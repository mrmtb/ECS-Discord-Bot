"""Locks PSB-07 — one editor for every page, Home included, no second surface.

Research (Phase 3, .planning/phases/03-one-editor-familiar-chrome/03-RESEARCH.md)
established with file-level evidence that this requirement was ALREADY TRUE when
this phase was planned: `site_editor(page_id)` is the only route that renders
section-JSON content for editing, Home is an ordinary `SitePage` row (its slug
is not in `_BLOCK_SLUGS`) so it appears in the Pages list like any other page,
`site_editor_home()` is a pure redirect INTO that same route, and
`SitePage.body_html` is written by exactly one live route
(`public_site_page_revision_restore`, the legacy-revision-restore fallback).
Plan 03-01 additionally retired the standalone page-settings screen
(`page_edit_flowbite.html`) into a 302 redirect into the editor.

This module exists to keep all of that true, not to prove new work. It writes
no application code (see 03-04-PLAN.md's explicit non-goal).
"""

import re
import os

import pytest

from app.models import SitePage


# --------------------------------------------------------------------------- #
# fixtures — mirrors tests/test_ph_editor_shell.py
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


_DOC = {'v': 1, 'sections': [
    {'id': 's1', 'type': 'content', 'theme': 'inherit', 'settings': {},
     'blocks': [{'id': 'b1', 'type': 'heading', 'level': 2, 'html': 'Hi there'}]}]}


def _make_section_page(db, slug, **overrides):
    """A page whose content model is the section document (the normal case)."""
    kwargs = dict(slug=slug, title=f'Page {slug}', status='published',
                  sections_draft=_DOC, sections_published=_DOC)
    kwargs.update(overrides)
    p = SitePage(**kwargs)
    db.session.add(p)
    db.session.commit()
    return p


def _make_legacy_body_html_page(db, slug):
    """A page that still carries a recognizable legacy body_html blob, so a
    test can watch it stay untouched through a real draft+publish cycle."""
    p = SitePage(slug=slug, title=f'Legacy {slug}', status='draft',
                 body_html='<p>LEGACY-BLOB-DO-NOT-TOUCH</p>',
                 sections_draft={'v': 1, 'sections': []}, draft_rev=0)
    db.session.add(p)
    db.session.commit()
    return p


def _table_html(resp):
    """Return only the <table>...</table> slice of a response body, so a
    markup assertion is scoped to the Pages table and can never pass by
    accident via a sidebar/nav link. Mirrors _footer_html() in
    tests/test_ph_footer_menu.py."""
    body = resp.get_data(as_text=True)
    match = re.search(r'<table.*?</table>', body, re.DOTALL)
    assert match is not None, 'no <table>...</table> block found in response body'
    return match.group(0)


class TestHomeIsAnOrdinaryPage:
    def test_home_row_edit_control_uses_same_editor_route_as_any_page(self, app, db, gadmin_client):
        """Half 1 of criterion 1: Home is not special-cased in the Pages list."""
        home = _make_section_page(db, 'home')
        other = _make_section_page(db, 'some-other-page')

        r = gadmin_client.get('/admin-panel/public-site/pages')
        assert r.status_code == 200, (r.status_code, r.get_data(as_text=True)[:400])
        table = _table_html(r)

        assert home.title in table, 'Home should be an ordinary row in the Pages table'
        assert other.title in table

        home_edit_href = f'/admin-panel/site-editor/{home.id}'
        other_edit_href = f'/admin-panel/site-editor/{other.id}'
        assert home_edit_href in table, \
            "Home's Edit control must point at the same site-editor route shape every other row uses"
        assert other_edit_href in table

        # Neither row's Edit control points at any kind of separate/simple
        # editing surface for Home specifically.
        assert '/admin-panel/site-editor/home-edit' not in table
        assert 'simple-editor' not in table.lower()

    def test_home_convenience_url_is_a_redirect_not_a_surface(self, app, db, gadmin_client):
        """Half 2 of criterion 1: /site-editor/home is a convenience entry
        INTO the one editor, not a second editing surface."""
        home = _make_section_page(db, 'home')

        r = gadmin_client.get('/admin-panel/site-editor/home', follow_redirects=False)
        assert r.status_code == 302, (r.status_code, r.get_data(as_text=True)[:400])
        assert r.headers['Location'].rstrip('/').endswith(f'/admin-panel/site-editor/{home.id}')


