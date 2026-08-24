# tests/test_public_site_builder.py

"""
Load-bearing tests for the public-site builder (section model, sanitizer,
cache versioning, editor save protocol invariants).

The pure-python suites (sanitizer / section schema / cache keys / frame
headers) run with no app or database. App-dependent suites use the shared
conftest fixtures where available and skip cleanly where not — the adversarial
gate treats a skip as "needs the container run", never as a pass.
"""

import pytest


# --------------------------------------------------------------------------- #
# Sanitizer
# --------------------------------------------------------------------------- #

class TestSanitizer:
    def test_strips_script_keeps_formatting(self):
        from app.utils.html_sanitizer import sanitize_html
        out = sanitize_html('<p>hi <script>alert(1)</script><em>there</em></p>')
        assert '<script' not in out
        assert '<em>there</em>' in out

    def test_strips_event_handlers_and_style(self):
        from app.utils.html_sanitizer import sanitize_html
        out = sanitize_html('<p onclick="x()" style="color:red">a</p>')
        assert 'onclick' not in out and 'style=' not in out

    def test_javascript_href_neutered(self):
        from app.utils.html_sanitizer import sanitize_html
        out = sanitize_html('<a href="javascript:alert(1)">x</a>')
        assert 'javascript:' not in out

    def test_safe_link_gets_rel(self):
        from app.utils.html_sanitizer import sanitize_html
        out = sanitize_html('<a href="https://ok.com" target="_blank">x</a>')
        assert 'noopener' in out and 'href="https://ok.com"' in out

    def test_iframe_and_style_tags_removed(self):
        from app.utils.html_sanitizer import sanitize_html
        out = sanitize_html('<style>body{}</style><iframe src="x"></iframe><p>ok</p>')
        assert '<style' not in out and '<iframe' not in out and '<p>ok</p>' in out

    def test_hex_color_validation(self):
        from app.utils.html_sanitizer import validate_hex_color
        assert validate_hex_color('#40b050') == '#40b050'
        assert validate_hex_color('#fff') == '#fff'
        assert validate_hex_color("');alert(1)//", '#111111') == '#111111'
        assert validate_hex_color('red', None) is None

    def test_link_url_schemes(self):
        from app.utils.html_sanitizer import is_safe_link_url
        assert is_safe_link_url('/news/foo')
        assert is_safe_link_url('https://x.com')
        assert is_safe_link_url('mailto:a@b.c')
        assert not is_safe_link_url('javascript:alert(1)')
        assert not is_safe_link_url('data:text/html,x')
        assert not is_safe_link_url('vbscript:x')

    def test_link_url_rejects_protocol_relative(self):
        """Protocol-relative URLs start with '/' but navigate off-site.

        These values are Site-Editor-writable and render on public pages
        (desktop nav, mobile nav, and — since Phase 2 — the footer), so a
        '//evil.tld' link would send real visitors off-domain under our own
        chrome. The '/\\evil.tld' form is included because several browsers
        normalize a backslash here to a forward slash.
        """
        from app.utils.html_sanitizer import is_safe_link_url
        assert not is_safe_link_url('//evil.example.com/phish')
        assert not is_safe_link_url('//attacker.tld')
        assert not is_safe_link_url('/\\evil.tld')
        # Genuine same-site paths and anchors must still pass.
        assert is_safe_link_url('/about')
        assert is_safe_link_url('/news/foo')
        assert is_safe_link_url('#top')

    def test_embed_urls(self):
        from app.utils.html_sanitizer import build_embed_url
        assert build_embed_url('https://www.youtube.com/watch?v=dQw4w9WgXcQ') \
            == 'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ'
        assert build_embed_url('https://youtu.be/dQw4w9WgXcQ') \
            == 'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ'
        assert build_embed_url('https://vimeo.com/123456789') \
            == 'https://player.vimeo.com/video/123456789'
        assert build_embed_url('https://evil.com/embed/x') is None
        assert build_embed_url('http://www.youtube.com/watch?v=abc12345') is None  # http


# --------------------------------------------------------------------------- #
# Section schema validation
# --------------------------------------------------------------------------- #

def _doc(blocks, stype='content', **settings):
    return {'sections': [{'type': stype, 'settings': settings, 'blocks': blocks}]}


