"""Page settings live inside the editor now, not on a separate screen.

Phase 3 plan 03-01 (PSB-07/PSB-08/PSB-09) folded the standalone
`public_site_page_edit` / `page_edit_flowbite.html` settings screen into the
site editor's in-panel "Page settings" slide-over, and added two columns
(`SitePage.excerpt`, `SitePage.featured_image_url`) that previously did not
exist at all. This module locks:

  1. The round trip: excerpt -> POST /page-settings -> DB -> echoed response.
  2. That a payload carrying only SOME keys never wipes the keys it omits
     (apply_page_settings's membership-test contract plan 03-03's Quick Edit
     and bulk actions depend on).
  3. The full WordPress-parity field set (status, permalink, excerpt,
     featured image, search title, search description) in one POST.
  4. The reserved-slug permalink lock is enforced server-side, not just
     hidden client-side.
  5. The draft -> published transition's stale-revision CAS guard, and that
     metadata-only saves are deliberately NOT CAS-protected (no lost-update
     hazard against the section document) and never advance draft_rev.
  6. The same-app /static rule on featured_image_url (never is_safe_link_url).
  7. The retired screen 302s into the editor instead of rendering or 404ing.
  8. excerpt/featured_image_url feed meta description / og:description /
     og:image on the public site, with an explicit override still winning.
"""
import pytest

from app.models import SitePage


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


_DOC = {'v': 1, 'sections': [
    {'id': 's1', 'type': 'content', 'theme': 'inherit', 'settings': {},
     'blocks': [{'id': 'b1', 'type': 'heading', 'level': 2, 'html': 'Hi there'}]}]}


def _make_page(db, slug, **kwargs):
    defaults = dict(title='Settings Test', status='draft', sections_draft=_DOC)
    defaults.update(kwargs)
    p = SitePage(slug=slug, **defaults)
    db.session.add(p)
    db.session.commit()
    return p


def _head(html):
    """Scope an assertion to <head>...</head> so a body-text match can never
    be mistaken for a meta tag."""
    return html.split('<head', 1)[1].split('</head>', 1)[0]


# --------------------------------------------------------------------------- #
# Task 1: the tracer slice -- excerpt round-trips end to end
# --------------------------------------------------------------------------- #

class TestPageSettingsRoundTrip:
    def test_excerpt_round_trips_on_the_model(self, app, db):
        # Must be RED before SitePage.excerpt exists (AttributeError/TypeError).
        p = _make_page(db, 'ps-model-roundtrip')
        p.excerpt = 'Hello from the panel'
        db.session.commit()
        db.session.expire_all()
        fresh = db.session.query(SitePage).get(p.id)
        assert fresh.excerpt == 'Hello from the panel'

    def test_page_settings_endpoint_round_trips_excerpt(self, app, db, gadmin_client):
        p = _make_page(db, 'ps-endpoint-roundtrip')
        r = gadmin_client.post(f'/admin-panel/site-editor/{p.id}/page-settings',
                               json={'excerpt': 'Hello from the panel'})
        assert r.status_code == 200, r.get_data(as_text=True)
        data = r.get_json()
        assert data['success'] is True
        assert data['page']['excerpt'] == 'Hello from the panel'
        db.session.expire_all()
        fresh = db.session.query(SitePage).get(p.id)
        assert fresh.excerpt == 'Hello from the panel'

    def test_editor_shell_renders_page_settings_button(self, app, db, gadmin_client):
        p = _make_page(db, 'ps-shell-button', status='published',
                       sections_published=_DOC)
        r = gadmin_client.get(f'/admin-panel/site-editor/{p.id}')
        assert r.status_code == 200, (r.status_code, r.get_data(as_text=True)[:400])
        assert 'id="pse-page-settings"' in r.get_data(as_text=True)

    def test_page_settings_endpoint_requires_auth(self, app, db, client):
        p = _make_page(db, 'ps-auth')
        r = client.post(f'/admin-panel/site-editor/{p.id}/page-settings',
                        json={'excerpt': 'nope'})
        assert r.status_code != 200

    def test_partial_payload_does_not_wipe_untouched_fields(self, app, db, gadmin_client):
        # This is THE contract plan 03-03's Quick Edit / bulk actions depend
        # on: a payload carrying only `status` must leave title/excerpt/SEO
        # completely alone.
        p = _make_page(db, 'ps-partial', title='Original Title',
                       excerpt='Original excerpt',
                       meta_description='Original meta description')
        r = gadmin_client.post(f'/admin-panel/site-editor/{p.id}/page-settings',
                               json={'status': 'draft'})
        assert r.status_code == 200, r.get_data(as_text=True)
        db.session.expire_all()
        fresh = db.session.query(SitePage).get(p.id)
        assert fresh.title == 'Original Title'
        assert fresh.excerpt == 'Original excerpt'
        assert fresh.meta_description == 'Original meta description'


