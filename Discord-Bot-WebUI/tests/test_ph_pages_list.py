"""Locks the Pages screen's WordPress-style list tooling (PSB-12, criterion 5):
two-step publish (never a one-click action), bulk publish/unpublish/trash on
several pages at once, and an in-table Quick Edit for title/permalink/status.

Specifically locks:

  1. Publish must never be a one-click action — the per-row Publish/Unpublish
     form and the bulk `publish` verb both require a deliberate confirm/step.
  2. The bulk endpoint re-derives every target from the database per id — a
     client-supplied id list (missing / trashed / non-integer rows) is never
     trusted as a set of pre-authorized rows.
  3. Both the bulk endpoint and Quick Edit delegate every metadata write to
     apply_page_settings (plan 03-01) — never re-implementing the empty-page
     refusal, the slug-history insert, or the draft->published section copy.
  4. A partial payload (bulk sends only `status`; Quick Edit sends only
     title/slug/status) never wipes excerpt/featured image/SEO.
  5. The Pages list's bulk action name and checkbox class are Pages-specific
     — the generic `bulk-action` name is already registered globally by
     handlers/user-management-comprehensive.js on every admin page, and
     reusing it would make Pages bulk actions silently do nothing.
"""
import pytest

from app.models import SitePage, SitePageSlugHistory
from app.models.public_site import slugify
from app.admin_panel.routes.public_site import _RESERVED_SLUGS, _BLOCK_SLUGS


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
    u = db.session.query(User).filter_by(username='pl-siteeditor').first()
    if not u:
        u = User(username='pl-siteeditor', email='pl-se@example.com',
                 is_approved=True, approval_status='approved')
        u.set_password('x')
        u.roles.append(role)
        db.session.add(u)
        db.session.flush()
    with client.session_transaction() as sess:
        sess['_user_id'] = u.id
        sess['_fresh'] = True
    return client


_DOC = {'v': 1, 'sections': [
    {'id': 's1', 'type': 'content', 'theme': 'inherit', 'settings': {},
     'blocks': [{'id': 'b1', 'type': 'heading', 'level': 2, 'html': 'Hi there'}]}]}


def _make_page(db, slug, **kwargs):
    defaults = dict(title='Pages List Test', status='draft', sections_draft=_DOC)
    defaults.update(kwargs)
    p = SitePage(slug=slug, **defaults)
    db.session.add(p)
    db.session.commit()
    return p


def _table_region(html):
    """Scope an assertion to the <table>...</table> region so a match
    elsewhere in the admin shell chrome can't pass by accident."""
    return html.split('<table', 1)[1].split('</table>', 1)[0]


# --------------------------------------------------------------------------- #
# Task 1: the tracer slice -- ticking two pages and bulk-publishing them
# --------------------------------------------------------------------------- #