class TestSectionSchema:
    def test_unknown_block_dropped_with_note(self):
        from app.services.section_schema import validate_sections
        doc, notes = validate_sections(_doc([{'type': 'nope'}]))
        assert doc['sections'][0]['blocks'] == []
        assert any('nope' in n for n in notes)

    def test_embed_raw_admin_only(self):
        from app.services.section_schema import validate_sections
        blocks = [{'type': 'embed_raw', 'html': '<p>x</p>'}]
        vol, _ = validate_sections(_doc(blocks), is_admin=False)
        adm, _ = validate_sections(_doc(blocks), is_admin=True)
        assert vol['sections'][0]['blocks'] == []
        assert adm['sections'][0]['blocks'][0]['type'] == 'embed_raw'

    def test_unsafe_button_link_drops_block(self):
        from app.services.section_schema import validate_sections
        doc, _ = validate_sections(_doc(
            [{'type': 'button', 'label': 'x', 'link': {'kind': 'url', 'url': 'javascript:x'}}]))
        assert doc['sections'][0]['blocks'] == []

    def test_image_ref_requires_asset_or_static_url(self):
        # Image blocks are always KEPT (they render an editor placeholder until
        # configured), but an unsafe/foreign URL is stripped to None so it can
        # never reach a src attribute; only asset_id or same-app /static survive.
        from app.services.section_schema import validate_sections
        doc, _ = validate_sections(_doc([
            {'type': 'image', 'image': {'url': 'https://evil.com/x.jpg'}},
            {'type': 'image', 'image': {'url': '/static/img/publeague/ok.jpg'}},
            {'type': 'image', 'image': {'asset_id': 7}},
            {'type': 'image', 'image': {'url': '/static/x" onerror=alert(1)'}},
        ]))
        imgs = [b['image'] for b in doc['sections'][0]['blocks']]
        assert imgs == [None, {'url': '/static/img/publeague/ok.jpg'},
                        {'asset_id': 7}, None]

    def test_empty_media_blocks_kept_as_placeholders(self):
        from app.services.section_schema import validate_sections
        doc, _ = validate_sections(_doc([
            {'type': 'image', 'image': {}},
            {'type': 'gallery', 'items': []},
            {'type': 'video', 'url': ''},
            {'type': 'map', 'url': ''},
        ]))
        kept = [b['type'] for b in doc['sections'][0]['blocks']]
        assert kept == ['image', 'gallery', 'video', 'map']

    def test_link_with_html_metachars_rejected(self):
        from app.services.section_schema import validate_sections
        doc, _ = validate_sections(_doc([
            {'type': 'button', 'label': 'x',
             'link': {'kind': 'url', 'url': 'https://x"><img src=x onerror=alert(1)>'}}]))
        # unsafe link -> button has no valid link -> dropped
        assert doc['sections'][0]['blocks'] == []

    def test_settings_coerced_to_enums(self):
        from app.services.section_schema import validate_sections
        doc, _ = validate_sections(_doc([], stype='hero', size='huge', overlay='medium',
                                        bg_color='not-a-color'))
        s = doc['sections'][0]['settings']
        assert s['size'] == 'md' and s['overlay'] == 'medium'
        assert 'bg_color' not in s

    def test_ids_generated_and_stable_format(self):
        from app.services.section_schema import validate_sections
        doc, _ = validate_sections(_doc([{'type': 'heading', 'html': 'x'}]))
        import re
        assert re.match(r'^s_[a-z0-9]{4,16}$', doc['sections'][0]['id'])
        assert re.match(r'^b_[a-z0-9]{4,16}$', doc['sections'][0]['blocks'][0]['id'])

    def test_video_url_normalized(self):
        from app.services.section_schema import validate_sections
        doc, _ = validate_sections(_doc(
            [{'type': 'video', 'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'}]))
        b = doc['sections'][0]['blocks'][0]
        assert b['embed_src'].startswith('https://www.youtube-nocookie.com/embed/')

    def test_caps_enforced(self):
        from app.services.section_schema import (validate_sections, MAX_SECTIONS)
        doc, notes = validate_sections(
            {'sections': [{'type': 'content', 'settings': {}, 'blocks': []}] * (MAX_SECTIONS + 5)})
        assert len(doc['sections']) == MAX_SECTIONS
        assert any('truncated' in n for n in notes)

    def test_collect_asset_ids(self):
        from app.services.section_schema import validate_sections, collect_asset_ids
        doc, _ = validate_sections({'sections': [
            {'type': 'hero', 'settings': {'image': {'asset_id': 3}}, 'blocks': [
                {'type': 'image', 'image': {'asset_id': 4}},
                {'type': 'gallery', 'items': [{'image': {'asset_id': 5}}]}]}]},
            is_admin=True)
        assert collect_asset_ids(doc) == {3, 4, 5}

    def test_malformed_input_never_raises(self):
        from app.services.section_schema import validate_sections
        for bad in (None, [], 'x', {'sections': 'x'}, {'sections': [None, 1, 'x']}):
            doc, _ = validate_sections(bad)
            assert doc['sections'] == []


