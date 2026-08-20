"""Locks PSB-11 — the Appearance branding round trip and its least-privilege
boundary.

Research (Phase 3, .planning/phases/03-one-editor-familiar-chrome/03-RESEARCH.md)
established that the Appearance screen was ALREADY fully built when this phase
was planned: logo, title/tagline, favicon, primary/accent colour (with a live
WCAG-contrast check) and five curated font pairings all persist through
AdminConfig, and saving busts the public render cache via
`bump_public_cache_after_commit('global')` so the whole public site re-skins
with no deploy. This module exists to keep that true, not to build it.

Coverage that ALREADY lives in tests/test_public_site_runtime.py::TestTheming
and must NOT be duplicated here:
  - test_appearance_save_reskins: primary/accent colour RGB-triplet CSS vars
    and the 'classic' font pair putting Georgia into the render.
tests/test_public_site_runtime.py::TestRoleBoundary::
test_site_editor_can_reach_pages_but_not_appearance already asserts a Site
Editor gets a 403 on the Appearance SCREEN. This module extends that boundary
to the SAVE endpoint (T-03-18) -- the one an attacker would actually POST to.

Everything else this module covers (logo, title, tagline, favicon, ALL five
font pairings, invalid-value fallback, the live-preview markup, and the
no-deploy re-skin proven across two saves in one test) is new ground, not a
re-assertion of TestTheming.
"""

import re

import pytest

from app.services.public_theme import FONT_PAIRS


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def gadmin(db):
    from app.models import User, Role
    role = db.session.query(Role).filter_by(name='Global Admin').first()
    if not role:
        role = Role(name='Global Admin', description='Global Admin')
        db.session.add(role)
        db.session.flush()
    u = db.session.query(User).filter_by(username='gadmin').first()
    if not u:
        u = User(username='gadmin', email='gadmin@example.com',
                 is_approved=True, approval_status='approved')
        u.set_password('x')
        u.roles.append(role)
        db.session.add(u)
        db.session.flush()
    return u


@pytest.fixture
def gadmin_client(client, gadmin, db):
    with client.session_transaction() as sess:
        sess['_user_id'] = gadmin.id
        sess['_fresh'] = True
    return client


@pytest.fixture
def site_editor_client(client, db):
    from app.models import User, Role
    role = db.session.query(Role).filter_by(name='Site Editor').first()
    if not role:
        role = Role(name='Site Editor', description='Site Editor', sync_enabled=False)
        db.session.add(role)
        db.session.flush()
    u = db.session.query(User).filter_by(username='siteeditor_appearance').first()
    if not u:
        u = User(username='siteeditor_appearance', email='se_appearance@example.com',
                 is_approved=True, approval_status='approved')
        u.set_password('x')
        u.roles.append(role)
        db.session.add(u)
        db.session.flush()
    with client.session_transaction() as sess:
        sess['_user_id'] = u.id
        sess['_fresh'] = True
    return client


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

_BASELINE = {
    'title': 'ECS Test League',
    'tagline': 'A baseline tagline',
    'logo_url': '/static/img/baseline-logo.png',
    'favicon_url': '/static/img/baseline-favicon.png',
    'primary_hex': '#112233',
    'accent_hex': '#445566',
    'font_pair': 'modern',
}


def _save_appearance(client, **overrides):
    """POST the Appearance save with a COMPLETE payload (baseline merged with
    overrides). The route applies every key on every POST -- without a
    complete baseline each test would blank the fields it didn't send, and
    the next test would inherit the damage through the session-scoped app."""
    payload = dict(_BASELINE)
    payload.update(overrides)
    return client.post('/admin-panel/public-site/appearance/save', data=payload,
                       follow_redirects=True)


def _head_html(resp):
    body = resp.get_data(as_text=True)
    match = re.search(r'<head.*?</head>', body, re.DOTALL)
    assert match is not None, 'no <head>...</head> block found in response body'
    return match.group(0)


def _footer_html(resp):
    body = resp.get_data(as_text=True)
    match = re.search(r'<footer.*?</footer>', body, re.DOTALL)
    assert match is not None, 'no <footer>...</footer> block found in response body'
    return match.group(0)


# --------------------------------------------------------------------------- #
# 1. Branding fields round-trip to the public site
# --------------------------------------------------------------------------- #