class TestBulkPublish:
    def test_bulk_publish_publishes_selected_pages(self, app, db, gadmin_client):
        p1 = _make_page(db, 'bulk-pub-1')
        p2 = _make_page(db, 'bulk-pub-2')
        r = gadmin_client.post('/admin-panel/public-site/pages/bulk',
                               json={'action': 'publish', 'page_ids': [p1.id, p2.id]})
        assert r.status_code == 200, r.get_data(as_text=True)
        data = r.get_json()
        assert data['success'] is True
        assert data['updated'] == 2
        assert data['skipped'] == []
        db.session.expire_all()
        f1 = db.session.query(SitePage).get(p1.id)
        f2 = db.session.query(SitePage).get(p2.id)
        assert f1.status == 'published'
        assert f2.status == 'published'
        assert f1.sections_published == f1.sections_draft
        assert f2.sections_published == f2.sections_draft

    def test_bulk_publish_skips_empty_page_without_all_or_nothing(self, app, db, gadmin_client):
        p1 = _make_page(db, 'bulk-mixed-1')
        p2 = _make_page(db, 'bulk-mixed-2')
        empty = _make_page(db, 'bulk-mixed-empty', sections_draft=None)
        r = gadmin_client.post('/admin-panel/public-site/pages/bulk',
                               json={'action': 'publish',
                                     'page_ids': [p1.id, p2.id, empty.id]})
        assert r.status_code == 200, r.get_data(as_text=True)
        data = r.get_json()
        assert data['success'] is True
        assert data['updated'] == 2
        assert empty.id in data['skipped']
        db.session.expire_all()
        fe = db.session.query(SitePage).get(empty.id)
        f1 = db.session.query(SitePage).get(p1.id)
        f2 = db.session.query(SitePage).get(p2.id)
        assert fe.status != 'published'
        assert f1.status == 'published'
        assert f2.status == 'published'

    def test_bulk_publish_preserves_untouched_metadata(self, app, db, gadmin_client):
        p1 = _make_page(db, 'bulk-meta-1', title='Original Title',
                        excerpt='Original excerpt',
                        meta_description='Original meta description')
        p2 = _make_page(db, 'bulk-meta-2', title='Second Title',
                        excerpt='Second excerpt')
        r = gadmin_client.post('/admin-panel/public-site/pages/bulk',
                               json={'action': 'publish', 'page_ids': [p1.id, p2.id]})
        assert r.status_code == 200, r.get_data(as_text=True)
        db.session.expire_all()
        f1 = db.session.query(SitePage).get(p1.id)
        f2 = db.session.query(SitePage).get(p2.id)
        assert f1.title == 'Original Title'
        assert f1.excerpt == 'Original excerpt'
        assert f1.meta_description == 'Original meta description'
        assert f2.title == 'Second Title'
        assert f2.excerpt == 'Second excerpt'

    def test_bulk_action_requires_auth(self, app, db, client):
        # A bare, never-logged-in `client` — do NOT also request gadmin_client
        # or site_editor_client in this test, they mutate the SAME underlying
        # test client's session cookie (all three fixtures wrap one `client`).
        p = _make_page(db, 'bulk-auth')
        r = client.post('/admin-panel/public-site/pages/bulk',
                        json={'action': 'publish', 'page_ids': [p.id]})
        assert r.status_code != 200

    def test_bulk_action_allows_site_editor(self, app, db, site_editor_client):
        p2 = _make_page(db, 'bulk-auth-se')
        r2 = site_editor_client.post('/admin-panel/public-site/pages/bulk',
                                     json={'action': 'publish', 'page_ids': [p2.id]})
        assert r2.status_code == 200, r2.get_data(as_text=True)
        assert r2.get_json()['success'] is True

    def test_bulk_id_list_is_never_trusted(self, app, db, gadmin_client):
        trashed = _make_page(db, 'bulk-trashed', status='published',
                             sections_published=_DOC)
        trashed.deleted_at = __import__('datetime').datetime.utcnow()
        db.session.commit()
        r = gadmin_client.post('/admin-panel/public-site/pages/bulk',
                               json={'action': 'trash',
                                     'page_ids': [999999, trashed.id, 'not-an-int']})
        assert r.status_code == 200, r.get_data(as_text=True)
        data = r.get_json()
        assert data['success'] is True
        assert data['updated'] == 0
        assert 999999 in data['skipped']
        assert trashed.id in data['skipped']
        assert 'not-an-int' in data['skipped']

    def test_pages_list_renders_bulk_markup_with_pages_specific_action(self, app, db, gadmin_client):
        _make_page(db, 'bulk-markup-1')
        r = gadmin_client.get('/admin-panel/public-site/pages')
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        table = _table_region(html)
        assert 'id="pagesSelectAll"' in table
        assert 'pages-row-checkbox' in table
        assert 'data-action="pages-bulk-action"' in html
        # Generic name owned globally by user-management-comprehensive.js must
        # never appear — reusing it would silently no-op on this screen.
        assert 'data-action="bulk-action"' not in html


# --------------------------------------------------------------------------- #
# Task 2: Quick Edit a row in place
# --------------------------------------------------------------------------- #