# --------------------------------------------------------------------------- #
# Task 2: the full field set, permalink lock, publish CAS, image validation
# --------------------------------------------------------------------------- #

class TestPageSettingsFullFieldSet:
    def test_panel_persists_all_six_fields_in_one_post(self, app, db, gadmin_client):
        p = _make_page(db, 'ps-full-fields')
        payload = {
            'status': 'draft',
            'slug': 'ps-full-fields-renamed',
            'excerpt': 'A full excerpt',
            'featured_image_url': '/static/img/publeague/test.jpg',
            'meta_title': 'A search title',
            'meta_description': 'A search description',
        }
        r = gadmin_client.post(f'/admin-panel/site-editor/{p.id}/page-settings', json=payload)
        assert r.status_code == 200, r.get_data(as_text=True)
        db.session.expire_all()
        fresh = db.session.query(SitePage).get(p.id)
        assert fresh.slug == 'ps-full-fields-renamed'
        assert fresh.excerpt == 'A full excerpt'
        assert fresh.featured_image_url == '/static/img/publeague/test.jpg'
        assert fresh.meta_title == 'A search title'
        assert fresh.meta_description == 'A search description'

    def test_reserved_slug_cannot_be_renamed(self, app, db, gadmin_client):
        p = _make_page(db, 'about', status='published', sections_published=_DOC)
        r = gadmin_client.post(f'/admin-panel/site-editor/{p.id}/page-settings',
                               json={'slug': 'something-else'})
        assert r.status_code == 200, r.get_data(as_text=True)
        db.session.expire_all()
        fresh = db.session.query(SitePage).get(p.id)
        assert fresh.slug == 'about'

    def test_draft_to_published_copies_sections_and_sets_published_at(self, app, db, gadmin_client):
        p = _make_page(db, 'ps-publish-flip', status='draft', sections_published=None)
        r = gadmin_client.post(f'/admin-panel/site-editor/{p.id}/page-settings',
                               json={'status': 'published', 'base_rev': p.draft_rev or 0})
        assert r.status_code == 200, r.get_data(as_text=True)
        db.session.expire_all()
        fresh = db.session.query(SitePage).get(p.id)
        assert fresh.status == 'published'
        assert fresh.sections_published == _DOC
        assert fresh.published_at is not None

    def test_stale_base_rev_on_publish_returns_409_and_changes_nothing(self, app, db, gadmin_client):
        p = _make_page(db, 'ps-stale-publish', status='draft', sections_published=None)
        r = gadmin_client.post(f'/admin-panel/site-editor/{p.id}/page-settings',
                               json={'status': 'published', 'base_rev': 999})
        assert r.status_code == 409
        data = r.get_json()
        assert data['error'] == 'stale_rev'
        db.session.expire_all()
        fresh = db.session.query(SitePage).get(p.id)
        assert fresh.status == 'draft'
        assert fresh.sections_published is None

    def test_metadata_only_save_with_stale_base_rev_still_succeeds(self, app, db, gadmin_client):
        # Metadata carries no lost-update hazard against the section document,
        # so it deliberately skips the CAS check the publish transition uses.
        p = _make_page(db, 'ps-stale-metadata', status='published', sections_published=_DOC)
        r = gadmin_client.post(f'/admin-panel/site-editor/{p.id}/page-settings',
                               json={'excerpt': 'Still works', 'base_rev': 999})
        assert r.status_code == 200, r.get_data(as_text=True)
        db.session.expire_all()
        fresh = db.session.query(SitePage).get(p.id)
        assert fresh.excerpt == 'Still works'

    def test_metadata_only_save_does_not_advance_draft_rev(self, app, db, gadmin_client):
        p = _make_page(db, 'ps-draftrev-untouched')
        before = p.draft_rev or 0
        r = gadmin_client.post(f'/admin-panel/site-editor/{p.id}/page-settings',
                               json={'excerpt': 'no bump'})
        assert r.status_code == 200, r.get_data(as_text=True)
        db.session.expire_all()
        fresh = db.session.query(SitePage).get(p.id)
        assert (fresh.draft_rev or 0) == before

    def test_non_static_featured_image_is_stored_as_null(self, app, db, gadmin_client):
        p = _make_page(db, 'ps-bad-image')
        r = gadmin_client.post(f'/admin-panel/site-editor/{p.id}/page-settings',
                               json={'featured_image_url': 'https://evil.example.com/x.png'})
        assert r.status_code == 200, r.get_data(as_text=True)
        db.session.expire_all()
        fresh = db.session.query(SitePage).get(p.id)
        assert fresh.featured_image_url is None

    def test_state_reports_status_draft_then_published(self, app, db, gadmin_client):
        p = _make_page(db, 'ps-state-status', status='draft', sections_published=None)
        r1 = gadmin_client.get(f'/admin-panel/site-editor/{p.id}/state')
        assert r1.get_json()['page']['status'] == 'draft'
        r2 = gadmin_client.post(f'/admin-panel/site-editor/{p.id}/page-settings',
                                json={'status': 'published', 'base_rev': p.draft_rev or 0})
        assert r2.status_code == 200, r2.get_data(as_text=True)
        r3 = gadmin_client.get(f'/admin-panel/site-editor/{p.id}/state')
        assert r3.get_json()['page']['status'] == 'published'