# --------------------------------------------------------------------------- #
# Frame headers
# --------------------------------------------------------------------------- #

class TestFrameHeaders:
    def test_preview_frameable_same_origin_only(self):
        from app.utils.frame_headers import frame_headers_for_path
        h = frame_headers_for_path('/preview/about')
        assert h['X-Frame-Options'] == 'SAMEORIGIN'
        assert "frame-ancestors 'self'" in h['Content-Security-Policy']

    def test_everything_else_deny(self):
        from app.utils.frame_headers import frame_headers_for_path
        for p in ('/', '/admin-panel/site-editor/1', '/auth/login', '/previews'):
            assert frame_headers_for_path(p)['X-Frame-Options'] == 'DENY'


# --------------------------------------------------------------------------- #
# App-dependent suites (PUBLIC_ONLY surface, editor protocol) — these need the
# app factory + DB; they run in the container test env and skip elsewhere.
# --------------------------------------------------------------------------- #

class TestPublicRenderIntegration:
    """The public routes must actually render through the section pipeline.
    Uses the db fixture so the model tables exist (create_all)."""

    def test_no_unguarded_admin_url_in_public_views(self):
        # No public VIEW may build an admin_panel URL unguarded — only the
        # sanctioned _edit_url()/portal_url() helpers may. We AST-parse for real
        # url_for('admin_panel.*') Call nodes (ignoring docstrings/comments,
        # which is why a naive line-grep would false-positive on prose).
        import ast
        import inspect
        import app.public_site as ps
        tree = ast.parse(inspect.getsource(ps))
        offenders = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == 'url_for' and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                    and node.args[0].value.startswith('admin_panel.')):
                offenders.append(node.args[0].value)
        assert offenders == [], f'unguarded admin url_for in public views: {offenders}'

    def test_public_pages_render(self, app, db):
        client = app.test_client()
        for path in ('/preview/', '/preview/about', '/preview/faqs',
                     '/preview/register', '/preview/contact', '/preview/news',
                     '/preview/calendar', '/preview/calendar?view=month'):
            resp = client.get(path)
            assert resp.status_code in (200, 302), (path, resp.status_code)

    def test_guide_renders_full_content(self, app, db):
        # The guide builds from app/seeds/guide_content.json into a real
        # multi-chapter page with the lexicon glossary + anchor nav.
        resp = app.test_client().get('/preview/guide')
        assert resp.status_code == 200
        body = resp.data.decode('utf-8', 'ignore')
        assert 'The Pub League Guide' in body
        assert 'Lexicon' in body or 'lexicon' in body
        assert 'id="pub-league-classic-priorities"' in body  # chapter anchor
        assert '<dt>' in body  # lexicon glossary term rendered

    def test_home_degrades_without_content_rows(self, app, db):
        # Even with no seeded home_* rows, the home route renders from defaults
        # (graceful degradation) rather than 404ing.
        resp = app.test_client().get('/preview/')
        assert resp.status_code == 200
        assert b'ECS Pub League' in resp.data or b'soccer' in resp.data.lower()

    def test_dynamic_page_copy_overrides_render(self, app, db):
        # Appearance-screen copy keys must flow through to the news/calendar
        # banners (and blank/unset keys must fall back to shipped defaults).
        with app.app_context():
            from app.models.admin_config import AdminConfig
            AdminConfig.set_setting('public_calendar_hero_title', 'Fixture Calendar',
                                    category='public_site', auto_commit=True)
            AdminConfig.set_setting('public_calendar_cta_heading', 'Fixture CTA',
                                    category='public_site', auto_commit=True)
        client = app.test_client()
        body = client.get('/preview/calendar').data.decode()
        assert 'Fixture Calendar' in body
        assert 'Fixture CTA' in body
        news = client.get('/preview/news').data.decode()
        assert 'News' in news  # default title still applies (key never saved)


