# tests/test_ph_posts.py

"""
Locks PSB-12's Posts half: NewsPost tags alongside category, and the public
tag filter that makes them clickable.

Task 2 covers the admin write path — ``_normalize_tags`` (dedup, truncation,
empty-input handling) and the admin Posts list/edit round trip. Task 3
covers the public read path — exact/case-insensitive/boundary-anchored
matching on ``GET /preview/news?tag=...``, wildcard escaping, the render
cache bypass, pagination, and draft-post invisibility.

Reuses the ``gadmin``/``gadmin_client`` fixture pattern established by
tests/test_ph_pages_list.py and tests/test_ph_page_settings.py. Per the
plan's own warning: ``client``, ``gadmin_client`` and ``site_editor_client``
all wrap the SAME underlying Flask test client, so each test below uses
exactly one client fixture — anonymous-vs-admin control cases are split
into separate tests rather than sharing a test body.
"""

from datetime import datetime, timedelta

import pytest

from app.admin_panel.routes.public_site import _normalize_tags
from app.models import NewsPost, MediaAsset


# --------------------------------------------------------------------------- #
# Fixtures
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


def _make_post(db, slug, **kwargs):
    defaults = dict(title=f'Post {slug}', status='draft')
    defaults.update(kwargs)
    p = NewsPost(slug=slug, **defaults)
    db.session.add(p)
    db.session.commit()
    return p


# --------------------------------------------------------------------------- #
# Task 2: _normalize_tags (pure helper) + admin round trip
# --------------------------------------------------------------------------- #

class TestNormalizeTags:
    def test_strips_dedupes_case_insensitively_and_rejoins(self):
        result = _normalize_tags(' Recap , playoffs,  Recap ,sounders ')
        # First spelling of a case-insensitive duplicate wins; each entry
        # stripped; rejoined with ', '.
        assert result == 'Recap, playoffs, sounders'

    def test_drops_empty_entries(self):
        result = _normalize_tags('recap,, ,  ,playoffs')
        assert result == 'recap, playoffs'

    def test_empty_field_stores_none(self):
        assert _normalize_tags('') is None
        assert _normalize_tags(None) is None
        assert _normalize_tags('   ') is None
        assert _normalize_tags(' , , ') is None

    def test_overlong_string_is_truncated_at_an_entry_boundary(self):
        # Build entries that comfortably overflow the 255-char column when
        # joined, and confirm the result is composed of WHOLE entries only
        # (no entry appears partially — every kept entry is byte-identical
        # to one of the inputs).
        entries = [f'tag-{i:03d}-{"x" * 20}' for i in range(20)]
        raw = ','.join(entries)
        result = _normalize_tags(raw)
        assert result is not None
        assert len(result) <= 255
        for kept in result.split(', '):
            assert kept in entries
        # It must have actually dropped something (the point of the test).
        assert len(result.split(', ')) < len(entries)

    def test_per_entry_length_is_capped(self):
        long_entry = 'y' * 500
        result = _normalize_tags(long_entry)
        assert result is not None
        assert len(result) < 500


