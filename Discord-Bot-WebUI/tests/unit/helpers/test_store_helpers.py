"""
Store helper unit tests.

app/store_helpers.py now carries the whole one-order-per-season rule and the
colour/size rule for BOTH the web store and the Flutter API. Before it existed
those rules were copy-pasted across five call sites and had already drifted:
the browser demanded a colour and a size on every item and posted the sentinels
'N/A' / 'One Size' when an item declared neither, while the mobile API wrote
NULL -- so the same item ordered from a phone and from a browser produced
different rows.

These tests pin the two behaviours that outage turned on:
  * an order with eligibility_reset_at set keeps its season but stops blocking
  * a field is required only when the item actually offers choices
"""
import pytest
from datetime import datetime
from unittest.mock import MagicMock

from app.store_helpers import (
    STORE_LEAGUE_TYPE,
    check_order_eligibility,
    get_blocking_order,
    get_current_store_season,
    parse_item_options,
    validate_order_options,
)


# =============================================================================
# Fakes -- these helpers take a plain SQLAlchemy Session, so a recording stub is
# enough and keeps the suite DB-free.
# =============================================================================

class _FakeQuery:
    def __init__(self, result):
        self._result = result
        self.filters = []

    def filter(self, *criteria):
        self.filters.extend(criteria)
        return self

    def filter_by(self, **kwargs):
        self.filters.append(kwargs)
        return self

    def first(self):
        return self._result


class _Sequence:
    """Explicit marker for "return a different row per query".

    Not a bare callable: MagicMock is itself callable, so sniffing with
    callable() would silently invoke the row instead of returning it.
    """
    def __init__(self, *results):
        self._it = iter(results)

    def next(self):
        return next(self._it)


class _FakeSession:
    def __init__(self, result=None):
        self._result = result
        self.queries = []

    def query(self, model):
        row = self._result.next() if isinstance(self._result, _Sequence) else self._result
        q = _FakeQuery(row)
        self.queries.append((model, q))
        return q


def _item(colors=None, sizes=None):
    item = MagicMock()
    item.available_colors = colors
    item.available_sizes = sizes
    return item


def _season(id=12, name='2026 Fall'):
    season = MagicMock()
    season.id = id
    season.name = name
    return season


def _order(id=44, reset_at=None):
    order = MagicMock()
    order.id = id
    order.eligibility_reset_at = reset_at
    return order


# =============================================================================
# Season resolution
# =============================================================================

def test_current_season_queries_pub_league_only():
    """Summer ('PL Third') and ECS FC seasons must never be picked up here."""
    season = _season()
    session = _FakeSession(season)

    assert get_current_store_season(session) is season

    _model, query = session.queries[0]
    assert {'league_type': STORE_LEAGUE_TYPE, 'is_current': True} in query.filters


def test_no_current_season_blocks_ordering_rather_than_guessing():
    eligible, reason, season, blocking = check_order_eligibility(_FakeSession(None), user_id=7)

    assert eligible is False
    assert season is None
    assert blocking is None
    assert 'No current season' in reason


# =============================================================================
# The one-order-per-season rule
# =============================================================================

def test_existing_order_blocks_and_names_the_season():
    """The message is what the Flutter app renders -- keep the wording stable."""
    season = _season(name='2026 Fall')
    # First query resolves the season, second finds the blocking order.
    session = _FakeSession(_Sequence(season, _order()))

    eligible, reason, got_season, blocking = check_order_eligibility(session, user_id=7)

    assert eligible is False
    assert got_season is season
    assert blocking is not None
    assert '2026 Fall' in reason
    assert 'Only one order per season is allowed.' in reason


def test_no_existing_order_is_eligible():
    season = _season()
    session = _FakeSession(_Sequence(season, None))

    eligible, reason, got_season, blocking = check_order_eligibility(session, user_id=7)

    assert eligible is True
    assert reason is None
    assert got_season is season
    assert blocking is None


def test_blocking_order_query_excludes_reset_orders():
    """The reset must work by IGNORING stamped rows, never by nulling season_id.

    The old implementation set season_id = NULL to unblock ordering, which
    erased the order from every season-scoped query permanently.
    """
    session = _FakeSession(None)
    season = _season(id=12)

    get_blocking_order(session, user_id=7, season=season)

    _model, query = session.queries[0]
    rendered = ' '.join(str(c) for c in query.filters)
    assert 'eligibility_reset_at IS NULL' in rendered
    assert 'season_id' in rendered