class TestSrcsetParts:
    """One srcset implementation for the whole public site (media_service)."""

    def test_variants_produce_srcset_and_webp(self):
        from app.services.media_service import srcset_parts
        srcset, webp = srcset_parts(
            '/static/img/publeague/pic.jpg',
            {'widths': [320, 640], 'webp': True}, width=1000, ver='?v=abc123')
        assert srcset == ('/static/img/publeague/pic-w320.jpg?v=abc123 320w, '
                          '/static/img/publeague/pic-w640.jpg?v=abc123 640w, '
                          '/static/img/publeague/pic.jpg?v=abc123 1000w')
        assert webp == ('/static/img/publeague/pic-w320.webp?v=abc123 320w, '
                        '/static/img/publeague/pic-w640.webp?v=abc123 640w')

    def test_no_variants_means_no_srcset(self):
        from app.services.media_service import srcset_parts
        assert srcset_parts('/static/img/x.jpg', None) == (None, None)
        assert srcset_parts('/static/img/x.jpg', {'widths': []}) == (None, None)
        assert srcset_parts(None, {'widths': [320]}) == (None, None)


class TestDynamicPageCache:
    """The news/calendar full-page cache: hit path, bounded key space."""

    def test_calendar_cached_and_category_not_cached(self, app, db, monkeypatch):
        import app.services.public_cache as pc
        store, calls = {}, {'store': 0}
        monkeypatch.setattr(pc, 'cache_key',
                            lambda host, path, scope='page', slug=None: f'k:{host}:{path}')
        monkeypatch.setattr(pc, 'get_cached_html', store.get)
        monkeypatch.setattr(pc, 'store_html',
                            lambda k, h: (store.__setitem__(k, h),
                                          calls.__setitem__('store', calls['store'] + 1)))
        monkeypatch.setattr(pc, 'acquire_render_lock', lambda k: True)
        monkeypatch.setattr(pc, 'get_stale_html', lambda k: None)
        monkeypatch.setenv('PUBLIC_ONLY', 'true')
        client = app.test_client()

        r1 = client.get('/preview/calendar')
        assert r1.status_code == 200
        assert calls['store'] == 1
        r2 = client.get('/preview/calendar')
        assert r2.status_code == 200 and r2.data == r1.data
        assert calls['store'] == 1  # second hit came from the cache
        assert r2.headers.get('Cache-Control') == 'public, max-age=60'

        # Free-text ?category is served live — an attacker must not be able to
        # mint cache keys.
        before = dict(store)
        r3 = client.get('/preview/news?category=zzz-not-real')
        assert r3.status_code == 200
        assert store == before

    def test_degraded_render_not_stored(self, app, db, monkeypatch):
        # A render that hit a graceful-degradation except (transient DB error)
        # must never be written to the cache — one blip must not serve an
        # empty page to every anonymous visitor for the TTL.
        import app.services.public_cache as pc
        import app.services.media_service as ms
        store = {}
        monkeypatch.setattr(pc, 'cache_key',
                            lambda host, path, scope='page', slug=None: f'k:{path}')
        monkeypatch.setattr(pc, 'get_cached_html', store.get)
        monkeypatch.setattr(pc, 'store_html', lambda k, h: store.__setitem__(k, h))
        monkeypatch.setattr(pc, 'acquire_render_lock', lambda k: True)
        monkeypatch.setattr(pc, 'get_stale_html', lambda k: None)
        monkeypatch.setenv('PUBLIC_ONLY', 'true')

        def _boom(session, urls):
            raise RuntimeError('db blip')
        monkeypatch.setattr(ms, 'render_info_for_urls', _boom)

        resp = app.test_client().get('/preview/news')
        assert resp.status_code == 200          # degraded page still serves
        assert store == {}                       # ...but is never cached
        assert resp.headers.get('Cache-Control') == 'no-store'