class TestAdminPostsTagsRoundTrip:
    def test_save_round_trips_tags_through_the_edit_form(self, app, db, gadmin_client):
        r = gadmin_client.post('/admin-panel/public-site/news/save', data={
            'csrf_token': 'x', 'title': 'Tagged post',
            'tags': 'recap, playoffs',
        }, follow_redirects=False)
        assert r.status_code in (302, 303)
        post = db.session.query(NewsPost).filter_by(title='Tagged post').first()
        assert post is not None
        assert post.tags == 'recap, playoffs'

        # Edit form shows the current tags, pre-filled.
        edit = gadmin_client.get(f'/admin-panel/public-site/news/{post.id}/edit')
        assert b'name="tags"' in edit.data
        assert b'recap, playoffs' in edit.data

    def test_save_with_no_tag_change_leaves_tags_identical(self, app, db, gadmin_client):
        post = _make_post(db, 'unchanged-tags-post', tags='recap, playoffs')
        gadmin_client.post('/admin-panel/public-site/news/save', data={
            'csrf_token': 'x', 'id': post.id, 'title': post.title,
            'tags': 'recap, playoffs',
        }, follow_redirects=False)
        db.session.refresh(post)
        assert post.tags == 'recap, playoffs'

    def test_empty_tags_field_stores_null_not_empty_string(self, app, db, gadmin_client):
        post = _make_post(db, 'clearing-tags-post', tags='recap')
        gadmin_client.post('/admin-panel/public-site/news/save', data={
            'csrf_token': 'x', 'id': post.id, 'title': post.title,
            'tags': '',
        }, follow_redirects=False)
        db.session.refresh(post)
        assert post.tags is None

    def test_admin_posts_list_renders_tags_column_with_dash_fallback(self, app, db, gadmin_client):
        _make_post(db, 'list-tagged', title='List Tagged', tags='recap, playoffs')
        # The untagged row is given a category and relies on created_at for
        # its Date cell (never blank) — isolating the em-dash to the Tags
        # cell specifically, rather than one that could equally be coming
        # from Category or Date if a naive substring check were used.
        _make_post(db, 'list-untagged', title='List Untagged', category='General')
        r = gadmin_client.get('/admin-panel/public-site/news')
        assert r.status_code == 200
        body = r.data.decode()
        assert 'Tags' in body
        assert 'recap, playoffs' in body
        assert 'General' in body

        # Extract the untagged row specifically and assert its Tags cell (the
        # 2nd hidden-xl <td>, after Category) is the dash — a body-wide '—'
        # check would also pass if the dash came from an unrelated cell.
        row_start = body.find('List Untagged')
        assert row_start != -1
        tr_start = body.rfind('<tr', 0, row_start)
        tr_end = body.find('</tr>', row_start)
        row_html = body[tr_start:tr_end]
        import re as _re
        cells = _re.findall(r'<td[^>]*>(.*?)</td>', row_html, _re.S)
        # cells order: Title, Status, Category, Tags, Date, Actions
        assert len(cells) >= 4
        assert 'General' in cells[2]
        assert cells[3].strip() == '—'

    def test_metacharacter_bearing_tag_is_stored_as_typed_and_rendered_escaped(self, app, db, gadmin_client):
        raw_tag = '<script>alert(1)</script>'
        gadmin_client.post('/admin-panel/public-site/news/save', data={
            'csrf_token': 'x', 'title': 'XSS tag test',
            'tags': raw_tag,
        }, follow_redirects=False)
        post = db.session.query(NewsPost).filter_by(title='XSS tag test').first()
        # Stored exactly as typed — tags are plain text, never HTML-sanitized.
        assert post.tags == raw_tag

        listing = gadmin_client.get('/admin-panel/public-site/news')
        assert b'<script>alert(1)</script>' not in listing.data
        assert b'&lt;script&gt;' in listing.data

        edit = gadmin_client.get(f'/admin-panel/public-site/news/{post.id}/edit')
        assert b'<script>alert(1)</script>' not in edit.data
        assert b'&lt;script&gt;' in edit.data