class TestQuickEdit:
    def test_quick_edit_row_renders_prefilled_and_hidden(self, app, db, gadmin_client):
        p = _make_page(db, 'qe-render', title='Quick Edit Me')
        r = gadmin_client.get('/admin-panel/public-site/pages')
        html = r.get_data(as_text=True)
        table = _table_region(html)
        assert f'id="pages-qe-row-{p.id}"' in table
        assert 'hidden' in table.split(f'id="pages-qe-row-{p.id}"')[1].split('>', 1)[0]
        assert f'value="Quick Edit Me"' in table
        assert f'value="qe-render"' in table
        assert f'data-action="pages-quick-edit-open" data-page-id="{p.id}"' in table

    def test_quick_edit_updates_only_title_slug_status(self, app, db, gadmin_client):
        p = _make_page(db, 'qe-update', title='Before')
        r = gadmin_client.post(f'/admin-panel/public-site/pages/{p.id}/quick-edit',
                               json={'title': 'After', 'slug': 'qe-update-renamed',
                                     'status': 'published'})
        assert r.status_code == 200, r.get_data(as_text=True)
        data = r.get_json()
        assert data['success'] is True
        assert data['page']['title'] == 'After'
        assert data['page']['slug'] == 'qe-update-renamed'
        assert data['page']['status'] == 'published'
        db.session.expire_all()
        fresh = db.session.query(SitePage).get(p.id)
        assert fresh.title == 'After'
        assert fresh.slug == 'qe-update-renamed'
        assert fresh.status == 'published'

    def test_quick_edit_preserves_excerpt_image_and_seo(self, app, db, gadmin_client):
        p = _make_page(db, 'qe-preserve', excerpt='Keep me',
                       featured_image_url='/static/img/keep.jpg',
                       meta_description='Keep this too')
        r = gadmin_client.post(f'/admin-panel/public-site/pages/{p.id}/quick-edit',
                               json={'title': 'New Title'})
        assert r.status_code == 200, r.get_data(as_text=True)
        db.session.expire_all()
        fresh = db.session.query(SitePage).get(p.id)
        assert fresh.title == 'New Title'
        assert fresh.excerpt == 'Keep me'
        assert fresh.featured_image_url == '/static/img/keep.jpg'
        assert fresh.meta_description == 'Keep this too'

    def test_quick_edit_echoes_the_slug_the_server_settled_on(self, app, db, gadmin_client):
        _make_page(db, 'qe-taken')
        p = _make_page(db, 'qe-uniquing-source')
        r = gadmin_client.post(f'/admin-panel/public-site/pages/{p.id}/quick-edit',
                               json={'slug': 'qe-taken'})
        assert r.status_code == 200, r.get_data(as_text=True)
        data = r.get_json()
        assert data['page']['slug'] != 'qe-taken'
        assert data['page']['slug'].startswith('qe-taken')
        db.session.expire_all()
        fresh = db.session.query(SitePage).get(p.id)
        assert fresh.slug == data['page']['slug']

    def test_quick_edit_reserved_slug_refused_server_side(self, app, db, gadmin_client):
        p = _make_page(db, 'about', status='published', sections_published=_DOC)
        r = gadmin_client.post(f'/admin-panel/public-site/pages/{p.id}/quick-edit',
                               json={'slug': 'renamed-about'})
        assert r.status_code == 200, r.get_data(as_text=True)
        data = r.get_json()
        assert data['page']['slug'] == 'about'
        db.session.expire_all()
        fresh = db.session.query(SitePage).get(p.id)
        assert fresh.slug == 'about'

    def test_quick_edit_rename_records_slug_history(self, app, db, gadmin_client):
        p = _make_page(db, 'qe-history-old')
        r = gadmin_client.post(f'/admin-panel/public-site/pages/{p.id}/quick-edit',
                               json={'slug': 'qe-history-new'})
        assert r.status_code == 200, r.get_data(as_text=True)
        hist = (db.session.query(SitePageSlugHistory)
                .filter_by(old_slug='qe-history-old').first())
        assert hist is not None
        assert hist.page_id == p.id

    def test_quick_edit_publish_refused_when_page_is_empty(self, app, db, gadmin_client):
        p = _make_page(db, 'qe-empty', sections_draft=None)
        r = gadmin_client.post(f'/admin-panel/public-site/pages/{p.id}/quick-edit',
                               json={'status': 'published'})
        assert r.status_code == 400, r.get_data(as_text=True)
        data = r.get_json()
        assert data['success'] is False
        assert data['error'] == 'empty_page'
        db.session.expire_all()
        fresh = db.session.query(SitePage).get(p.id)
        assert fresh.status != 'published'

    def test_quick_edit_requires_auth(self, app, db, client):
        p = _make_page(db, 'qe-auth')
        r = client.post(f'/admin-panel/public-site/pages/{p.id}/quick-edit',
                        json={'title': 'nope'})
        assert r.status_code != 200


# --------------------------------------------------------------------------- #
# Task 3: publishing is deliberate, and the gear points at the editor panel
# --------------------------------------------------------------------------- #