# --------------------------------------------------------------------------- #
# Task 3: the retired screen redirects; public SEO precedence
# --------------------------------------------------------------------------- #

class TestRetiredScreenRedirects:
    def test_old_settings_url_redirects_into_editor_with_panel_param(self, app, db, gadmin_client):
        p = _make_page(db, 'ps-redirect', status='published', sections_published=_DOC)
        r = gadmin_client.get(f'/admin-panel/public-site/pages/{p.id}/edit')
        assert r.status_code == 302
        location = r.headers.get('Location', '')
        assert f'/admin-panel/site-editor/{p.id}' in location
        assert 'panel=page' in location


class TestPublicSEOFields:
    def test_dynamic_page_uses_excerpt_and_featured_image_as_fallback(self, app, db, client):
        _make_page(db, 'ps-public-dynamic', status='published', sections_published=_DOC,
                  excerpt='A dynamic excerpt', featured_image_url='/static/img/publeague/dyn.jpg')
        r = client.get('/preview/ps-public-dynamic')
        assert r.status_code == 200, (r.status_code, r.get_data(as_text=True)[:400])
        head = _head(r.get_data(as_text=True))
        assert 'A dynamic excerpt' in head
        assert '/static/img/publeague/dyn.jpg' in head

    def test_about_page_uses_excerpt_and_featured_image_as_fallback(self, app, db, client):
        _make_page(db, 'about', status='published', sections_published=_DOC,
                  excerpt='About excerpt text', featured_image_url='/static/img/publeague/about.jpg')
        r = client.get('/preview/about')
        assert r.status_code == 200, (r.status_code, r.get_data(as_text=True)[:400])
        head = _head(r.get_data(as_text=True))
        assert 'About excerpt text' in head
        assert '/static/img/publeague/about.jpg' in head

    def test_home_page_uses_excerpt_and_featured_image_as_fallback(self, app, db, client):
        _make_page(db, 'home', status='published', sections_published=_DOC,
                  excerpt='Home excerpt text', featured_image_url='/static/img/publeague/home.jpg')
        r = client.get('/preview/')
        assert r.status_code == 200, (r.status_code, r.get_data(as_text=True)[:400])
        head = _head(r.get_data(as_text=True))
        assert 'Home excerpt text' in head
        assert '/static/img/publeague/home.jpg' in head

    def test_explicit_meta_description_still_wins_over_excerpt(self, app, db, client):
        _make_page(db, 'ps-public-override', status='published', sections_published=_DOC,
                  excerpt='Should not appear in the head',
                  meta_description='Explicit meta description wins')
        r = client.get('/preview/ps-public-override')
        assert r.status_code == 200, (r.status_code, r.get_data(as_text=True)[:400])
        head = _head(r.get_data(as_text=True))
        assert 'Explicit meta description wins' in head
        assert 'Should not appear in the head' not in head


