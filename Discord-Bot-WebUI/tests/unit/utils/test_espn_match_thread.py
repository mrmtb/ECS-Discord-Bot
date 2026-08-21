"""
Regression tests for the ESPN integration behind MLS match threads.

Three production defects motivated these:

1. The scoreboard date was computed in UTC. ESPN buckets its scoreboard by US
   Eastern date, so every Sounders home fixture (a 6:30 PM PT kickoff is already
   the next day in UTC) queried the wrong day and got zero events back.

2. When that lookup came back empty, ``_build_espn_description`` returned a bare
   "Home vs Away" string. That non-empty string was then handed to the AI as
   ``espn_info``, which selects the "use the real stats" prompt branch -- with no
   stats in it. The model filled the hole by inventing league positions
   ("Austin 11th" when ESPN had them 14th).

3. ``ESPNAPIClient`` sent ``User-Agent: ECS-Discord-Bot/2.0``. site.api.espn.com
   403s that UA, so every live-reporting fetch failed.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.utils.espn_api_client import ESPNAPIClient
from app.utils.sync_espn_client import espn_scoreboard_date


class TestEspnScoreboardDate:
    """ESPN groups the scoreboard by US Eastern date, not UTC."""

    def test_evening_pacific_kickoff_stays_on_its_own_day(self):
        # Sounders vs Austin: 6:30 PM PT on 8/19 == 01:30 UTC on 8/20.
        # ESPN lists it on the 8/19 slate.
        kickoff = datetime(2026, 8, 20, 1, 30, tzinfo=timezone.utc)
        assert espn_scoreboard_date(kickoff) == "20260819"

    def test_late_pacific_kickoff_stays_on_its_own_day(self):
        # 7:30 PM PT on 8/19 == 02:30 UTC 8/20; ESPN still lists it on 8/19.
        kickoff = datetime(2026, 8, 20, 2, 30, tzinfo=timezone.utc)
        assert espn_scoreboard_date(kickoff) == "20260819"

    def test_afternoon_eastern_kickoff(self):
        kickoff = datetime(2026, 8, 19, 23, 30, tzinfo=timezone.utc)
        assert espn_scoreboard_date(kickoff) == "20260819"

    def test_naive_datetime_is_treated_as_utc(self):
        # MLSMatch.date_time is stored naive-UTC.
        assert espn_scoreboard_date(datetime(2026, 8, 20, 1, 30)) == "20260819"

    def test_none_returns_none(self):
        assert espn_scoreboard_date(None) is None

    def test_boundary_is_pacific_not_eastern(self):
        """
        ESPN's own leagues[0].calendar puts every day boundary at 08:00Z in
        winter / 07:00Z in summer -- 00:00 PST/PDT. A kickoff in the
        04:00Z-07:00Z window is therefore still the PREVIOUS Pacific day, even
        though Eastern has already rolled over. MLS never kicks off that late,
        but Concacaf / Leagues Cup fixtures can.
        """
        kickoff = datetime(2026, 8, 20, 5, 0, tzinfo=timezone.utc)  # 22:00 PDT 8/19
        assert espn_scoreboard_date(kickoff) == "20260819", (
            "Eastern would say 20260820 and return an empty slate"
        )

    def test_pacific_midnight_rolls_over(self):
        # 07:00Z in summer is exactly 00:00 PDT -> the new day.
        assert espn_scoreboard_date(
            datetime(2026, 8, 20, 7, 0, tzinfo=timezone.utc)) == "20260820"
        # ...and one minute earlier is still the old one.
        assert espn_scoreboard_date(
            datetime(2026, 8, 20, 6, 59, tzinfo=timezone.utc)) == "20260819"

    def test_winter_boundary_tracks_dst(self):
        # 08:00Z in winter is 00:00 PST -> the new day.
        assert espn_scoreboard_date(
            datetime(2026, 2, 21, 8, 0, tzinfo=timezone.utc)) == "20260221"
        assert espn_scoreboard_date(
            datetime(2026, 2, 21, 7, 59, tzinfo=timezone.utc)) == "20260220"


class TestCompetitorsWithoutADate:
    """
    The scoreboard needs a correct date; /summary?event={id} does not. Resolving
    competitors from the summary first means a stale or rescheduled
    MLSMatch.date_time can no longer silently blank out the description.
    """

    def _client(self, summary_status=200, summary_json=None):
        from app.utils.sync_espn_client import SyncESPNClient
        c = SyncESPNClient()
        c.session = MagicMock()
        resp = MagicMock()
        resp.status_code = summary_status
        resp.json.return_value = summary_json or {}
        c.session.get.return_value = resp
        return c

    _SUMMARY = {
        "header": {"competitions": [{"competitors": [
            {"homeAway": "home", "team": {"id": "18267", "displayName": "FC Cincinnati"}},
            {"homeAway": "away", "team": {"id": "9726", "displayName": "Seattle Sounders FC"}},
        ]}]}
    }

    def test_resolves_with_no_match_date_supplied(self):
        c = self._client(summary_json=self._SUMMARY)
        got = c.get_event_competitors("761743", "usa.1")  # note: no match_date
        assert got == {
            "home_team_id": "18267", "home_team_name": "FC Cincinnati",
            "away_team_id": "9726", "away_team_name": "Seattle Sounders FC",
        }

    def test_summary_is_tried_before_the_scoreboard(self):
        c = self._client(summary_json=self._SUMMARY)
        c.get_event_competitors("761743", "usa.1", match_date="20260822")
        called = [call.args[0] for call in c.session.get.call_args_list]
        assert called and called[0].endswith("/usa.1/summary"), called
        assert not any("scoreboard" in u for u in called), "should not have needed the scoreboard"

    def test_falls_back_to_scoreboard_when_summary_fails(self):
        c = self._client(summary_status=403)
        c.get_event_competitors("761743", "usa.1", match_date="20260822")
        called = [call.args[0] for call in c.session.get.call_args_list]
        assert any("scoreboard" in u for u in called), called


class TestEspnApiClientNotBlocked:
    """The summary fetch must not use a UA/host combination ESPN 403s."""

    def test_summary_host_is_the_non_ua_gated_one(self):
        assert "site.web.api.espn.com" in ESPNAPIClient.BASE_URL

    def test_no_custom_bot_user_agent(self):
        client = ESPNAPIClient()
        ua = client.session.headers.get("User-Agent", "")
        assert "ECS-Discord-Bot" not in ua


class TestBuildEspnDescriptionNoFakeData:
    """No ESPN data must mean *no* description, never a stat-free stand-in."""

    def _patch_client(self, client):
        return patch(
            "app.utils.sync_espn_client.get_sync_espn_client",
            return_value=client,
        )

    def test_returns_none_when_event_not_found(self):
        from app.tasks.match_scheduler import _build_espn_description

        client = MagicMock()
        client.get_event_competitors.return_value = None

        with self._patch_client(client):
            result = _build_espn_description(
                "761736", "Seattle Sounders FC", "Austin FC",
                "MLS", match_date="20260819",
            )

        assert result is None, (
            "A bare 'A vs B' string gets fed to the AI as espn_info and makes "
            "it invent standings; the caller needs to see None instead."
        )

    def test_returns_none_when_team_lookups_fail(self):
        from app.tasks.match_scheduler import _build_espn_description

        client = MagicMock()
        client.get_event_competitors.return_value = {
            "home_team_id": "9726", "away_team_id": "20906",
            "home_team_name": "Seattle Sounders FC", "away_team_name": "Austin FC",
        }
        client.get_team_info.return_value = None
        client.get_head_to_head.return_value = None

        with self._patch_client(client):
            result = _build_espn_description(
                "761736", "Seattle Sounders FC", "Austin FC",
                "MLS", match_date="20260819",
            )

        assert result is None

    def test_returns_real_records_when_espn_answers(self):
        from app.tasks.match_scheduler import _build_espn_description

        client = MagicMock()
        client.get_event_competitors.return_value = {
            "home_team_id": "9726", "away_team_id": "20906",
            "home_team_name": "Seattle Sounders FC", "away_team_name": "Austin FC",
        }
        client.get_team_info.side_effect = [
            {"wins": 10, "ties": 6, "losses": 8, "standing_summary": "11th in MLS"},
            {"wins": 9, "ties": 5, "losses": 10, "standing_summary": "14th in MLS"},
        ]
        client.get_head_to_head.return_value = None

        with self._patch_client(client):
            result = _build_espn_description(
                "761736", "Seattle Sounders FC", "Austin FC",
                "MLS", match_date="20260819",
            )

        assert result is not None
        assert "10W-6D-8L" in result
        assert "11th" in result
        assert "14th" in result