class TestDeliberatePublishAndGearLink:
    def test_publish_form_has_a_confirm(self, app, db, gadmin_client):
        _make_page(db, 'confirm-publish')
        r = gadmin_client.get('/admin-panel/public-site/pages')
        table = _table_region(r.get_data(as_text=True))
        # The publish form must carry the same onsubmit-confirm shape as Trash.
        assert 'public_site_page_publish' not in table or 'onsubmit="return confirm(' in table
        # Directly assert a confirm exists tied to the publish action.
        assert table.count('onsubmit="return confirm(') >= 2

    def test_trash_form_still_has_a_confirm(self, app, db, gadmin_client):
        _make_page(db, 'confirm-trash')
        r = gadmin_client.get('/admin-panel/public-site/pages')
        table = _table_region(r.get_data(as_text=True))
        assert "onsubmit=\"return confirm('Move this page to Trash?');\"" in table

    def test_gear_link_points_at_editor_not_retired_settings_route(self, app, db, gadmin_client):
        p = _make_page(db, 'gear-link-check')
        r = gadmin_client.get('/admin-panel/public-site/pages')
        table = _table_region(r.get_data(as_text=True))
        assert f'/admin-panel/site-editor/{p.id}?panel=page' in table
        assert 'pages/' + str(p.id) + '/edit' not in table

# --------------------------------------------------------------------------- #
# CR-01 regression: home-page content BLOCKS are not reachable by id
#
# The Pages list, its counts and the Trash view all filter
# ~SitePage.slug.in_(_BLOCK_SLUGS), so block rows (home_hero, home_intro, ...)
# are deliberately invisible as "pages". Both the bulk endpoint and Quick Edit
# take a CLIENT-SUPPLIED id, so the exclusion has to be enforced server-side —
# the UI simply not drawing a checkbox is not a control. A block trashed here
# would disappear from the home page with NO admin recovery path, because Trash
# cannot list it either.
#
# One client fixture per test: client / gadmin_client / site_editor_client all
# wrap the SAME underlying test client, so mixing two in one body shares a
# session cookie and an auth assertion can pass for the wrong reason.
# --------------------------------------------------------------------------- #

class TestBlockSlugsNotReachableById:
    def _make_block(self, db):
        from app.admin_panel.routes.public_site import _BLOCK_SLUGS
        slug = _BLOCK_SLUGS[0]
        blk = db.session.query(SitePage).filter_by(slug=slug).first()
        if not blk:
            blk = SitePage(slug=slug, title='Home hero', status='published')
            db.session.add(blk)
        # COMMIT, not flush: the quick-edit route aborts 404 inside
        # @transactional, which rolls the session back — a merely-flushed
        # fixture row would vanish and the read-back would be None.
        db.session.commit()
        return blk

    def test_bulk_trash_cannot_trash_a_block_slug(self, app, db, gadmin_client):
        blk = self._make_block(db)
        blk_id = blk.id
        r = gadmin_client.post('/admin-panel/public-site/pages/bulk',
                               json={'action': 'trash', 'page_ids': [blk_id]})
        assert r.status_code == 200, r.get_data(as_text=True)
        data = r.get_json()
        assert data['updated'] == 0, 'a block slug must never be counted as updated'
        assert blk_id in data['skipped']
        db.session.expire_all()
        still = db.session.query(SitePage).get(blk_id)
        assert still.deleted_at is None, 'home content block was trashed with no recovery path'

    def test_bulk_publish_cannot_touch_a_block_slug(self, app, db, gadmin_client):
        blk = self._make_block(db)
        blk.status = 'draft'
        db.session.commit()
        blk_id = blk.id
        r = gadmin_client.post('/admin-panel/public-site/pages/bulk',
                               json={'action': 'publish', 'page_ids': [blk_id]})
        assert r.status_code == 200, r.get_data(as_text=True)
        assert r.get_json()['updated'] == 0
        db.session.expire_all()
        assert db.session.query(SitePage).get(blk_id).status == 'draft'

    def test_bulk_mixed_still_processes_the_real_page(self, app, db, gadmin_client):
        """A block in the payload must not become an all-or-nothing failure."""
        blk = self._make_block(db)
        page = _make_page(db, 'cr01-mixed-real')
        r = gadmin_client.post('/admin-panel/public-site/pages/bulk',
                               json={'action': 'publish',
                                     'page_ids': [blk.id, page.id]})
        assert r.status_code == 200
        data = r.get_json()
        assert data['updated'] == 1
        assert blk.id in data['skipped']
        db.session.expire_all()
        assert db.session.query(SitePage).get(page.id).status == 'published'

    def test_quick_edit_cannot_rename_a_block_slug(self, app, db, gadmin_client):
        blk = self._make_block(db)
        blk_id, original = blk.id, blk.slug
        r = gadmin_client.post(f'/admin-panel/public-site/pages/{blk_id}/quick-edit',
                               json={'title': 'pwned', 'slug': 'pwned'})
        assert r.status_code == 404, r.get_data(as_text=True)
        db.session.expire_all()
        still = db.session.query(SitePage).get(blk_id)
        assert still.slug == original
        assert still.title != 'pwned'