class TestMediaAltTextRoundTrip:
    """The server-side contract the shared picker's alt-text save depends
    on: POST alt_text to the existing per-asset save endpoint, then GET the
    SAME list endpoint the picker reads assets from on every open, and prove
    the saved alt text actually comes back — not just that the POST was
    accepted. This is what makes 'the picker lets you set alt text' true
    rather than merely attempted; a picker that posts the value but never
    sees it again on the next open would silently defeat PSB-10's
    accessibility point."""

    def test_alt_text_saved_via_the_save_endpoint_reappears_in_the_list_endpoint(self, app, db, gadmin_client):
        asset = MediaAsset(filename='crest.jpg', url='/static/img/publeague/crest.jpg')
        db.session.add(asset)
        db.session.commit()

        # Before any save, the list endpoint (what the picker reads on open)
        # reports no alt text — the baseline the round trip is measured against.
        before = gadmin_client.get('/admin-panel/public-site/media/list')
        before_asset = next(a for a in before.get_json()['assets'] if a['id'] == asset.id)
        assert before_asset['alt'] == ''

        save_resp = gadmin_client.post(f'/admin-panel/public-site/media/{asset.id}/save', data={
            'csrf_token': 'x', 'alt_text': 'Sounders crest on a green field',
        }, follow_redirects=False)
        assert save_resp.status_code in (302, 303)

        # The save route writes through g.db_session (a separate session
        # object from this test's own db.session, per this codebase's
        # request-session pattern). In a real browser, the picker's next
        # open is a genuinely separate HTTP request with a freshly-scoped
        # db.session and therefore an empty identity map, so it always sees
        # the committed row. Here, this test's db.session is reused across
        # both calls within one Python test function, so its identity map
        # still holds the pre-save MediaAsset instance unless expired —
        # expire_all() reproduces the "fresh request" read this test is
        # actually trying to prove.
        db.session.expire_all()

        after = gadmin_client.get('/admin-panel/public-site/media/list')
        after_asset = next(a for a in after.get_json()['assets'] if a['id'] == asset.id)
        assert after_asset['alt'] == 'Sounders crest on a green field'

        # And it survives an application-level reload of the row, not just
        # the endpoint's cached response.
        db.session.expire(asset)
        reloaded = db.session.query(MediaAsset).get(asset.id)
        assert reloaded.alt_text == 'Sounders crest on a green field'

    def test_alt_text_save_requires_auth(self, client, db):
        asset = MediaAsset(filename='crest2.jpg', url='/static/img/publeague/crest2.jpg')
        db.session.add(asset)
        db.session.commit()
        r = client.post(f'/admin-panel/public-site/media/{asset.id}/save', data={
            'csrf_token': 'x', 'alt_text': 'should not be saved',
        }, follow_redirects=False)
        assert r.status_code in (302, 401, 403)
        db.session.refresh(asset)
        assert asset.alt_text is None


# --------------------------------------------------------------------------- #
# Task 3: public tag filter
# --------------------------------------------------------------------------- #

@pytest.fixture
def tagged_posts(db):
    """Three published posts (a short-tag one, a longer-tag-starting-with-
    the-same-word one, and an untagged one) plus a draft carrying the same
    tag as the short one — so the boundary-exactness and draft-invisibility
    cases are meaningful rather than trivially true."""
    now = datetime.utcnow()
    short = NewsPost(slug='tag-short-post', title='Short Tag Post',
                      status='published', published_at=now - timedelta(days=1),
                      tags='foot, Recap')
    long_ = NewsPost(slug='tag-long-post', title='Long Tag Post',
                      status='published', published_at=now - timedelta(days=2),
                      tags='football')
    untagged = NewsPost(slug='tag-untagged-post', title='Untagged Post',
                         status='published', published_at=now - timedelta(days=3))
    draft_same_tag = NewsPost(slug='tag-draft-post', title='Draft Tag Post',
                               status='draft', published_at=None, tags='foot')
    db.session.add_all([short, long_, untagged, draft_same_tag])
    db.session.commit()
    return {'short': short, 'long': long_, 'untagged': untagged, 'draft': draft_same_tag}