def test_blocking_order_without_season_is_none():
    session = _FakeSession(_order())
    assert get_blocking_order(session, user_id=7, season=None) is None
    assert session.queries == []


# =============================================================================
# Colour / size validation -- the web/mobile divergence
# =============================================================================

def test_item_with_no_options_needs_no_selection_and_stores_null():
    """This is the case the browser could not order at all, and the case where
    web wrote 'N/A' / 'One Size' while mobile wrote NULL."""
    ok, message, color, size = validate_order_options(_item(), None, None)

    assert ok is True
    assert message is None
    assert color is None
    assert size is None


def test_item_with_no_options_ignores_a_stray_selection():
    ok, _message, color, size = validate_order_options(_item(), 'N/A', 'One Size')

    assert ok is True
    assert color is None
    assert size is None


def test_missing_colour_rejected_when_item_offers_colours():
    ok, message, _c, _s = validate_order_options(_item(colors='["Blue", "Red"]'), '', 'L')

    assert ok is False
    assert message == 'Color selection is required for this item.'


def test_colour_must_be_one_of_the_declared_options():
    ok, message, _c, _s = validate_order_options(_item(colors='["Blue", "Red"]'), 'Purple', None)

    assert ok is False
    assert 'Available: Blue, Red' in message


def test_missing_size_rejected_when_item_offers_sizes():
    ok, message, _c, _s = validate_order_options(_item(sizes='["S", "M"]'), None, '')

    assert ok is False
    assert message == 'Size selection is required for this item.'


def test_valid_selection_is_returned_trimmed():
    item = _item(colors='["Blue"]', sizes='["L"]')

    ok, message, color, size = validate_order_options(item, '  Blue ', ' L  ')

    assert ok is True
    assert message is None
    assert (color, size) == ('Blue', 'L')


def test_none_selection_does_not_raise():
    """A client sending an explicit JSON null used to AttributeError on .strip()."""
    ok, _message, color, size = validate_order_options(_item(), None, None)
    assert ok is True and color is None and size is None


# =============================================================================
# Option parsing -- these columns are TEXT, and some rows hold Python repr
# quoting rather than JSON.
# =============================================================================

@pytest.mark.parametrize('raw,expected', [
    (None, []),
    ('', []),
    ('[]', []),
    ('["S", "M"]', ['S', 'M']),
    ("['S', 'M']", ['S', 'M']),        # Python repr quoting, seen in real rows
    ('not json at all', []),           # never raise on bad data
    ('{"a": 1}', []),                  # valid JSON, wrong shape
    # THE ONE THAT MATTERED. The model declares these columns db.Text, but the
    # production database holds json/jsonb, and psycopg2 typecasts by OID -- so
    # the value arrives already decoded. Every read site used to call
    # json.loads() on it, get TypeError, and swallow it into []: the mobile API
    # reported that NO item had any colours or sizes, and server-side
    # colour/size validation silently never fired. The SQLite test database has
    # TEXT columns, so no fixture-backed test can reproduce it -- only this one.
    (['S', 'M'], ['S', 'M']),
    ([], []),
    (['S', None, '  ', 'L'], ['S', 'L']),   # skip nulls/blanks the driver hands back
    ({'a': 1}, []),                          # jsonb object, wrong shape
])
def test_parse_item_options(raw, expected):
    assert parse_item_options(raw) == expected


def test_validate_order_options_with_driver_decoded_lists():
    """Validation must fire when the column arrives as a real list, not a string.

    With the old parser this returned ok=True and stored NULL, so an item with
    declared colours could be ordered without choosing one.
    """
    item = _item(colors=['Blue', 'Red'], sizes=['S', 'M'])

    ok, message, _c, _s = validate_order_options(item, '', 'S')
    assert ok is False
    assert message == 'Color selection is required for this item.'

    ok, message, color, size = validate_order_options(item, 'Blue', 'S')
    assert ok is True and (color, size) == ('Blue', 'S')

    ok, message, _c, _s = validate_order_options(item, 'Purple', 'S')
    assert ok is False and 'Available: Blue, Red' in message