# --------------------------------------------------------------------------- #
# Plan 04-04 / WR-02: ONE slug-lock rule, three consumers
#
# The rule deciding whether a page's permalink can be renamed existed in THREE
# places that disagreed:
#   - public_site.apply_page_settings' rename guard: exact membership only
#   - site_editor._slug_locked: membership OR a `home_*` prefix clause
#   - pages_list_flowbite.html: a hardcoded Jinja array PLUS the prefix clause
# The server's exact-membership rule is the one that could actually refuse a
# write, so the other two were reconciled toward it, not the other way round.
# --------------------------------------------------------------------------- #

def _ensure_page(db, slug, **kwargs):
    """_make_page, but tolerant of a slug the seed may already own.

    Several reserved slugs (about/guide/guests/home_*) can be created by the
    public-site seed, so a plain INSERT would blow up on the unique index for
    a reason that has nothing to do with the rule under test.
    """
    existing = db.session.query(SitePage).filter_by(slug=slug).first()
    if existing is not None:
        existing.deleted_at = None
        db.session.commit()
        return existing
    return _make_page(db, slug, **kwargs)


def _input_tag(html, element_id):
    """Return the single tag carrying `id="<element_id>"`.

    Scoped by element id on purpose: the Pages list renders one Quick Edit
    input per row, and a naive substring search over the whole table could
    read a neighbouring row's attributes and pass for the wrong reason.
    """
    needle = 'id="%s"' % element_id
    assert needle in html, f'no element with id {element_id!r} in the rendered page'
    start = html.rindex('<', 0, html.index(needle))
    return html[start:html.index('>', start) + 1]


def _has_disabled_attr(tag):
    """True when `tag` carries the BARE `disabled` attribute.

    A plain `'disabled' in tag` is wrong here and would pass for every row:
    the input's Tailwind classes include `disabled:opacity-60`, which contains
    the substring. The lookahead requires the attribute to end at whitespace
    or the tag close, so the `disabled:` variant class never matches.
    """
    import re as _re
    return _re.search(r'\sdisabled(?=[\s>])', tag) is not None


