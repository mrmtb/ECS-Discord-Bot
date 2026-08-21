"""Site Editor authorization regression module (Phase 4, SHIP-03).

The Site Editor is the least-privilege role this milestone introduces. Before
this module, the entire suite held exactly ONE authorization test for it —
`tests/test_public_site_runtime.py::TestRoleBoundary`, a single Pages-versus-
Appearance pair. That single pair proved the role gate on two routes; it said
nothing about the other ten routes that share the identical un-guarded
client-supplied-`page_id` pattern Phase 3's code review found and fixed in
only two of twelve places (CR-01). This module makes the audit repeatable
rather than a one-time read: it walks every route this phase's plan names —
the single-item Pages-list actions, the retired save-by-form-body route, the
entire site-editor surface, the bulk endpoint's skip semantics, and the
Submissions/Menu role boundary (D-01/D-02) — and proves each one as a real
Site Editor over real HTTP, with controls proving every refusal comes from
the guard itself rather than from a missing fixture, a login redirect, or a
route that quietly stopped existing.

FIXTURE HAZARD — the single most important constraint in this module.
`client` (tests/conftest.py) returns ONE `app.test_client()` instance, and
every role fixture below (`gadmin_client`, `site_editor_client`) wraps that
SAME instance by writing `sess['_user_id']` into it. Requesting two role
clients in one test body means the second silently overwrites the first's
session cookie, and an authorization assertion then passes for the wrong
reason. Use exactly ONE role fixture per test function. Where a test needs a
contrasting role, that contrast goes in a SEPARATE test function with its own
fixture — never combine two role clients in a single test body.

WHAT THIS MODULE DELIBERATELY DOES NOT COVER. Being explicit about the edge of
the coverage stops the next reader from assuming a guarantee that is not here:

* Browser interactivity. Whether the shortened Website dropdown and hub card
  grid READ as deliberate rather than as a truncated menu, and whether the
  editor is actually usable by a volunteer, are visual judgments. They are a
  human pass in plan 04-05, not a Playwright suite — this project's Phase 3
  precedent. Everything below asserts status codes and resolved URLs only, and
  never rendered label text, so a copy change can never break an
  authorization test.

* Row-level authorization for Posts, FAQs and Media. Those surfaces have no
  content-block analog — there is no hidden row class that the Pages list
  filters out and that would therefore vanish with no admin-facing way to
  notice or recover it. The block-slug guard tables below are specific to
  SitePage rows and say nothing about NewsPost, Faq or MediaAsset.

* The bulk endpoint's per-id semantics beyond the one skip case already
  covered by TestBulkKeepsSkipSemantics.
"""
import pytest

from app.models import SitePage
from app.admin_panel.routes.public_site import _BLOCK_SLUGS