# --------------------------------------------------------------------------- #
# Plan 04-04 / WR-01: ONE compare-and-swap check, and a docstring that is true
#
# `apply_page_settings` used to take a third parameter (`allow_publish_copy`)
# whose only effect was an early `return False, 'stale_rev'`. No call site ever
# passed anything but the default, and the real compare-and-swap check lives
# OUTSIDE the helper — in site_editor_page_settings, which compares the
# client's base_rev against the page's draft_rev and returns 409 BEFORE the
# helper runs. The branch was dead code and the docstring described it as the
# mechanism the editor uses, which was false.
#
# These four tests lock the removal AND lock that the protection the removed
# branch appeared to provide is still enforced from its real home.
# --------------------------------------------------------------------------- #

class TestApplyPageSettingsHasOneCheck:
    def test_helper_takes_only_page_and_data(self, app):
        """The dead parameter is gone.

        Asserted through `inspect.signature`, deliberately NOT through a source
        grep: a text search would be satisfied by a comment mentioning the old
        name (this module's own header does) and would break the moment someone
        writes the word in prose. The signature is the thing that matters.
        """
        import inspect
        from app.admin_panel.routes.public_site import apply_page_settings
        params = list(inspect.signature(apply_page_settings).parameters)
        assert params == ['page', 'data'], (
            'apply_page_settings must take exactly (page, data) — a third '
            'parameter means the publish-copy refusal has grown a second '
            f'implementation again. Got: {params}')

    def test_stale_revision_publish_is_still_refused_with_409(self, app, db, gadmin_client):
        """The protection did not leave with the dead branch.

        Seeds a REAL draft revision (7) and sends a base_rev one behind it, so
        the comparison is meaningful rather than a None-vs-0 accident. The
        refusal must come from site_editor_page_settings' own check, and the
        published sections must be untouched — that copy is the whole reason
        this transition is compare-and-swap protected at all.
        """
        p = _make_page(db, 'wr01-stale-publish', status='draft',
                       sections_published=None, draft_rev=7)
        r = gadmin_client.post(f'/admin-panel/site-editor/{p.id}/page-settings',
                               json={'status': 'published', 'base_rev': 6})
        assert r.status_code == 409, r.get_data(as_text=True)
        data = r.get_json()
        assert data['success'] is False
        assert data['error'] == 'stale_rev'
        assert data['draft_rev'] == 7, 'the client is told which revision to reload'
        db.session.expire_all()
        fresh = db.session.query(SitePage).get(p.id)
        assert fresh.status == 'draft', 'a stale publish must not flip status'
        assert fresh.sections_published is None, \
            'a stale publish copied draft sections into the LIVE column'

    def test_matching_revision_publish_still_copies_sections(self, app, db, gadmin_client):
        """The happy path still copies. Same seeded revision, correct base_rev."""
        p = _make_page(db, 'wr01-fresh-publish', status='draft',
                       sections_published=None, draft_rev=7)
        r = gadmin_client.post(f'/admin-panel/site-editor/{p.id}/page-settings',
                               json={'status': 'published', 'base_rev': 7})
        assert r.status_code == 200, r.get_data(as_text=True)
        assert r.get_json()['success'] is True
        db.session.expire_all()
        fresh = db.session.query(SitePage).get(p.id)
        assert fresh.status == 'published'
        assert fresh.sections_published == _DOC
        assert fresh.published_at is not None

    def test_bulk_publish_caller_is_unaffected_by_the_removal(self, app, db, gadmin_client):
        """The call site that never passed the parameter, proven untouched.

        Bulk publish reaches apply_page_settings with only {'status': ...} and
        no revision of any kind. It must still publish an ordinary page and
        must still refuse a page with no content in either column — the empty
        -page refusal is the helper's ONLY surviving failure mode.
        """
        good = _make_page(db, 'wr01-bulk-good')
        empty = _make_page(db, 'wr01-bulk-empty', sections_draft=None,
                           sections_published=None)
        r = gadmin_client.post('/admin-panel/public-site/pages/bulk',
                               json={'action': 'publish',
                                     'page_ids': [good.id, empty.id]})
        assert r.status_code == 200, r.get_data(as_text=True)
        data = r.get_json()
        assert data['updated'] == 1
        assert empty.id in data['skipped']
        db.session.expire_all()
        assert db.session.query(SitePage).get(good.id).status == 'published'
        assert db.session.query(SitePage).get(empty.id).status == 'draft'