class TestOneSlugLockRule:
    def test_editor_and_routes_share_the_same_function_object(self, app):
        """Test 5 — an IDENTITY assertion, not a behavioural one.

        Two separately-defined functions that happen to agree today would pass
        any behavioural test and still drift apart tomorrow; that is exactly
        how this rule ended up with three implementations. `is` is the only
        assertion that proves site_editor imports the rule rather than
        restating it.
        """
        from app.admin_panel.routes import public_site, site_editor
        assert site_editor._slug_locked is public_site._slug_locked, (
            'site_editor must IMPORT public_site._slug_locked, not define its '
            'own copy — a second definition is the WR-02 defect returning.')

    @pytest.mark.parametrize('slug', sorted(_RESERVED_SLUGS))
    def test_every_reserved_slug_is_locked_and_cannot_be_renamed(
            self, slug, app, db, gadmin_client):
        """Test 6 — the predicate and the server agree across the WHOLE set.

        Parametrized so a failure names the offending slug instead of just
        saying "some reserved slug is renameable".

        Two assertions, because the predicate answering True is worthless if
        the server would still perform the write: the rename is attempted for
        real through Quick Edit. A home_* content block is refused earlier
        still (404 from the block-slug guard, plan 04-01) — either refusal is
        acceptable; the slug surviving unchanged is what is being locked.
        """
        from app.admin_panel.routes.public_site import _slug_locked
        assert _slug_locked(slug) is True, f'{slug!r} must be reported locked'

        page = _ensure_page(db, slug)
        page_id = page.id
        r = gadmin_client.post(f'/admin-panel/public-site/pages/{page_id}/quick-edit',
                               json={'slug': 'renamed-away'})
        assert r.status_code in (200, 404), r.get_data(as_text=True)
        db.session.expire_all()
        fresh = db.session.query(SitePage).get(page_id)
        assert fresh.slug == slug, (
            f'reserved slug {slug!r} was renamed to {fresh.slug!r} — the '
            'server rename guard let a locked permalink through')

    def test_an_ordinary_slug_is_unlocked_and_really_can_be_renamed(
            self, app, db, gadmin_client):
        """Test 7 — the control.

        Without this, the whole reserved-set parametrization above would pass
        just as happily if _slug_locked always returned True and the rename
        path were broken for everyone.
        """
        from app.admin_panel.routes.public_site import _slug_locked
        page = _make_page(db, 'wr02-ordinary-rename')
        page_id = page.id
        assert _slug_locked('wr02-ordinary-rename') is False
        r = gadmin_client.post(f'/admin-panel/public-site/pages/{page_id}/quick-edit',
                               json={'slug': 'wr02-ordinary-renamed'})
        assert r.status_code == 200, r.get_data(as_text=True)
        assert r.get_json()['page']['slug'] == 'wr02-ordinary-renamed'
        db.session.expire_all()
        assert db.session.query(SitePage).get(page_id).slug == 'wr02-ordinary-renamed'

    def test_pages_list_disables_the_permalink_input_for_exactly_the_locked_rows(
            self, app, db, gadmin_client):
        """Test 8 — the template agrees with the server.

        `about` is a reserved slug that is NOT a home content block, so it is
        one of the few reserved rows the Pages list actually renders (the
        home_* rows are filtered out of this screen entirely). Both inputs are
        located by their per-page element id so neither assertion can read the
        other row.
        """
        locked = _ensure_page(db, 'about')
        ordinary = _make_page(db, 'wr02-template-ordinary')
        r = gadmin_client.get('/admin-panel/public-site/pages')
        assert r.status_code == 200, r.get_data(as_text=True)
        html = r.get_data(as_text=True)

        locked_input = _input_tag(html, f'pages-qe-slug-{locked.id}')
        ordinary_input = _input_tag(html, f'pages-qe-slug-{ordinary.id}')
        assert _has_disabled_attr(locked_input), (
            'a reserved permalink was offered as editable in Quick Edit — the '
            f'template drifted from the server rule. Tag: {locked_input}')
        assert not _has_disabled_attr(ordinary_input), (
            'an ordinary page\'s permalink was locked — the template rule is '
            f'wider than the server\'s. Tag: {ordinary_input}')

    def test_pages_list_lock_tracks_the_servers_set_not_a_frozen_literal(
            self, app, db, gadmin_client):
        """The template must READ the server's set, not restate it.

        The deleted Jinja literal happened to list exactly the non-block
        members of _RESERVED_SLUGS, so no fixed slug can tell the old code from
        the new. The distinguishing behaviour is what happens when the SERVER's
        set changes: the view hands _RESERVED_SLUGS itself to the template on
        every render, so a slug added to it must lock immediately. A frozen
        literal would keep rendering that row editable.

        Mutates the real set (and restores it) rather than monkeypatching the
        module attribute, because _slug_locked reads the same object — this
        keeps the server guard and the template in agreement for the duration
        of the test instead of pitting them against each other.
        """
        page = _make_page(db, 'wr02-tracks-server-set')
        url = '/admin-panel/public-site/pages'

        before = _input_tag(gadmin_client.get(url).get_data(as_text=True),
                            f'pages-qe-slug-{page.id}')
        assert not _has_disabled_attr(before), (
            'precondition failed: this ordinary page should start unlocked')

        _RESERVED_SLUGS.add('wr02-tracks-server-set')
        try:
            after = _input_tag(gadmin_client.get(url).get_data(as_text=True),
                               f'pages-qe-slug-{page.id}')
            assert _has_disabled_attr(after), (
                'the Pages list did not lock a permalink the SERVER now '
                'reserves — the template is reading a hardcoded list again '
                f'instead of the set the view passes. Tag: {after}')
        finally:
            _RESERVED_SLUGS.discard('wr02-tracks-server-set')

        restored = _input_tag(gadmin_client.get(url).get_data(as_text=True),
                              f'pages-qe-slug-{page.id}')
        assert not _has_disabled_attr(restored), (
            'the set was not restored — later tests in this module would run '
            'against a polluted _RESERVED_SLUGS')