class TestPublicTagFilter:
    def test_short_tag_query_does_not_match_a_longer_tag(self, client, tagged_posts):
        r = client.get('/preview/news?tag=foot')
        assert r.status_code == 200
        body = r.data.decode()
        assert 'Short Tag Post' in body
        assert 'Long Tag Post' not in body

    def test_case_insensitive_match(self, client, tagged_posts):
        r = client.get('/preview/news?tag=recap')
        assert r.status_code == 200
        body = r.data.decode()
        assert 'Short Tag Post' in body
        # A no-op filter (or a case-SENSITIVE one that silently matched
        # everything) would also let "Short Tag Post" through — assert the
        # untagged post is excluded too, so this only passes if filtering is
        # both active AND case-insensitive.
        assert 'Untagged Post' not in body

    def test_wildcard_characters_in_the_query_match_literally(self, client, tagged_posts):
        # '%' and '_' are SQL LIKE wildcards; unescaped, '%' would match
        # every post's tags and '_' would match any single character.
        r = client.get('/preview/news?tag=%25')
        assert r.status_code == 200
        assert 'Short Tag Post' not in r.data.decode()
        assert 'Long Tag Post' not in r.data.decode()

        r2 = client.get('/preview/news?tag=fo_t')  # would match "foot" if unescaped
        assert r2.status_code == 200
        assert 'Short Tag Post' not in r2.data.decode()

    def test_draft_posts_tag_never_reaches_an_anonymous_visitor(self, client, tagged_posts):
        r = client.get('/preview/news?tag=foot')
        assert b'Draft Tag Post' not in r.data

    def test_tag_filtered_page_bypasses_the_public_render_cache(self, client, tagged_posts):
        import app.public_site as public_site_module
        captured = []
        orig = public_site_module._dynamic_page_cache

        def spy(cache_slug, key_suffix, render_fn):
            captured.append(key_suffix)
            return render_fn()

        public_site_module._dynamic_page_cache = spy
        try:
            client.get('/preview/news')
            client.get('/preview/news?tag=foot')
        finally:
            public_site_module._dynamic_page_cache = orig

        assert captured[0] is not None    # untagged: cacheable key suffix
        assert captured[1] is None        # tagged: forced live/uncached

    def test_pagination_preserves_the_active_tag(self, client, db):
        now = datetime.utcnow()
        for i in range(14):
            db.session.add(NewsPost(
                slug=f'pg-tag-post-{i}', title=f'Paged Tag Post {i}',
                status='published', published_at=now - timedelta(days=i),
                tags='paginated'))
        db.session.commit()
        r = client.get('/preview/news?tag=paginated')
        assert r.status_code == 200
        body = r.data.decode()
        # Every post here is ALSO tagged "paginated", so its own per-card tag
        # chip link ALSO contains "tag=paginated" — a body-wide substring
        # check would pass even if the pagination nav itself dropped the
        # filter. Isolate the assertion to the <nav aria-label="News pages">
        # block, which sits after the card grid and contains none of the
        # per-card chip links.
        nav_start = body.find('aria-label="News pages"')
        assert nav_start != -1, 'expected a pagination nav for 14 posts at 12/page'
        nav_html = body[nav_start:]
        assert 'tag=paginated' in nav_html

    def test_tags_render_as_links_on_list_and_detail(self, client, tagged_posts):
        listing = client.get('/preview/news')
        assert 'href="/preview/news?tag=foot"' in listing.data.decode()

        detail = client.get(f'/preview/news/{tagged_posts["short"].slug}')
        assert detail.status_code == 200
        detail_body = detail.data.decode()
        assert 'href="/preview/news?tag=foot"' in detail_body
        assert 'href="/preview/news?tag=Recap"' in detail_body

    def test_page_title_names_the_active_tag(self, client, tagged_posts):
        r = client.get('/preview/news?tag=foot')
        body = r.data.decode()
        # "#foot" also appears as chip TEXT on any matching post's card
        # regardless of whether the SEO title logic runs — isolate the
        # assertion to the <title> element specifically.
        title_start = body.find('<title>')
        title_end = body.find('</title>', title_start)
        assert title_start != -1 and title_end != -1
        title_text = body[title_start:title_end]
        assert '#foot' in title_text