class TestPageTemplates:
    """Add-New-Page starter templates must be valid section docs — a template
    that loses blocks in validation would silently seed a broken skeleton."""

    def test_every_template_validates_losslessly(self):
        from app.services.section_converter import PAGE_TEMPLATES, build_page_template
        from app.services.section_schema import validate_sections
        for t in PAGE_TEMPLATES:
            built = build_page_template(t['key'], 'Summer Cup')
            doc, notes = validate_sections({'v': 1, 'sections': built}, is_admin=False)
            assert len(doc['sections']) == len(built), (t['key'], notes)
            for raw_s, val_s in zip(built, doc['sections']):
                assert len(val_s['blocks']) == len(raw_s['blocks']), (t['key'], notes)

    def test_blank_and_unknown_are_empty(self):
        from app.services.section_converter import build_page_template
        assert build_page_template('blank', 'X') == []
        assert build_page_template('nope', 'X') == []

    def test_title_is_escaped_into_heading(self):
        from app.services.section_converter import build_page_template
        sections = build_page_template('info', '<script>alert(1)</script> & Co')
        h1 = sections[0]['blocks'][0]
        assert h1['type'] == 'heading'
        assert '<script>' not in h1['html']
        assert '&amp; Co' in h1['html']

    def test_template_keys_match_metadata(self):
        # Every advertised template must actually build something (except blank).
        from app.services.section_converter import PAGE_TEMPLATES, build_page_template
        for t in PAGE_TEMPLATES:
            built = build_page_template(t['key'], 'X')
            if t['key'] != 'blank':
                assert built, f"template {t['key']} built an empty skeleton"


# --------------------------------------------------------------------------- #
# Rebuild — the design system reaching the pages
# --------------------------------------------------------------------------- #

class _DeadSession:
    """A session whose every query raises, so the builders run their own
    degradation path. That is what a deploy window looks like, and it keeps
    these tests database-free."""

    def query(self, *a, **k):
        raise RuntimeError('no database')


def _built(monkeypatch, slug):
    """Build one page's document exactly as `rebuild_public_pages` would."""
    from app.models.admin_config import AdminConfig
    from app.services import section_converter as sc
    monkeypatch.setattr(AdminConfig, 'get_setting',
                        staticmethod(lambda key, default=None: default))
    builders = {'home': lambda: sc.build_home_doc(_DeadSession()),
                'register': sc.build_register_doc,
                'contact': sc.build_contact_doc,
                'faqs': sc.build_faqs_doc,
                'guests': sc.build_guests_doc}
    return builders[slug]()


def _all_blocks(doc):
    return [b for s in doc['sections'] for b in s['blocks']]