class TestSlugifyPropertyThatMakesExactMembershipComplete:
    """Test 9 — the whole justification for dropping the `home_*` prefix clause.

    The argument WR-02 rests on has two joints, and both are pinned here:

      1. slugify's output alphabet is exactly [a-z0-9-]. Its implementation is
         `re.sub(r'[^a-z0-9]+', '-', value)` over an already-lowercased string,
         followed by hyphen collapsing — every character outside [a-z0-9] is
         REPLACED, so the only characters that can survive are [a-z0-9] plus
         the '-' the substitution itself introduces. No application-produced
         slug can therefore contain an underscore.
      2. every `home_*` row is a seeded content block, and _BLOCK_SLUGS is a
         subset of _RESERVED_SLUGS.

    Together those make exact membership COMPLETE: a prefix test would only
    ever match rows exact membership already matches. These tests are written
    to fail loudly if someone changes the separator, widens the allowed
    character class, or adds a block slug without reserving it.
    """

    # Deliberately nasty: underscores in every position, unicode, punctuation
    # runs, leading/trailing separators, an already-slug-shaped input, and the
    # degenerate inputs that hit the 'post' fallback.
    _CORPUS = [
        'home_hero', '_leading', 'trailing_', '__double__',
        'snake_case_title', 'MiXeD_CaSe_Input', 'a_b_c_d_e',
        'Hello World', 'Hello, World!!!', '   spaced   out   ',
        '---dashes---', 'dots.and.dots', 'slash/es', 'colon:sep',
        'tabs\tand\nnewlines', 'emoji 🎉 party', 'Ünïcödé Tïtlé',
        'Ω_Ω', 'ＦＵＬＬＷＩＤＴＨ', 'Ⅻ roman', 'ǅ digraph',
        'quote"s', "apostrophe's", 'per%cent', 'plus+plus',
        '2026 season_2', 'a' * 300, '', '   ', '___', '!!!', None,
    ]

    @pytest.mark.parametrize('raw', _CORPUS)
    def test_slugify_never_emits_an_underscore(self, raw):
        out = slugify(raw)
        assert '_' not in out, (
            f'slugify({raw!r}) produced {out!r}. An underscore in a generated '
            'slug breaks the completeness argument for _slug_locked: exact '
            'membership in _RESERVED_SLUGS would no longer cover every home_* '
            'row, and a content block could become renameable. Either restore '
            "the prefix clause in public_site._slug_locked or don't do this.")

    @pytest.mark.parametrize('raw', _CORPUS)
    def test_slugify_output_alphabet_is_exactly_lowercase_alnum_and_hyphen(self, raw):
        """The stronger pin: constrain the ALPHABET, not just the underscore.

        Asserting only "no underscore" would still pass if someone swapped the
        separator to '_' for one branch, or added '_' to the allowed class
        while the sample inputs happened not to exercise it. This asserts the
        full shape — hyphen-separated runs of [a-z0-9], no leading/trailing or
        doubled separator — so ANY change to the character class or the
        separator surfaces here.
        """
        import re as _re
        out = slugify(raw)
        assert _re.fullmatch(r'[a-z0-9]+(-[a-z0-9]+)*', out), (
            f'slugify({raw!r}) produced {out!r}, which is not a hyphen-joined '
            'run of [a-z0-9]. public_site._slug_locked drops the home_* prefix '
            'clause on the strength of this exact property.')

    def test_slugify_replaces_underscores_with_the_hyphen_separator(self):
        """Pins the separator itself, not merely its absence.

        `'a_b'` must become `'a-b'`. If a future edit changed the replacement
        character to '_' this is the test that names it, and the alphabet test
        above catches the rest.
        """
        assert slugify('a_b') == 'a-b'
        assert slugify('home_hero') == 'home-hero'

    def test_every_block_slug_is_reserved(self):
        """The second joint of the argument.

        Exact membership is only complete if every home_* content block is
        actually IN the reserved set. Adding a block slug without reserving it
        would silently make that block's permalink renameable — and renaming a
        content block's slug removes it from the home page with no admin-facing
        way to notice.
        """
        missing = sorted(set(_BLOCK_SLUGS) - _RESERVED_SLUGS)
        assert not missing, (
            f'block slugs missing from _RESERVED_SLUGS: {missing}. '
            '_slug_locked would report them unrenameable-by-accident=False.')

    def test_no_reserved_slug_needs_the_prefix_clause_to_be_matched(self):
        """Every underscore-bearing reserved slug is matched by membership.

        i.e. the dropped `slug.startswith('home_')` clause was redundant, not
        protective — it could only ever have matched rows the exact-membership
        test already matches.
        """
        from app.admin_panel.routes.public_site import _slug_locked
        underscored = [s for s in _RESERVED_SLUGS if '_' in s]
        assert underscored, 'expected at least the home_* blocks to be reserved'
        for slug in underscored:
            assert _slug_locked(slug) is True, slug
            assert slug.startswith('home_'), (
                f'{slug!r} carries an underscore but is not a home_* block — '
                'the completeness argument only covers the home_* family.')

    def test_page_create_end_to_end_cannot_produce_an_underscore_slug(
            self, app, db, gadmin_client):
        """The property, proven through the real write path rather than the
        unit function — the create endpoint is one of the two places a new
        slug enters the table, and it must run its input through slugify."""
        r = gadmin_client.post('/admin-panel/public-site/pages/create',
                               data={'title': 'Wr02_Underscore_Title',
                                     'template': 'blank'})
        assert r.status_code in (302, 303), r.get_data(as_text=True)
        db.session.expire_all()
        page = (db.session.query(SitePage)
                .filter(SitePage.title == 'Wr02_Underscore_Title').first())
        assert page is not None, 'create endpoint did not persist the page'
        assert '_' not in page.slug, (
            f'created page slug {page.slug!r} contains an underscore — the '
            'create path stopped running its input through slugify')

    def test_quick_edit_rename_end_to_end_cannot_produce_an_underscore_slug(
            self, app, db, gadmin_client):
        """The other write path: the rename guard slugifies its candidate."""
        page = _make_page(db, 'wr02-rename-underscore')
        page_id = page.id
        r = gadmin_client.post(f'/admin-panel/public-site/pages/{page_id}/quick-edit',
                               json={'slug': 'home_sneaky_block'})
        assert r.status_code == 200, r.get_data(as_text=True)
        db.session.expire_all()
        fresh = db.session.query(SitePage).get(page_id)
        assert '_' not in fresh.slug, (
            f'rename produced {fresh.slug!r} — an underscore slug would defeat '
            'the exact-membership completeness argument')
        assert fresh.slug == 'home-sneaky-block'