class TestBrandingRoundTrip:
    def test_logo_title_tagline_round_trip_to_public_site(self, app, db, gadmin_client):
        r = _save_appearance(gadmin_client, title='Distinctive Title XYZ',
                             tagline='Distinctive tagline XYZ',
                             logo_url='/static/img/distinctive-logo-xyz.png')
        assert r.status_code == 200

        home = app.test_client().get('/preview/')
        assert home.status_code == 200
        head = _head_html(home)
        footer = _footer_html(home)
        body = home.get_data(as_text=True)

        assert 'og:site_name" content="Distinctive Title XYZ"' in head
        assert 'Distinctive Title XYZ' in body  # header <span>
        assert 'Distinctive tagline XYZ' in footer
        assert 'distinctive-logo-xyz.png' in body  # header img src

    def test_favicon_round_trips_into_rel_icon_link(self, app, db, gadmin_client):
        r = _save_appearance(gadmin_client, favicon_url='/static/img/distinctive-favicon-xyz.png')
        assert r.status_code == 200

        home = app.test_client().get('/preview/')
        head = _head_html(home)
        assert '<link rel="icon" href="/static/img/distinctive-favicon-xyz.png">' in head

    @pytest.mark.parametrize('pair_slug', sorted(FONT_PAIRS.keys()))
    def test_every_font_pairing_is_selectable_and_lands(self, app, db, gadmin_client, pair_slug):
        """Parametrised over FONT_PAIRS' actual keys (not a hard-coded list)
        so adding a sixth pairing without wiring it fails here.

        Three subtleties this assertion has to defend against, or it would be
        the exact vacuous test the plan warns about:
          1. Jinja/MarkupSafe autoescapes the theme_css string it interpolates,
             so quoted font names ('Trebuchet MS') land in the HTML as
             &#39;Trebuchet MS&#39;, not literally quoted -- a plain
             substring check on the quoted name would false-negative.
          2. The escaped entity &#39; itself CONTAINS a semicolon, so a naive
             "match up to the next semicolon" regex (`[^;]*`) truncates right
             inside the entity and never reaches the font name -- also a
             false negative. The fix is to anchor immediately after the
             colon and the optional (raw-or-entity) opening quote, not to
             bound the match by "no semicolon".
          3. base_public.html's own static fallback CSS hardcodes
             `var(--font-heading, 'Inter', system-ui, sans-serif)` UNESCAPED
             (it's literal template text, not a Jinja interpolation) -- so a
             bare "Inter" substring check would false-POSITIVE for the
             'modern' pair regardless of whether Appearance actually wired
             anything. Anchoring on `--font-heading:` (the CSS *declaration*
             colon) excludes that `var(--font-heading, ...)` *reference*
             (comma, not colon) and proves the admin-chosen value reached the
             actual :root declaration this phase's pipeline emits.
        """
        r = _save_appearance(gadmin_client, font_pair=pair_slug)
        assert r.status_code == 200

        home = app.test_client().get('/preview/')
        body = home.get_data(as_text=True)
        heading_stack = FONT_PAIRS[pair_slug]['heading']
        first_font_name = heading_stack.split(',')[0].strip().strip("'")
        declaration_pat = re.compile(
            r"--font-heading:\s*(?:&#39;|')?\s*" + re.escape(first_font_name))
        assert declaration_pat.search(body), (
            f'font pair {pair_slug!r} -- expected the --font-heading: CSS declaration '
            f'to carry {first_font_name!r}, not found in rendered page'
        )


# --------------------------------------------------------------------------- #
# 2. Invalid values fall back safely (T-03-19)
# --------------------------------------------------------------------------- #

class TestInvalidValueFallback:
    def test_invalid_hex_and_unknown_font_pair_fall_back_to_defaults(self, app, db, gadmin_client):
        from app.services.public_theme import DEFAULT_PRIMARY, DEFAULT_ACCENT

        r = _save_appearance(gadmin_client, primary_hex='not-a-color',
                             accent_hex='<script>alert(1)</script>',
                             font_pair='does-not-exist')
        assert r.status_code == 200

        home = app.test_client().get('/preview/')
        assert home.status_code == 200, \
            'a rejected value must fall back, never break public rendering'
        body = home.get_data(as_text=True)

        # The strict validators fall back to the brand defaults rather than
        # storing the malformed value into the public <style> block.
        assert 'not-a-color' not in body
        assert '<script>alert(1)</script>' not in body

        def _hex_to_rgb_triplet(hexval):
            h = hexval.lstrip('#')
            return f'{int(h[0:2], 16)} {int(h[2:4], 16)} {int(h[4:6], 16)}'

        assert f'--color-primary-rgb: {_hex_to_rgb_triplet(DEFAULT_PRIMARY)}' in body
        assert f'--color-blue-rgb: {_hex_to_rgb_triplet(DEFAULT_ACCENT)}' in body