class TestRebuiltDocuments:
    """These guard the failure that made the previous redesign a no-op on the
    live site: a builder emits a structural key, macros.html consumes it, and
    section_schema drops it in between because `_validate_block` rebuilds every
    block from an allowlist. Nothing errors — the page just quietly renders in
    the old shape."""

    SLUGS = ('home', 'register', 'contact', 'faqs', 'guests')

    @pytest.mark.parametrize('slug', SLUGS)
    def test_no_block_is_dropped_by_validation(self, monkeypatch, slug):
        from app.services.section_schema import validate_sections
        raw = _built(monkeypatch, slug)
        doc, notes = validate_sections(raw, is_admin=True)
        assert len(doc['sections']) == len(raw['sections']), notes
        for raw_s, out_s in zip(raw['sections'], doc['sections']):
            assert len(out_s['blocks']) == len(raw_s['blocks']), notes

    def test_structural_keys_survive_validation(self, monkeypatch):
        from app.services.section_schema import validate_sections
        doc, _ = validate_sections(_built(monkeypatch, 'home'), is_admin=True)
        blocks = _all_blocks(doc)
        keys = {k for b in blocks for k in b}
        # slot keeps a heading in the same <section> as the grid it labels;
        # prominence is the two-h2-tier hierarchy; cta_kind puts a division's
        # live action inside its own block; treatment is the duotone.
        for key in ('slot', 'prominence', 'cta_kind', 'treatment'):
            assert key in keys, f'{key} was stripped by validate_sections'
        assert any(s['settings'].get('treatment')
                   for s in doc['sections'] if s['type'] == 'hero')

    def test_home_has_no_icon_card_grid(self, monkeypatch):
        """design.md DO-NOT 16. Two icon-above-heading three-ups on one page was
        the single most recognisable AI tell on the old home page; the value
        propositions are a rule-separated list now, and the join sequence is a
        real step ladder."""
        from app.services.section_schema import validate_sections
        doc, _ = validate_sections(_built(monkeypatch, 'home'), is_admin=True)
        iconed = [b for b in _all_blocks(doc)
                  if b['type'] == 'card' and b.get('icon')]
        assert not iconed, f'{len(iconed)} icon cards survived on the home page'
        assert sum(1 for b in _all_blocks(doc) if b['type'] == 'steps') == 2

    def test_home_spends_brand_green_once(self, monkeypatch):
        """Flat brand green used to ground every photoless hero, scrim every
        photographic one and paint every closing band — the same rectangle four
        or five times a page. It buys exactly one moment now.

        Which section gets it is a design decision and may move (it is currently
        the join sequence, with the closing argument on the ink ground); that it
        is spent ONCE is the rule.
        """
        from app.services.section_schema import validate_sections
        doc, _ = validate_sections(_built(monkeypatch, 'home'), is_admin=True)
        brand = [s for s in doc['sections'] if s['theme'] == 'brand']
        assert len(brand) == 1, f'{len(brand)} brand-green sections'
        # and the page still has a real dark anchor besides the green
        assert any(s['theme'] == 'dark' for s in doc['sections']), \
            'no ink-ground section — the page has no weight anywhere'

    @pytest.mark.parametrize('slug', ('register', 'faqs'))
    def test_photoless_hero_is_not_brand_green(self, monkeypatch, slug):
        from app.services.section_schema import validate_sections
        doc, _ = validate_sections(_built(monkeypatch, slug), is_admin=True)
        heroes = [s for s in doc['sections']
                  if s['type'] == 'hero' and not s['settings'].get('image')]
        assert heroes, f'{slug} has no photoless hero to check'
        for h in heroes:
            assert h['theme'] != 'brand', f'{slug} hero is still a green slab'

    def test_divisions_own_their_call_to_action(self, monkeypatch):
        """design.md DO-NOT 18. The division CTAs used to be loose `cta_live`
        siblings floating under their cards, which is why Classic and Premier
        never lined up."""
        from app.services.section_schema import validate_sections
        doc, _ = validate_sections(_built(monkeypatch, 'home'), is_admin=True)
        for section in doc['sections']:
            kinds = {b.get('kind') for b in section['blocks']
                     if b['type'] == 'cta_live'}
            assert not (kinds & {'division_classic', 'division_premier'}), \
                'a division CTA is still a loose block rather than card-owned'
        cards = [b for b in _all_blocks(doc)
                 if b['type'] == 'card' and b.get('cta_kind')]
        assert len(cards) == 2
        assert all(c.get('prominence') == 'lead' for c in cards)

    def test_photography_ships_untreated(self, monkeypatch):
        """Photography is full-colour, everywhere, by default.

        A duotone house style was tried and reverted: on the live page the one
        untreated photo was visibly better than the treated ones either side of
        it. The treatment stays available per block for a deliberate one-off,
        but nothing the builders emit may opt into it — a page of duotoned
        photos reads as a broken colour profile, not as an identity.
        """
        from app.services.section_schema import validate_sections
        for slug in self.SLUGS:
            doc, _ = validate_sections(_built(monkeypatch, slug), is_admin=True)
            treated = [b for b in _all_blocks(doc)
                       if b.get('treatment') == 'duotone']
            treated += [s for s in doc['sections']
                        if s['settings'].get('treatment') == 'duotone']
            assert not treated, f'{slug} ships {len(treated)} duotoned images'

    def test_content_sections_do_not_indent(self, monkeypatch):
        """Every section type must share one left edge.

        `section_content` used to centre a narrower container (`mx-auto
        max-w-5xl`), which put a left-aligned content section's text ~130px
        further right than every hero, columns and band section on the same
        page. Three different left edges within two screens is what reads as
        "not aligned" even when nothing is technically broken. The measure is an
        inner wrapper now; the outer container is max-w-7xl everywhere.
        """
        import re
        src = open('app/templates/public/sections/macros.html', encoding='utf-8').read()
        body = src.split('{% macro section_content')[1].split('{% endmacro %}')[0]
        outer = re.search(r'<div class="mx-auto ([a-z0-9-]+) px-4', body)
        assert outer and outer.group(1) == 'max-w-7xl', \
            f'section_content outer container is {outer and outer.group(1)!r}, not max-w-7xl'

    def test_rebuildable_slugs_all_have_builders(self):
        from app.services.section_converter import REBUILDABLE_SLUGS
        # build_doc_for_page dispatches on slug; anything without an arm falls
        # through to build_richtext_doc, which would silently flatten a
        # designed page into a prose page.
        import inspect
        from app.services import section_converter as sc
        src = inspect.getsource(sc.build_doc_for_page)
        for slug in REBUILDABLE_SLUGS:
            assert f"slug == '{slug}'" in src or slug in ('about',), slug