# --------------------------------------------------------------------------- #
# Plan 04-04 / IN-01: the volunteer reads a sentence, not an error code
#
# The editor panel already translates the empty-page refusal into plain
# English (app/static/js/site-editor/shell.js). Quick Edit surfaced whatever
# the server sent — `empty_page` — to the same person for the same condition.
# --------------------------------------------------------------------------- #

_EMPTY_PAGE_SENTENCE = 'Add some content before publishing this page.'


class TestQuickEditEmptyPageMessage:
    def test_quick_edit_handler_carries_the_editors_exact_sentence(
            self, app, db, gadmin_client):
        """Test 10 — the EXACT sentence, character for character.

        Asserted as a literal rather than a fuzzy match so a reworded
        near-duplicate ("Add content before publishing") fails here instead of
        quietly giving the volunteer two different sentences for one
        condition. The same literal appears in shell.js:702.
        """
        _make_page(db, 'in01-message-render')
        r = gadmin_client.get('/admin-panel/public-site/pages')
        assert r.status_code == 200, r.get_data(as_text=True)
        html = r.get_data(as_text=True)
        assert _EMPTY_PAGE_SENTENCE in html, (
            'the Pages list Quick Edit handler does not translate the '
            'empty_page refusal — a volunteer would read the raw error code.')
        assert "'empty_page'" in html, (
            'the sentence is present but not keyed on the server error string')

    def test_generic_fallback_is_still_present(self, app, db, gadmin_client):
        """Test 11 — the control.

        The change must ADD a translation for one condition, not REPLACE the
        catch-all. Suppressing unexpected server errors from the person who
        triggered them would be worse than showing them (T-04-17 accepts the
        raw string for every other case on purpose).
        """
        _make_page(db, 'in01-fallback-render')
        r = gadmin_client.get('/admin-panel/public-site/pages')
        assert r.status_code == 200
        html = r.get_data(as_text=True)
        assert "'Save failed'" in html, (
            'the generic Quick Edit failure fallback disappeared — every '
            'non-empty_page error would now render as an empty message')

    def test_server_still_produces_the_condition_the_handler_translates(
            self, app, db, gadmin_client):
        """Test 12 — the branch is reachable, not decorative.

        Quick Edit's allowed field set includes `status`, so a volunteer can
        flip a contentless page to Published from the table row. Without this
        test, Tests 10 and 11 would be asserting against a handler branch the
        server can never trigger.
        """
        page = _make_page(db, 'in01-empty-publish', status='draft',
                          sections_draft=None, sections_published=None)
        page_id = page.id
        r = gadmin_client.post(f'/admin-panel/public-site/pages/{page_id}/quick-edit',
                               json={'status': 'published'})
        assert r.status_code == 400, r.get_data(as_text=True)
        data = r.get_json()
        assert data['success'] is False
        assert data['error'] == 'empty_page', (
            'the Quick Edit handler keys its plain-English sentence on this '
            f"exact string; the server sent {data.get('error')!r}")
        db.session.expire_all()
        assert db.session.query(SitePage).get(page_id).status == 'draft'