class TestNoSecondSurface:
    def test_retired_settings_route_redirects_into_the_editor(self, app, db, gadmin_client):
        """The old standalone page-settings screen must not render (200) and
        must not 404 — a stale bookmark has to land somewhere useful (D-02)."""
        page = _make_section_page(db, 'redirect-target-page')

        r = gadmin_client.get(f'/admin-panel/public-site/pages/{page.id}/edit',
                              follow_redirects=False)
        assert r.status_code == 302, \
            f'expected a redirect into the editor, got {r.status_code}: {r.get_data(as_text=True)[:400]}'
        location = r.headers['Location']
        assert f'/admin-panel/site-editor/{page.id}' in location, \
            f'redirect must land on the editor for THIS page id, got {location!r}'

    def test_pages_list_and_editor_shell_serve_no_body_html_form_control(self, app, db, gadmin_client):
        """No second content-editing surface anywhere in the Pages templates.
        Deliberately NOT asserted against Posts/FAQs, which keep their own
        body_html/TinyMCE editors (out of PSB-07's Pages-only scope)."""
        page = _make_section_page(db, 'no-blob-editor-page')

        pages_list = gadmin_client.get('/admin-panel/public-site/pages')
        assert pages_list.status_code == 200
        assert 'body_html' not in pages_list.get_data(as_text=True), \
            'the Pages list must not expose a body_html form control'

        editor = gadmin_client.get(f'/admin-panel/site-editor/{page.id}')
        assert editor.status_code == 200
        assert 'body_html' not in editor.get_data(as_text=True), \
            'the editor shell must not expose a body_html form control'


class TestRetiredColumnStaysRetired:
    def test_editor_publish_flow_never_writes_body_html(self, app, db, gadmin_client):
        """The behavioural half of the guarantee: drive a REAL draft save and
        publish through the editor endpoints and prove the legacy blob is
        untouched -- the section document is the one content model."""
        page = _make_legacy_body_html_page(db, 'legacy-blob-page')
        original_body_html = page.body_html
        assert original_body_html == '<p>LEGACY-BLOB-DO-NOT-TOUCH</p>'

        new_doc = {'v': 1, 'sections': [{
            'id': 's_new', 'type': 'content', 'theme': 'inherit', 'settings': {},
            'blocks': [{'id': 'b_new', 'type': 'heading', 'level': 2,
                       'html': 'Brand new section content'}]}]}

        r1 = gadmin_client.post(f'/admin-panel/site-editor/{page.id}/draft',
                                json={'doc': new_doc, 'base_rev': 0})
        assert r1.status_code == 200, r1.get_data(as_text=True)
        d1 = r1.get_json()
        assert d1['success'] and d1['draft_rev'] == 1

        r2 = gadmin_client.post(f'/admin-panel/site-editor/{page.id}/publish',
                                json={'base_rev': 1})
        assert r2.status_code == 200, r2.get_data(as_text=True)

        db.session.expire_all()
        refreshed = db.session.get(SitePage, page.id)
        assert refreshed.status == 'published'
        assert refreshed.sections_published['sections'][0]['blocks'][0]['html'] == \
            'Brand new section content'
        assert refreshed.body_html == original_body_html, \
            'the editor must never write body_html — that would create a second content model'


class TestSingleBodyHtmlWriteSite:
    def test_exactly_one_sitepage_body_html_assignment_across_the_editor_routes(self):
        """Source-level guarantee: exactly one line across the two route files
        assigns a SitePage's body_html, and it must be inside
        public_site_page_revision_restore -- the legacy revision-restore
        fallback, not a live editing path. A second write site would be a
        second content model wearing the same UI (T-03-20)."""
        here = os.path.dirname(os.path.abspath(__file__))
        repo_root = os.path.dirname(here)
        files = [
            os.path.join(repo_root, 'app', 'admin_panel', 'routes', 'public_site.py'),
            os.path.join(repo_root, 'app', 'admin_panel', 'routes', 'site_editor.py'),
        ]

        # Scope to page-typed variables (page/pg/copy-of-a-page assigned via
        # dot-attribute), NOT NewsPost's own `post.body_html = ...` write in
        # the same file, and NOT a `SitePage(..., body_html=..., ...)`
        # constructor kwarg (a different write pattern entirely -- this test
        # is specifically about live dot-attribute assignment paths).
        assignment_pat = re.compile(r'\bpage\w*\.body_html\s*=(?!=)')

        matches = []
        for path in files:
            assert os.path.isfile(path), f'expected route file missing: {path}'
            with open(path, encoding='utf-8') as f:
                lines = f.readlines()
            for lineno, line in enumerate(lines, start=1):
                if assignment_pat.search(line):
                    matches.append((path, lineno, line.strip()))

        assert len(matches) == 1, (
            "PSB-07's guarantee is that the section document is the one content "
            "model; a second SitePage.body_html write site would be a second "
            f"content model wearing the same UI. Found {len(matches)}: {matches}"
        )

        path, lineno, _line = matches[0]
        assert path.endswith('public_site.py'), \
            f'the one write site must live in public_site.py, found it in {path}'

        # Confirm the matching line falls inside public_site_page_revision_restore
        # by scanning backward from the match to the nearest preceding `def `.
        with open(path, encoding='utf-8') as f:
            all_lines = f.readlines()
        enclosing_def = None
        for i in range(lineno - 1, -1, -1):
            m = re.match(r'def (\w+)\(', all_lines[i])
            if m:
                enclosing_def = m.group(1)
                break
        assert enclosing_def == 'public_site_page_revision_restore', (
            f'the sole body_html write site must be inside '
            f'public_site_page_revision_restore, found it inside {enclosing_def!r} '
            f'at {path}:{lineno}'
        )