class TestGuideReaderChrome:
    """The guide's contents rail and the imported-bullet repair.

    Both of these fix defects that shipped for as long as the page existed, so
    the assertions are about the DEFECT, not about the implementation — they
    stay meaningful if the rail is rebuilt some other way.
    """

    def test_guide_bullets_become_real_lists(self):
        """The Google Doc import turned every bullet into a literal ' * '.

        32 paragraphs across 9 chapters, and ZERO <ul> in the whole document,
        so the site's longest page rendered its equipment list, its Discord
        instructions and its rules as unbroken prose with asterisks in it.
        """
        import re
        from app.services.section_converter import _load_guide_chapters
        chapters = _load_guide_chapters()
        assert chapters, 'guide seed did not load'
        html = ''.join(c.get('html', '') for c in chapters)
        assert html.count('<ul>') >= 20, f'only {html.count("<ul>")} lists — bullets not repaired'
        leftover = [m.group(1)[:60]
                    for m in re.finditer(r'<p>(.*?)</p>', html, re.S)
                    if m.group(1).count(' * ') >= 2 or m.group(1).strip().startswith('* ')]
        assert not leftover, f'{len(leftover)} asterisk paragraphs survived: {leftover[:2]}'

    def test_bulletise_leaves_ordinary_prose_alone(self):
        """A single asterisk in running copy is not a list."""
        from app.services.section_converter import _bulletise
        prose = '<p>Shots are worth 1 point * see the rules.</p>'
        assert _bulletise(prose) == prose
        # ...and a one-item "list" loses its marker rather than becoming a <ul>.
        one = _bulletise('<p>* Fun Week is the second-to-last week.</p>')
        assert '<ul>' not in one and one.startswith('<p>Fun Week')

    def test_guide_outline_skips_the_closing_cta(self):
        """Every h2 gets a generated id, the closing band's included.

        Without the brand-ground filter, "Now go play." lands in the contents
        rail as a chapter that is not a chapter.
        """
        from app.public_site import _guide_outline
        html = (
            '<section class="pt-14"><h2 id="chapter-one">Chapter One</h2></section>'
            '<section class="pt-14"><h2 id="chapter-two">Chapter Two</h2></section>'
            '<section class="bg-ecs-pitch pt-20"><h2 id="now-go-play">Now go play.</h2></section>'
        )
        ids = [c['id'] for c in _guide_outline(html)]
        assert ids == ['chapter-one', 'chapter-two'], ids

    def test_guide_contents_card_is_gated_server_side(self):
        """`hide_at` must survive the schema's allowlist rebuild.

        _validate_block/_section_settings rebuild every section from an
        allowlist, so an unregistered key is silently dropped — the exact
        failure mode that ate `slot` and `prominence` in an earlier pass. If
        this regresses, the card and the rail both render at xl and the page
        ships its contents twice.
        """
        from app.services.section_converter import build_guide_doc
        from app.services.section_schema import validate_sections
        doc, _ = validate_sections(build_guide_doc(), is_admin=True)
        gated = [s for s in doc['sections'] if s['settings'].get('hide_at') == 'xl']
        assert len(gated) == 1, f'{len(gated)} sections gated at xl, expected exactly 1'
        assert 'What' in gated[0]['blocks'][0].get('html', '')

    def test_guide_toc_card_carries_no_nav_wrapper(self):
        """The richtext sanitizer strips <nav>.

        The card used to be wrapped in <nav aria-label="Guide contents"> and
        the JS hid it by that exact selector — which therefore matched nothing,
        so the guide shipped two contents lists for as long as both existed.
        """
        from app.services.section_converter import build_guide_doc
        html = ''.join(b.get('html', '') for s in build_guide_doc()['sections']
                       for b in s['blocks'])
        assert '<nav' not in html

    def test_guide_chrome_is_not_built_in_js(self):
        """The toolbar shell is server-rendered.

        It used to be created in JS and main.prepend()ed, which pushed the whole
        document down by its own 48px after first paint — a guaranteed layout
        shift on every load of the longest page on the site.
        """
        js = open('app/static/js/public-guide.js', encoding='utf-8').read()
        # The CALL, not the substring — the comment above the replacement names
        # the old code on purpose, and a bare `main.prepend` match would fail on
        # its own explanation.
        assert 'main.prepend(bar)' not in js
        assert "querySelector('[data-guide-bar]')" in js
        tpl = open('app/templates/public/_guide_chrome.html', encoding='utf-8').read()
        assert 'data-guide-bar' in tpl and 'data-guide-rail' in tpl