# --------------------------------------------------------------------------- #
# 3. The live preview is served
# --------------------------------------------------------------------------- #

class TestLivePreviewServed:
    def test_appearance_screen_serves_preview_panel_and_repaint_script(self, app, db, gadmin_client):
        r = gadmin_client.get('/admin-panel/public-site/appearance')
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert 'id="theme-preview"' in html
        assert 'id="pv-heading"' in html
        assert 'id="pv-primary"' in html
        assert 'function refresh()' in html
        assert "addEventListener('input', refresh)" in html


# --------------------------------------------------------------------------- #
# 4. Re-skinning needs no deploy
# --------------------------------------------------------------------------- #

class TestNoDeployReskin:
    def test_second_save_changes_the_public_render_within_the_same_test(self, app, db, gadmin_client):
        """Save once, read a public page, save DIFFERENT values, read the
        SAME public page again -- proving the change is served immediately,
        not baked in at boot. Ordering is explicit within one test so a
        session-scoped cache cannot make this pass vacuously."""
        r1 = _save_appearance(gadmin_client, title='First Distinctive Title')
        assert r1.status_code == 200
        first_read = app.test_client().get('/preview/')
        first_body = first_read.get_data(as_text=True)
        assert 'First Distinctive Title' in first_body

        r2 = _save_appearance(gadmin_client, title='Second Distinctive Title')
        assert r2.status_code == 200
        second_read = app.test_client().get('/preview/')
        second_body = second_read.get_data(as_text=True)

        assert 'Second Distinctive Title' in second_body
        assert 'First Distinctive Title' not in second_body, \
            'the second save must be what a fresh public read serves -- no deploy required'

    def test_appearance_save_bumps_the_public_cache_global_version(self, app, db, gadmin_client, mock_redis):
        """The cache-bust actually happens (not just the DB row being
        written). Assert on the invalidation call itself, since the mocked
        Redis get() always returns None in tests -- a stale render can never
        mask a regression here, but it also can't be OBSERVED here, so the
        call is the correct thing to assert on."""
        mock_redis.incr.reset_mock()
        r = _save_appearance(gadmin_client, title='Cache Bust Check')
        assert r.status_code == 200
        assert mock_redis.incr.called, \
            'Appearance save must bump the public cache global version (public_cache.py)'
        bumped_keys = [c.args[0] for c in mock_redis.incr.call_args_list if c.args]
        assert 'public:ver:global' in bumped_keys, \
            f'expected a bump of public:ver:global, got calls: {mock_redis.incr.call_args_list}'


# --------------------------------------------------------------------------- #
# 5. Least-privilege boundary on the SAVE endpoint (T-03-18)
# --------------------------------------------------------------------------- #

class TestRoleBoundaryOnSaveEndpoint:
    def test_site_editor_refused_appearance_save_but_can_still_reach_pages(self, app, db, site_editor_client):
        """The existing runtime test (test_public_site_runtime.py::
        TestRoleBoundary::test_site_editor_can_reach_pages_but_not_appearance)
        already covers the GET screen AND that Pages stays reachable. This
        extends the boundary to the POST save endpoint -- the one an
        attacker would actually target, screen link hidden or not -- without
        re-asserting the screen-level check that test already owns."""
        save = site_editor_client.post('/admin-panel/public-site/appearance/save',
                                       data=dict(_BASELINE), follow_redirects=False)
        assert save.status_code == 403, \
            f'Site Editor must be refused the Appearance save endpoint, got {save.status_code}'

        pages = site_editor_client.get('/admin-panel/public-site/pages')
        assert pages.status_code in (200, 302), \
            'the boundary must be specific to Appearance -- Pages must stay reachable'