# --------------------------------------------------------------------------- #
# Fixtures — copied verbatim in shape from tests/test_ph_pages_list.py.
# One role fixture per test. See the FIXTURE HAZARD note above.
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
    u = db.session.query(User).filter_by(username='pl-siteeditor-rb').first()
    if not u:
        u = User(username='pl-siteeditor-rb', email='pl-se-rb@example.com',
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
    defaults = dict(title='Role Boundary Test Page', status='draft', sections_draft=_DOC)
    defaults.update(kwargs)
    p = SitePage(slug=slug, **defaults)
    db.session.add(p)
    db.session.commit()
    return p


def _make_block(db):
    """Create (or reuse) the SitePage row for `_BLOCK_SLUGS[0]` — a real
    home-page content block, imported from the routes module rather than
    typed as a literal. COMMIT, not flush: a route that aborts 404 inside
    @transactional rolls the session back, so a merely-flushed fixture row
    would vanish and the read-back would be None."""
    slug = _BLOCK_SLUGS[0]
    blk = db.session.query(SitePage).filter_by(slug=slug).first()
    if not blk:
        blk = SitePage(slug=slug, title='Home hero', status='published')
        db.session.add(blk)
    db.session.commit()
    return blk


# --------------------------------------------------------------------------- #
# Task 1: end-to-end tracer — one predicate, one helper, one route
# --------------------------------------------------------------------------- #

class TestTrashRefusesBlockSlug:
    def test_site_editor_trash_of_block_row_is_404_and_block_row_survives_a_site_editor_trash_post(
            self, app, db, site_editor_client):
        blk = _make_block(db)
        blk_id = blk.id
        r = site_editor_client.post(f'/admin-panel/public-site/pages/{blk_id}/trash')
        assert r.status_code == 404, r.get_data(as_text=True)
        db.session.expire_all()
        still = db.session.query(SitePage).get(blk_id)
        assert still.deleted_at is None, 'block row was trashed by a Site Editor with no recovery path'

    def test_global_admin_trash_of_block_row_is_also_404_block_row_survives_a_global_admin_trash_post(
            self, app, db, gadmin_client):
        blk = _make_block(db)
        blk_id = blk.id
        r = gadmin_client.post(f'/admin-panel/public-site/pages/{blk_id}/trash')
        assert r.status_code == 404, r.get_data(as_text=True)
        db.session.expire_all()
        still = db.session.query(SitePage).get(blk_id)
        assert still.deleted_at is None, 'the guard is about the ROW, not the role'

    def test_site_editor_trash_of_an_ordinary_page_still_succeeds_control(
            self, app, db, site_editor_client):
        page = _make_page(db, 'rb-trash-ordinary')
        page_id = page.id
        r = site_editor_client.post(f'/admin-panel/public-site/pages/{page_id}/trash')
        assert r.status_code == 302, r.get_data(as_text=True)
        db.session.expire_all()
        fresh = db.session.query(SitePage).get(page_id)
        assert fresh.deleted_at is not None, 'the guard must be narrow, not a blanket break'

    def test_unauthenticated_post_to_trash_is_not_a_404_control(self, app, db, client):
        # A bare, never-logged-in `client` — do NOT also request gadmin_client
        # or site_editor_client here, they share the same session cookie.
        blk = _make_block(db)
        r = client.post(f'/admin-panel/public-site/pages/{blk.id}/trash')
        assert r.status_code != 404, (
            'a 404 here would come from a missing session, not the row guard — '
            'proves Tests 1-2\'s 404 provably comes from the row check')


# --------------------------------------------------------------------------- #
# Task 2: the other sixteen call sites
# --------------------------------------------------------------------------- #

_SINGLE_ITEM_BLOCK_ROUTES = [
    ('/admin-panel/public-site/pages/{id}/restore', 'POST'),
    ('/admin-panel/public-site/pages/{id}/delete', 'POST'),
    ('/admin-panel/public-site/pages/{id}/publish', 'POST'),
]


class TestSingleItemRoutesRefuseBlockSlug:
    @pytest.mark.parametrize('url_tpl,method', _SINGLE_ITEM_BLOCK_ROUTES,
                              ids=[u for u, _ in _SINGLE_ITEM_BLOCK_ROUTES])
    def test_single_item_route_refuses_block_id(self, app, db, site_editor_client,
                                                 url_tpl, method):
        blk = _make_block(db)
        blk_id = blk.id
        url = url_tpl.format(id=blk_id)
        r = site_editor_client.post(url)
        assert r.status_code == 404, r.get_data(as_text=True)
        db.session.expire_all()
        still = db.session.query(SitePage).get(blk_id)
        assert still.deleted_at is None
        assert still.slug == _BLOCK_SLUGS[0]

    def test_revision_restore_refuses_block_id(self, app, db, site_editor_client):
        from app.models import SitePageRevision
        blk = _make_block(db)
        rev = SitePageRevision(page_id=blk.id, title='Old title',
                                sections=_DOC, kind='publish')
        db.session.add(rev)
        db.session.commit()
        r = site_editor_client.post(
            f'/admin-panel/public-site/pages/{blk.id}/revisions/{rev.id}/restore')
        assert r.status_code == 404, r.get_data(as_text=True)
        db.session.expire_all()
        still = db.session.query(SitePage).get(blk.id)
        assert still.title == 'Home hero'

    def test_duplicate_refuses_block_id(self, app, db, site_editor_client):
        blk = _make_block(db)
        before = db.session.query(SitePage).count()
        r = site_editor_client.post(f'/admin-panel/public-site/pages/{blk.id}/duplicate')
        assert r.status_code == 404, r.get_data(as_text=True)
        db.session.expire_all()
        after = db.session.query(SitePage).count()
        assert after == before, 'a block must never be duplicated into a new draft'


class TestPageSaveFormBodyRefusesBlockSlug:
    def test_page_save_by_form_body_id_refuses_block_slug(self, app, db, site_editor_client):
        blk = _make_block(db)
        blk.status = 'draft'
        db.session.commit()
        blk_id = blk.id
        site_editor_client.post('/admin-panel/public-site/pages/save',
                                data={'id': str(blk_id), 'title': 'pwned',
                                      'status': 'published'})
        db.session.expire_all()
        still = db.session.query(SitePage).get(blk_id)
        assert still.title != 'pwned', 'the form-body id must not fall through to a successful write'
        assert still.status != 'published', (
            'the form-body id must not fall through to a successful publish')


class TestEditorSurfaceRefusesBlockSlug:
    def test_editor_shell_get_refuses_block_id(self, app, db, site_editor_client):
        blk = _make_block(db)
        r = site_editor_client.get(f'/admin-panel/site-editor/{blk.id}')
        assert r.status_code == 404, r.get_data(as_text=True)

    def test_editor_state_refuses_block_id(self, app, db, site_editor_client):
        blk = _make_block(db)
        r = site_editor_client.get(f'/admin-panel/site-editor/{blk.id}/state')
        assert r.status_code == 404, r.get_data(as_text=True)


class TestBulkKeepsSkipSemantics:
    def test_bulk_publish_reports_block_under_skipped_not_404(self, app, db, gadmin_client):
        blk = _make_block(db)
        blk.status = 'draft'
        db.session.commit()
        blk_id = blk.id
        page = _make_page(db, 'rb-bulk-mixed-real')
        r = gadmin_client.post('/admin-panel/public-site/pages/bulk',
                               json={'action': 'publish', 'page_ids': [blk_id, page.id]})
        assert r.status_code == 200, r.get_data(as_text=True)
        data = r.get_json()
        assert data['updated'] == 1
        assert blk_id in data['skipped']
        db.session.expire_all()
        assert db.session.query(SitePage).get(page.id).status == 'published'
        assert db.session.query(SitePage).get(blk_id).status == 'draft'


class TestFullAdminOrdinaryPageStillWorksControl:
    def test_full_admin_duplicate_of_ordinary_page_still_succeeds(self, app, db, gadmin_client):
        page = _make_page(db, 'rb-dup-ordinary')
        before = db.session.query(SitePage).count()
        r = gadmin_client.post(f'/admin-panel/public-site/pages/{page.id}/duplicate')
        assert r.status_code == 302, r.get_data(as_text=True)
        db.session.expire_all()
        after = db.session.query(SitePage).count()
        assert after == before + 1, 'refactor must narrow rows, not break functionality'


# --------------------------------------------------------------------------- #
# Task 3: Submissions refused (D-01), Menu stays reachable (D-02),
# hub/tabs hide admin-only surfaces from a Site Editor.
# --------------------------------------------------------------------------- #

class TestSubmissionsRefusedForSiteEditor:
    def test_site_editor_get_submissions_is_403(self, app, db, site_editor_client):
        r = site_editor_client.get('/admin-panel/public-site/submissions')
        assert r.status_code == 403, r.get_data(as_text=True)

    def test_site_editor_post_submissions_mark_read_is_403(self, app, db, site_editor_client):
        from app.models import FormSubmission
        sub = FormSubmission(form_name='contact', data_json='{}', source_page='/contact')
        db.session.add(sub)
        db.session.commit()
        r = site_editor_client.post(f'/admin-panel/public-site/submissions/{sub.id}/read')
        assert r.status_code == 403, r.get_data(as_text=True)

    def test_site_editor_post_submissions_delete_is_403(self, app, db, site_editor_client):
        from app.models import FormSubmission
        sub = FormSubmission(form_name='contact', data_json='{}', source_page='/contact')
        db.session.add(sub)
        db.session.commit()
        r = site_editor_client.post(f'/admin-panel/public-site/submissions/{sub.id}/delete')
        assert r.status_code == 403, r.get_data(as_text=True)


class TestSubmissionsAllowedForGlobalAdminControl:
    def test_global_admin_get_submissions_is_200(self, app, db, gadmin_client):
        r = gadmin_client.get('/admin-panel/public-site/submissions')
        assert r.status_code == 200, r.get_data(as_text=True)


class TestMenuStaysReachableForSiteEditor:
    def test_site_editor_get_menu_is_200(self, app, db, site_editor_client):
        r = site_editor_client.get('/admin-panel/public-site/menu')
        assert r.status_code == 200, r.get_data(as_text=True)


def _hub_cards_region(html):
    """Scope an assertion to the hub's card-grid region
    (<div id="cms-hub-cards">...</div>) so a match in the sidebar's separate,
    endpoint_exists()-gated Website submenu — a distinct, pre-existing nav
    surface out of this plan's scope (not in files_modified; see
    deferred-items.md) — can't make a hub-card assertion pass for the wrong
    reason."""
    return html.split('id="cms-hub-cards"', 1)[1]


class TestHubHidesAdminOnlySurfacesFromSiteEditor:
    def test_hub_omits_appearance_redirects_submissions_keeps_pages_media(
            self, app, db, site_editor_client):
        with app.app_context():
            from flask import url_for
            appearance_url = url_for('admin_panel.public_site_appearance')
            redirects_url = url_for('admin_panel.public_site_redirects')
            submissions_url = url_for('admin_panel.public_site_submissions')
            pages_url = url_for('admin_panel.public_site_pages')
            media_url = url_for('admin_panel.public_site_media')
        r = site_editor_client.get('/admin-panel/public-site')
        assert r.status_code == 200
        cards = _hub_cards_region(r.get_data(as_text=True))
        assert appearance_url not in cards
        assert redirects_url not in cards
        assert submissions_url not in cards
        assert pages_url in cards
        assert media_url in cards


class TestHubShowsAdminOnlySurfacesForGlobalAdminControl:
    def test_hub_carries_appearance_redirects_submissions_for_global_admin(
            self, app, db, gadmin_client):
        with app.app_context():
            from flask import url_for
            appearance_url = url_for('admin_panel.public_site_appearance')
            redirects_url = url_for('admin_panel.public_site_redirects')
            submissions_url = url_for('admin_panel.public_site_submissions')
        r = gadmin_client.get('/admin-panel/public-site')
        assert r.status_code == 200
        cards = _hub_cards_region(r.get_data(as_text=True))
        assert appearance_url in cards
        assert redirects_url in cards
        assert submissions_url in cards


# =========================================================================== #
# Plan 04-03 — the audit as a repeatable suite.
#
# Everything below turns the reachability audit from a one-time read of the
# routes into three tables that run on every `pytest` invocation:
#
#   1. _REACH_SURFACES      — every surface a Site Editor is SUPPOSED to have
#   2. _ADMIN_ONLY_SURFACES — every surface they must be refused, each with a
#                             full-admin control in a SEPARATE test function
#   3. _PAGE_ID_ROUTES      — every route that accepts a client-supplied page
#                             id, plus a completeness gate asserting that set
#                             is EQUAL to the live Flask url_map's
#
# Table 3's gate is the durable half of the CR-01 fix. Plan 04-01 guarded the
# routes that exist today; the gate is what makes the eleventh route someone
# adds next year fail a test instead of quietly re-opening the class.
# =========================================================================== #

from flask import url_for


def _url(app, endpoint, **values):
    """Resolve an ENDPOINT NAME to a path.

    Two deliberate choices here, both load-bearing:

    * Endpoint names, never path literals. A route rename then fails this
      module loudly (BuildError) instead of leaving an assertion pointed at a
      dead path that 404s — and a 404 would satisfy neither `== 403` nor
      `!= 403`, so a renamed route would produce a confusing failure at best
      and, in the guard table, a PASS for entirely the wrong reason at worst.

    * `_external=False` is explicit. Outside a request context `url_for`
      builds EXTERNAL urls by default, and this suite's config sets
      SERVER_NAME, so the default would hand back
      'http://localhost:5000/admin-panel/...'. That still works as a test-
      client target, but it silently breaks the completeness gate's
      `rule.rule.startswith(prefix)` comparison against the url_map's relative
      paths — the gate would see zero live routes and report every audited
      entry as stale.
    """
    with app.app_context():
        return url_for(endpoint, _external=False, **values)


class _RuntimeId:
    """Placeholder for an id that does not exist until a fixture has created
    the row. Lets the tables below stay module-level constants (so a failure
    names the endpoint, and so the completeness gate can read the key set at
    import time) while still addressing real database rows."""

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f'<runtime:{self.name}>'


_ORDINARY_PAGE_ID = _RuntimeId('ordinary_page_id')
_BLOCK_REVISION_ID = _RuntimeId('block_revision_id')
_REDIRECT_RULE_ID = _RuntimeId('redirect_rule_id')
_SUBMISSION_ID = _RuntimeId('submission_id')


def _resolve(url_kwargs, **runtime):
    """Substitute real row ids for the _RuntimeId placeholders. Raises rather
    than passing None through — a None here would build a url like
    '/pages/None/trash', Werkzeug would refuse the int converter, and the
    resulting error would look nothing like the authorization failure the
    test is actually about."""
    out = {}
    for key, val in url_kwargs.items():
        if isinstance(val, _RuntimeId):
            got = runtime.get(val.name)
            assert got is not None, (
                f'{key} needs the runtime id {val.name!r}, which no fixture '
                f'supplied — fix the test wiring, do not relax the assertion')
            out[key] = got
        else:
            out[key] = val
    return out


def _request(test_client, url, method, **kwargs):
    """One place that turns ('GET'|'POST', url) into a response, so the tables
    can carry a method string."""
    if method == 'POST':
        return test_client.post(url, **kwargs)
    return test_client.get(url, **kwargs)


# --------------------------------------------------------------------------- #
# Fixtures for the rows these tables address.
#
# NOTE ON THE FIXTURE HAZARD (see the module docstring): none of the fixtures
# below touch `client`. They depend on `db` only. That is what lets a refusal
# test and its full-admin control share the same row fixtures while still
# using exactly ONE role client each, in their own separate test functions.
# --------------------------------------------------------------------------- #

@pytest.fixture
def ordinary_page(db):
    """A real, ordinary page for the two editor surfaces in the reach table.

    The slug is asserted to be outside both the reserved set and the home
    content-block set, so a Site Editor reaching the editor for it is proof
    about the ROLE gate and not an accident of the row happening to be
    ordinary. It carries a real draft document so /state has something to
    return rather than falling into its converter fallback path."""
    from app.admin_panel.routes.public_site import _RESERVED_SLUGS, _is_block_slug
    slug = 'rb-reach-ordinary-page'
    assert slug not in _RESERVED_SLUGS, 'reach-table page must not be a reserved slug'
    assert not _is_block_slug(slug), 'reach-table page must not be a home content block'
    page = db.session.query(SitePage).filter_by(slug=slug).first()
    if not page:
        page = SitePage(slug=slug, title='Reach table page', status='draft',
                        sections_draft=_DOC)
        db.session.add(page)
    db.session.commit()
    return page


@pytest.fixture
def admin_only_rows(db):
    """Real rows for the id-taking full-admin endpoints.

    Both the refusal test and its control need these. Without them the
    control's endpoints would act on a missing row: submissions/read would
    still 302 (it no-ops on a missing id) but redirects/delete's behaviour and
    any future tightening would be untested, and — worse — a 404 from a
    missing row would be indistinguishable from a 404 caused by a route that
    no longer exists."""
    from app.models import RedirectRule, FormSubmission
    rule = RedirectRule(source_path='/rb-audit-source', target_path='/rb-audit-target')
    sub = FormSubmission(form_name='contact',
                         data_json='{"name": "A Visitor", "email": "v@example.com"}',
                         source_page='/contact')
    db.session.add(rule)
    db.session.add(sub)
    db.session.commit()
    return {'redirect_rule_id': rule.id, 'submission_id': sub.id}


def _make_block_revision(db, page_id):
    """A revision row bound to the block page, for the revision-restore
    entry in the page-id table (that route takes rev_id alongside page_id and
    404s unless the revision genuinely belongs to the page — so a fabricated
    id would produce the right status code for the wrong reason)."""
    from app.models import SitePageRevision
    rev = SitePageRevision(page_id=page_id, title='Home hero (an earlier version)',
                           sections=_DOC, kind='publish')
    db.session.add(rev)
    db.session.commit()
    return rev.id


# --------------------------------------------------------------------------- #
# TABLE 1 — the reach table.
# Every surface the Site Editor role is intended to have.
# --------------------------------------------------------------------------- #

_REACH_SURFACES = [
    ('admin_panel.public_site_hub', {}),               # Website hub
    ('admin_panel.public_site_pages', {}),             # Pages list
    ('admin_panel.public_site_page_new', {}),          # Add New Page picker
    ('admin_panel.public_site_news', {}),              # Posts list
    ('admin_panel.public_site_news_new', {}),          # New post
    ('admin_panel.public_site_faqs', {}),              # FAQs
    ('admin_panel.public_site_media', {}),             # Media library
    ('admin_panel.public_site_media_list', {}),        # Media library JSON
    ('admin_panel.public_site_menu', {}),              # Menu editor — D-02
    ('admin_panel.site_editor_home', {}),              # Home shortcut (302s)
    ('admin_panel.site_editor', {'page_id': _ORDINARY_PAGE_ID}),        # editor shell
    ('admin_panel.site_editor_state', {'page_id': _ORDINARY_PAGE_ID}),  # editor state
]


class TestSiteEditorReachTable:
    """Criterion: every surface a Site Editor is supposed to have, asserted
    reachable by a real Site Editor session, one parametrized case each so a
    failure names the offending endpoint rather than a bare status mismatch."""

    @pytest.mark.parametrize('endpoint,url_kwargs', _REACH_SURFACES,
                             ids=[e for e, _ in _REACH_SURFACES])
    def test_site_editor_reaches_surface(self, app, db, site_editor_client,
                                         ordinary_page, endpoint, url_kwargs):
        url = _url(app, endpoint, **_resolve(url_kwargs, ordinary_page_id=ordinary_page.id))
        r = site_editor_client.get(url)
        # 302 counts as reaching: site_editor_home resolves the home slug and
        # forwards into the editor. What must never happen is a refusal.
        assert r.status_code not in (401, 403), (
            f'the Site Editor was REFUSED {endpoint} ({url}) with '
            f'{r.status_code} — this is a surface the role is supposed to have')
        assert r.status_code in (200, 302), (
            f'{endpoint} ({url}) answered {r.status_code}; the reach table '
            f'expects a rendered page or a redirect, so this is a broken '
            f'surface rather than an authorization result')


class TestMenuReachableRationaleD02:
    def test_d02_menu_editor_is_reachable_by_a_site_editor(self, app, db, site_editor_client):
        """D-02: the Menu editor stays open to the Site Editor role.

        A volunteer who adds a page almost always needs it in the nav, and
        the off-site-link risk that would otherwise argue for locking this
        down is already closed at the other end — is_safe_link_url() was
        hardened on 2026-08-19 to reject protocol-relative URLs. Pinned by a
        test so a later consolidation that reads Menu as 'configuration, like
        Appearance' has to argue with a red suite rather than a stale doc.
        """
        url = _url(app, 'admin_panel.public_site_menu')
        r = site_editor_client.get(url)
        assert r.status_code == 200, r.get_data(as_text=True)


class TestAnonymousBaselineMakesThisModuleNonVacuous:
    """This test exists to make every other assertion in the module mean
    something. If authentication were somehow bypassed in the test app — a
    LOGIN_DISABLED config, a login_manager that silently authenticates
    everyone — then every 'reaches' assertion above would pass for a request
    that carried no identity at all, and every '403' assertion would be the
    only thing still working. Proving that an anonymous client is NOT served
    an authoring surface proves the role fixtures are doing real work.
    Do not delete this as trivial."""

    def test_anonymous_client_is_not_served_the_pages_list(self, app, db, client):
        # A bare, never-logged-in `client`. Do NOT also request a role client
        # here — they wrap this same instance and share its cookie jar.
        url = _url(app, 'admin_panel.public_site_pages')
        r = client.get(url)
        assert r.status_code != 200, (
            'an anonymous request was served the Pages list — authentication '
            'is not in effect, so every other assertion in this module is '
            'vacuous')
        if r.status_code in (301, 302):
            assert 'login' in r.headers.get('Location', '').lower(), (
                f'anonymous redirect went to {r.headers.get("Location")!r} '
                f'rather than the login view')
        else:
            assert r.status_code in (401, 403), r.status_code


# --------------------------------------------------------------------------- #
# TABLE 2 — the refusal table, and its controls.
#
# All eight full-admin surfaces. Appearance was the only one of these with any
# coverage before this plan; Redirects — named in the same breath as
# Appearance by the roadmap's criterion 3 — had none at all, and Submissions
# only became full-admin in plan 04-01 (D-01).
# --------------------------------------------------------------------------- #

_ADMIN_ONLY_SURFACES = [
    ('admin_panel.public_site_appearance', 'GET', {}),
    ('admin_panel.public_site_appearance_save', 'POST', {}),
    ('admin_panel.public_site_redirects', 'GET', {}),
    ('admin_panel.public_site_redirects_save', 'POST', {}),
    ('admin_panel.public_site_redirects_delete', 'POST', {'rule_id': _REDIRECT_RULE_ID}),
    ('admin_panel.public_site_submissions', 'GET', {}),
    ('admin_panel.public_site_submission_read', 'POST', {'sub_id': _SUBMISSION_ID}),
    ('admin_panel.public_site_submission_delete', 'POST', {'sub_id': _SUBMISSION_ID}),
]

# Minimal VALID bodies for the control test's POSTs. The refusal test never
# needs these — @role_required aborts before the view body reads the form —
# but the control must get past the view's own validation, otherwise a 500
# would be reported as 'not 403' and the control would prove nothing about
# reachability. CSRF is off under the test config (WTF_CSRF_ENABLED=False),
# so no token plumbing is required or wanted here.
_CONTROL_BODIES = {
    'admin_panel.public_site_appearance_save': {
        'title': 'ECS Pub League', 'primary_hex': '#00A651',
        'accent_hex': '#0D6EFD', 'font_pair': 'modern',
        'hero_overlay': 'medium', 'hero_focal': '50% 50%',
        'ecs_member_login_url': '{shop}/wp-login.php?redirect_to={redirect}',
    },
    'admin_panel.public_site_redirects_save': {
        'source_path': '/rb-audit-control-source',
        'target_path': '/rb-audit-control-target',
    },
}

_ADMIN_ONLY_IDS = [f'{e}:{m}' for e, m, _ in _ADMIN_ONLY_SURFACES]


class TestSiteEditorRefusalTable:
    @pytest.mark.parametrize('endpoint,method,url_kwargs', _ADMIN_ONLY_SURFACES,
                             ids=_ADMIN_ONLY_IDS)
    def test_site_editor_is_refused_full_admin_surface(
            self, app, db, site_editor_client, admin_only_rows,
            endpoint, method, url_kwargs):
        """Exactly 403 — not merely 'not 200'.

        A redirect to login also satisfies 'not 200', and it would mean the
        session was never established: precisely the wrong-reason pass this
        module exists to prevent. The paired control in
        TestFullAdminReachesEveryRefusedSurfaceControl proves the 403 is about
        the ROLE rather than about a typo, a missing row or a dead route."""
        url = _url(app, endpoint, **_resolve(url_kwargs, **admin_only_rows))
        r = _request(site_editor_client, url, method)
        assert r.status_code == 403, (
            f'{endpoint} ({method} {url}) answered {r.status_code} for a Site '
            f'Editor; this surface is full-admin only and must answer 403')


# THIS CLASS IS NOT REDUNDANT WITH THE ONE ABOVE — do not delete it.
#
# `assert status_code == 403` on its own proves almost nothing about
# authorization. It also passes when the route was replaced by something else
# that 403s, and it passes when the role fixture silently failed to establish
# a session so an anonymous request was refused. Running the SAME table as a
# full admin, in SEPARATE test functions with a SEPARATE fixture, is what
# converts each 403 into evidence: it proves the endpoint exists, is spelled
# correctly, has real rows to act on, and is refusing on the basis of role.
#
# Separate functions, not a second client in the same body: `gadmin_client`
# and `site_editor_client` wrap ONE `app.test_client()` and share its cookie
# jar (see the module docstring), so requesting both in one test would make
# the second login overwrite the first.
class TestFullAdminReachesEveryRefusedSurfaceControl:
    @pytest.mark.parametrize('endpoint,method,url_kwargs', _ADMIN_ONLY_SURFACES,
                             ids=_ADMIN_ONLY_IDS)
    def test_full_admin_is_not_refused_full_admin_surface(
            self, app, db, gadmin_client, admin_only_rows,
            endpoint, method, url_kwargs):
        url = _url(app, endpoint, **_resolve(url_kwargs, **admin_only_rows))
        body = _CONTROL_BODIES.get(endpoint)
        r = _request(gadmin_client, url, method, **({'data': body} if body else {}))
        assert r.status_code != 403, (
            f'{endpoint} ({method} {url}) refused a GLOBAL ADMIN with 403 — so '
            f'the matching Site Editor 403 is NOT evidence of a role boundary, '
            f'it is evidence that nobody can reach this endpoint')
        assert r.status_code in (200, 302), (
            f'{endpoint} ({method} {url}) answered {r.status_code} for a full '
            f'admin; the control expects a rendered page or a redirect')


class TestSubmissionsRationaleD01:
    """D-01, recorded where a future reader will actually look.

    The Submissions inbox holds names, email addresses and message bodies
    supplied by members of the public through the Form widget. That puts it in
    the same sensitivity class as Appearance and Redirects — configuration and
    PII — rather than with the authored content a Site Editor is trusted to
    manage. Plan 04-01 moved it onto the full-admin role list; these two tests
    are what stop a later 'the three Submissions routes are content surfaces
    like the rest' consolidation from quietly moving it back.

    Two tests, two fixtures, one role each — never both in one body."""

    def test_d01_submissions_inbox_is_refused_to_a_site_editor(
            self, app, db, site_editor_client):
        url = _url(app, 'admin_panel.public_site_submissions')
        r = site_editor_client.get(url)
        assert r.status_code == 403, r.get_data(as_text=True)

    def test_d01_submissions_inbox_is_reachable_by_a_full_admin_control(
            self, app, db, gadmin_client):
        # The control for the test above. Without it, that 403 could equally
        # be a route that stopped existing.
        url = _url(app, 'admin_panel.public_site_submissions')
        r = gadmin_client.get(url)
        assert r.status_code == 200, r.get_data(as_text=True)


# --------------------------------------------------------------------------- #
# TABLE 3 — every route that accepts a client-supplied page id, and the
# completeness gate that keeps the table honest.
# --------------------------------------------------------------------------- #

_PAGE_ID_ROUTES = {
    # Single-item Pages-list actions
    'admin_panel.public_site_page_trash': ('POST', {}),
    'admin_panel.public_site_page_restore': ('POST', {}),
    'admin_panel.public_site_page_delete': ('POST', {}),
    'admin_panel.public_site_page_publish': ('POST', {}),
    'admin_panel.public_site_page_duplicate': ('POST', {}),
    # Revisions
    'admin_panel.public_site_page_revisions': ('GET', {}),
    'admin_panel.public_site_page_revision_restore': (
        'POST', {'rev_id': _BLOCK_REVISION_ID}),
    # The retired settings screen (now a 302 into the editor) and Quick Edit
    'admin_panel.public_site_page_edit': ('GET', {}),
    'admin_panel.public_site_page_quick_edit': ('POST', {}),
    # The whole site-editor surface
    'admin_panel.site_editor': ('GET', {}),
    'admin_panel.site_editor_state': ('GET', {}),
    'admin_panel.site_editor_draft': ('POST', {}),
    'admin_panel.site_editor_render_section': ('POST', {}),
    'admin_panel.site_editor_page_settings': ('POST', {}),
    'admin_panel.site_editor_publish': ('POST', {}),
    'admin_panel.site_editor_lock': ('POST', {}),
    'admin_panel.site_editor_unlock': ('POST', {}),
}
# (`_SINGLE_ITEM_BLOCK_ROUTES` further up is plan 04-01's original path-literal
# list. It is a strict subset of this mapping and is left in place rather than
# rewritten — its three tests exercise the literal URL form, which is a
# genuinely different failure mode from url_for resolution. `_PAGE_ID_ROUTES`
# is the AUDITED SET the completeness gate compares against the url_map; the
# older list is not, and must not be extended.)

# `site_editor_unlock` is the one audited endpoint that does NOT run the
# shared row fetch: its body calls release_edit_lock(page_id, user_id)
# directly and never touches _get_page. Discovered while writing this table.
# Deliberately REPORTED, not patched — plan 04-03 is test-only and the fix is
# application code (see 04-03-SUMMARY.md "Deferred / reported"). It is low
# severity: release_edit_lock only deletes the Redis key when the caller
# already HOLDS the lock, and the acquire side (site_editor_lock) IS guarded,
# so a Site Editor can never hold a block page's lock in the first place; the
# SitePage row itself is never read or written. It gets its own test below,
# which asserts the property that actually matters — the row is untouched.
# CLOSED 2026-08-20. site_editor_unlock now calls _get_page(page_id) before
# release_edit_lock, so every one of the 17 page-id routes goes through the
# shared fetch and this set is empty. Keep it empty. The test below asserts
# that, because an exemption set is exactly how a closed vulnerability class
# quietly re-opens: one plausible-looking entry at a time, each individually
# defensible. If you genuinely need to add one, you are changing the invariant
# "every client-supplied page id is resolved through the shared fetch" — say so
# out loud in review rather than editing this line.
_NO_ROW_FETCH_EXEMPT = set()


class TestTheExemptionSetStaysEmpty:
    def test_no_page_id_route_is_exempt_from_the_shared_fetch(self):
        assert _NO_ROW_FETCH_EXEMPT == set(), (
            'A page-id route has been exempted from the block-slug guard: '
            f'{sorted(_NO_ROW_FETCH_EXEMPT)}. Every entry here is a route that '
            'accepts a client-supplied page id and does NOT resolve it through '
            '_get_real_page / _get_page — which is the CR-01 vulnerability '
            'class plan 04-01 closed. Adding an entry is not a test fix; it is '
            'a decision to reopen a hole. Guard the route instead.')

_GUARDED_PAGE_ID_ROUTES = [e for e in sorted(_PAGE_ID_ROUTES)
                           if e not in _NO_ROW_FETCH_EXEMPT]


class TestEveryPageIdRouteRefusesABlockRow:
    @pytest.mark.parametrize('endpoint', _GUARDED_PAGE_ID_ROUTES,
                             ids=_GUARDED_PAGE_ID_ROUTES)
    def test_page_id_route_refuses_a_block_row_and_leaves_it_untouched(
            self, app, db, site_editor_client, endpoint):
        blk = _make_block(db)
        blk_id = blk.id
        before = (blk.slug, blk.title, blk.status, blk.deleted_at)
        method, extra = _PAGE_ID_ROUTES[endpoint]
        rev_id = None
        if any(isinstance(v, _RuntimeId) and v is _BLOCK_REVISION_ID
               for v in extra.values()):
            rev_id = _make_block_revision(db, blk_id)
        url = _url(app, endpoint, page_id=blk_id,
                   **_resolve(extra, block_revision_id=rev_id))
        r = _request(site_editor_client, url, method,
                     **({'json': {}} if method == 'POST' else {}))
        assert r.status_code == 404, (
            f'{endpoint} ({method} {url}) answered {r.status_code} for a home '
            f'content-block id; every page-id route must treat a block row as '
            f'not found — see _get_real_page()')
        # Status code alone is not enough: a route could mutate the row and
        # only then decide to refuse. Re-read and compare.
        db.session.expire_all()
        still = db.session.query(SitePage).get(blk_id)
        assert still is not None, (
            f'{endpoint} deleted the block row outright before refusing')
        assert (still.slug, still.title, still.status, still.deleted_at) == before, (
            f'{endpoint} MUTATED the block row before answering 404 — '
            f'was {before!r}, now '
            f'{(still.slug, still.title, still.status, still.deleted_at)!r}')


class TestUnlockIsTheOneAuditedRouteWithoutTheRowFetch:
    def test_unlock_of_a_block_row_leaves_the_row_untouched_known_gap(
            self, app, db, site_editor_client):
        """KNOWN GAP, reported rather than patched (this plan is test-only).

        site_editor_unlock never calls _get_page, so unlike its sixteen
        siblings it does not answer 404 for a home content-block id. Recorded
        here explicitly instead of being silently dropped from the table, so
        the suite is honest about the gap rather than green by omission.

        GUARD ADDED 2026-08-20 — the endpoint has been removed from
        _NO_ROW_FETCH_EXEMPT and is now covered by the main parametrized guard
        above as well. This test is deliberately KEPT rather than deleted: it is
        the one that asserts the row is untouched, which the status-code
        assertion alone does not prove. Its tolerance of 200-or-404 is retained
        on purpose so it documents both the old and the current behaviour."""
        blk = _make_block(db)
        blk_id = blk.id
        before = (blk.slug, blk.title, blk.status, blk.deleted_at)
        url = _url(app, 'admin_panel.site_editor_unlock', page_id=blk_id)
        r = site_editor_client.post(url, json={})
        assert r.status_code in (200, 404), (
            f'unlock answered {r.status_code}; expected either the current '
            f'un-guarded 200 or the guarded 404')
        db.session.expire_all()
        still = db.session.query(SitePage).get(blk_id)
        assert still is not None
        assert (still.slug, still.title, still.status, still.deleted_at) == before, (
            'unlock touched the SitePage row — that would raise this from a '
            'consistency gap to a real block-row mutation path')


# The completeness gate.
#
# KNOWN MAP-INVISIBLE CASE — read this before concluding the gate covers
# everything that accepts a page id. `admin_panel.public_site_page_save` reads
# its id from the POST FORM BODY (`request.form.get('id')`), not from the URL,
# so it carries no page_id argument and this gate will never see it. It has
# its own dedicated test in TestTheOneMapInvisiblePageIdRoute below (and in
# plan 04-01's TestPageSaveFormBodyRefusesBlockSlug). If another route is ever
# written that takes an id from a body, it needs the same treatment — the gate
# cannot find it for you.
class TestPageIdRouteCompletenessGate:
    def test_audited_page_id_routes_equal_the_live_url_map(self, app):
        with app.app_context():
            public_prefix = url_for('admin_panel.public_site_hub', _external=False)
            editor_prefix = url_for('admin_panel.site_editor_home',
                                    _external=False).rsplit('/', 1)[0]
            live = {
                rule.endpoint
                for rule in app.url_map.iter_rules()
                if 'page_id' in rule.arguments
                and (rule.rule.startswith(public_prefix)
                     or rule.rule.startswith(editor_prefix))
            }
        assert live, (
            f'the url_map scan found NO page-id routes under {public_prefix!r} '
            f'or {editor_prefix!r} — the gate is scanning the wrong thing and '
            f'would pass no matter what anyone adds')

        audited = set(_PAGE_ID_ROUTES)
        unaudited = live - audited
        stale = audited - live

        assert not unaudited, (
            'These routes accept a client-supplied page id but are NOT in '
            f'_PAGE_ID_ROUTES: {sorted(unaudited)}. This is the vulnerability '
            'class plan 04-01 closed (CR-01) re-opening. Do one of two things: '
            '(1) add the endpoint to _PAGE_ID_ROUTES with its method and any '
            'extra url kwargs, and confirm it refuses a home content-block id '
            'with 404 via _get_real_page / _get_page; or (2) if it is '
            'genuinely exempt, say so in a comment here explaining why a block '
            'row reaching it is harmless.')
        assert not stale, (
            f'These endpoints are audited but no longer exist in the url_map: '
            f'{sorted(stale)}. A renamed or deleted route leaves a table entry '
            f'asserting nothing. Remove or rename the entry.')
        # Equality in BOTH directions, stated once more as the actual contract.
        assert live == audited


class TestTheOneMapInvisiblePageIdRoute:
    """`public_site_page_save` takes its page id from the form body, so it is
    structurally invisible to the completeness gate above. Its guard therefore
    needs its own test, and the gate needs the comment above it saying so."""

    def test_page_save_carries_no_page_id_url_argument(self, app):
        # Proves the premise of the comment above the gate, rather than
        # asking the next reader to take it on trust.
        with app.app_context():
            rules = [r for r in app.url_map.iter_rules()
                     if r.endpoint == 'admin_panel.public_site_page_save']
        assert rules, 'admin_panel.public_site_page_save is not registered'
        for rule in rules:
            assert 'page_id' not in rule.arguments, (
                'public_site_page_save now takes page_id in the URL — it is no '
                'longer map-invisible, so add it to _PAGE_ID_ROUTES and delete '
                'this test and the KNOWN MAP-INVISIBLE CASE comment')

    def test_site_editor_form_body_id_cannot_write_to_a_block_row(
            self, app, db, site_editor_client):
        blk = _make_block(db)
        blk.status = 'draft'
        db.session.commit()
        blk_id = blk.id
        before_title, before_status = blk.title, blk.status
        url = _url(app, 'admin_panel.public_site_page_save')
        site_editor_client.post(url, data={'id': str(blk_id),
                                           'title': 'pwned-via-form-body',
                                           'status': 'published'})
        db.session.expire_all()
        still = db.session.query(SitePage).get(blk_id)
        assert still.title == before_title, (
            'the form-body id fell through to a successful title write on a '
            'home content block')
        assert still.status == before_status, (
            'the form-body id fell through to a successful publish on a home '
            'content block')