class TestShellChrome:
    """Two site-wide defects that rendered on every public page for months.

    Both were invisible to review because the symptom looked like a
    configuration choice rather than a bug.
    """

    def test_theme_css_survives_autoescaping(self):
        """`<style>{{ appearance.theme_css }}</style>` must not be escaped.

        Jinja autoescapes, the font stacks contain single quotes, and `<style>`
        is a RAW TEXT element — the CSS parser never decodes HTML entities. So
        an escaped block set --font-heading to a garbage token stream, which is
        worse than leaving it unset: `var(--font-heading, fallback)` does not
        fall back for a property that IS set, so `font-family` was invalid at
        computed-value time and the entire public site rendered in the browser's
        default serif. The colour triplets have no quotes, so the palette kept
        working and hid it.
        """
        from markupsafe import Markup, escape
        from app.services.public_theme import css_var_block, theme_vars
        block = css_var_block(theme_vars()['css'])
        assert isinstance(block, Markup), 'css_var_block must return Markup'
        assert "'Big Shoulders Display'" in block
        assert "'Big Shoulders Display'" in str(escape(block)), \
            'theme_css does not survive autoescaping — fonts will break site-wide'
        assert '&#39;' not in str(escape(block))

    def test_theme_css_cannot_escape_the_style_element(self):
        from app.services.public_theme import css_var_block
        out = css_var_block({'--x': '</style><script>alert(1)</script>',
                             '--y': 'red', '--z': 'a{}b'})
        assert '<' not in out and '>' not in out
        assert '{ --y: red; }' in out and '--z' not in out

    def test_no_display_utility_fights_a_shared_constant(self):
        """`hidden lg:inline-flex` + a constant carrying `inline-flex` loses.

        Both are display utilities with equal specificity, so the built
        stylesheet's source order decides — and Tailwind emits `.inline-flex`
        after `.hidden`. Log in, Portal and the CTA pill were therefore visible
        at 320px, eating ~174px of a 288px bar. Use `max-lg:hidden`, which lives
        in a media block that comes later.
        """
        import re
        src = open('app/templates/public/base_public.html', encoding='utf-8').read()
        offenders = re.findall(r'class="hidden (?:sm|md|lg|xl):(?:inline-)?flex ', src)
        assert not offenders, f'{len(offenders)} element(s) pair `hidden` with a ' \
                              f'same-specificity display utility; use max-*:hidden'

    def test_type_cascade_names_the_current_display_face(self):
        """A font fallback chain is dead code that renders.

        It named Bricolage for months after that font was deleted, so every
        utility page (its context processor never sets --font-heading) set its
        headings in Inter, silently.
        """
        from app.services.public_theme import FONT_PAIRS, DEFAULT_FONT_PAIR
        head = FONT_PAIRS[DEFAULT_FONT_PAIR]['heading']
        face = head.split(',')[0].strip().strip("'")
        casc = open('app/templates/public/_type_cascade.html', encoding='utf-8').read()
        assert face in casc, f'type cascade does not name {face!r}'
        assert 'Bricolage' not in casc

    def test_nav_carries_no_duplicate_season_chip(self):
        """The hero already renders the season + registration state."""
        src = open('app/templates/public/base_public.html', encoding='utf-8').read()
        nav = src.split('{# =================== NAV')[1].split('</header>')[0]
        assert 'font-mono' not in nav, 'nav re-grew a season chip; the hero owns that fact'
