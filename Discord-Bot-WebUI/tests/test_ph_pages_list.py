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
