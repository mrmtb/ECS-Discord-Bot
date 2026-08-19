# tests/test_ph_footer_menu.py

"""
Footer-menu wiring regression lock (Phase 2, Plan 01).

AREA: the public-site footer's "Explore" column must be driven by the same
single AdminConfig('public_nav_menu') key that already drives the desktop nav
(base_public.html:135) and the mobile nav (base_public.html:198), via
`_nav_items()`. Before this plan the footer was five hardcoded `url_for()`
links (base_public.html:232-238 pre-fix) that no menu edit could ever reach —
this is why success criterion 4 ("desktop nav, mobile nav, and the footer all
reflect it") failed. This module is the untested path where that gap lived.

Every assertion in this module is scoped to the `<footer>...</footer>` slice
of the response body via `_footer_html()`, so a match in the header nav (which
also renders `nav_items`) can never be mistaken for a footer match.

Runs against the conftest app (SQLite in-memory + mocked Redis). Public routes
are mounted at /preview/*. Mirrors the fixture style of
tests/test_ph_forms_drafts.py.
"""

import json
import re

import pytest


def _footer_html(resp):
    """Return only the <footer>...</footer> slice of a response body, so every
    assertion in this module is footer-region-scoped and can never accidentally
    match the header nav (which also loops nav_items)."""
    body = resp.data.decode('utf-8', 'ignore')
    match = re.search(r'<footer.*?</footer>', body, re.DOTALL)
    assert match is not None, 'no <footer>...</footer> block found in response body'
    return match.group(0)


def _set_nav_menu(db, menu):
    """Seed/replace the AdminConfig('public_nav_menu') row directly via
    db.session, mirroring test_ph_forms_drafts.py's _stored_nav_menu-adjacent
    seeding pattern (query existing row, update in place, else add one)."""
    from app.models.admin_config import AdminConfig
    row = db.session.query(AdminConfig).filter_by(key='public_nav_menu').first()
    if row:
        row.value = json.dumps(menu)
        row.data_type = 'json'
        row.is_enabled = True
    else:
        db.session.add(AdminConfig(
            key='public_nav_menu', value=json.dumps(menu),
            data_type='json', category='public_site', is_enabled=True))
    db.session.commit()


# --------------------------------------------------------------------------- #
# Task 1 — the thin end-to-end slice: AdminConfig -> _nav_items() ->
# _inject_public_context() -> the footer block -> the HTML actually served.
# --------------------------------------------------------------------------- #

class TestFooterReflectsNavMenu:
    def test_custom_link_added_via_menu_appears_in_footer(self, client, db):
        """An admin-added kind='url' item with a distinctive label and a
        relative href must appear in the footer's Explore column. This is the
        core wiring assertion: before the fix, the footer's <ul> was five
        hardcoded url_for() links and could never contain this label."""
        menu = [
            {'kind': 'url', 'value': '/distinctive-footer-target',
             'label': 'DistinctiveFooterLinkXYZ', 'visible': True},
        ]
        _set_nav_menu(db, menu)

        resp = client.get('/preview/about')
        assert resp.status_code == 200, resp.data
        footer = _footer_html(resp)

        assert 'DistinctiveFooterLinkXYZ' in footer, \
            f'admin-added menu label missing from footer: {footer!r}'
        assert '/distinctive-footer-target' in footer, \
            f'admin-added menu href missing from footer: {footer!r}'

    def test_no_adminconfig_row_falls_back_to_default_nav_in_footer(self, app, client, db):
        """With no AdminConfig row at all, the page must still 200 (not 500)
        and the footer must contain one link per entry _nav_items() returns —
        proving the footer reuses the exact same resolver as the header nav,
        not a second/parallel default."""
        from app.models.admin_config import AdminConfig
        db.session.query(AdminConfig).filter_by(key='public_nav_menu').delete()
        db.session.commit()

        resp = client.get('/preview/about')
        assert resp.status_code == 200, resp.data
        footer = _footer_html(resp)

        with app.test_request_context():
            from app.public_site import _nav_items
            items = _nav_items()

        assert items, 'expected _DEFAULT_NAV fallback to produce at least one item'
        for item in items:
            assert item['label'] in footer, \
                f"_nav_items() entry {item['label']!r} missing from footer: {footer!r}"
            assert item['url'] in footer, \
                f"_nav_items() entry url {item['url']!r} missing from footer: {footer!r}"


# --------------------------------------------------------------------------- #
# Task 2 — the full menu-edit contract (criterion 4): add / reorder / hide /
# add-page / dropdown-children-excluded / stored-XSS, every assertion scoped
# to the <footer> slice.
# --------------------------------------------------------------------------- #

class TestFooterMenuEditContract:
    def test_hidden_item_excluded_visible_sibling_included(self, client, db):
        menu = [
            {'kind': 'url', 'value': '/hidden-target', 'label': 'HiddenLinkXYZ',
             'visible': False},
            {'kind': 'url', 'value': '/visible-target', 'label': 'VisibleLinkXYZ',
             'visible': True},
        ]
        _set_nav_menu(db, menu)

        resp = client.get('/preview/about')
        assert resp.status_code == 200, resp.data
        footer = _footer_html(resp)

        assert 'HiddenLinkXYZ' not in footer, \
            f'visible:False item leaked into footer: {footer!r}'
        assert 'VisibleLinkXYZ' in footer, \
            f'visible:True sibling missing from footer: {footer!r}'

    def test_reorder_changes_footer_link_order(self, client, db):
        menu = [
            {'kind': 'url', 'value': '/reorder-a', 'label': 'ReorderAlphaXYZ', 'visible': True},
            {'kind': 'url', 'value': '/reorder-b', 'label': 'ReorderBravoXYZ', 'visible': True},
            {'kind': 'url', 'value': '/reorder-c', 'label': 'ReorderCharlieXYZ', 'visible': True},
        ]
        _set_nav_menu(db, menu)

        resp = client.get('/preview/about')
        assert resp.status_code == 200, resp.data
        footer = _footer_html(resp)
        first_order = [footer.index('ReorderAlphaXYZ'), footer.index('ReorderBravoXYZ'),
                       footer.index('ReorderCharlieXYZ')]
        assert first_order == sorted(first_order), \
            f'expected Alpha, Bravo, Charlie order in footer: {footer!r}'

        # Reorder: Charlie, Alpha, Bravo.
        menu_reordered = [
            {'kind': 'url', 'value': '/reorder-c', 'label': 'ReorderCharlieXYZ', 'visible': True},
            {'kind': 'url', 'value': '/reorder-a', 'label': 'ReorderAlphaXYZ', 'visible': True},
            {'kind': 'url', 'value': '/reorder-b', 'label': 'ReorderBravoXYZ', 'visible': True},
        ]
        _set_nav_menu(db, menu_reordered)

        resp2 = client.get('/preview/about')
        footer2 = _footer_html(resp2)
        second_order = [footer2.index('ReorderCharlieXYZ'), footer2.index('ReorderAlphaXYZ'),
                        footer2.index('ReorderBravoXYZ')]
        assert second_order == sorted(second_order), \
            f'expected Charlie, Alpha, Bravo order in footer after reorder: {footer2!r}'

    def test_page_item_publish_gate_inherited_from_nav_items(self, client, db):
        """A kind='page' item pointing at a published SitePage renders; one
        pointing at a draft SitePage does not — proving the footer inherits
        _nav_items()'s publish gate rather than resolving pages itself."""
        from app.models import SitePage
        db.session.add(SitePage(
            slug='footer-contract-published', title='Footer Contract Published Page',
            body_html='<p>published</p>', status='published'))
        db.session.add(SitePage(
            slug='footer-contract-draft', title='Footer Contract Draft Page',
            body_html='<p>draft</p>', status='draft'))
        db.session.commit()

        menu = [
            {'kind': 'page', 'value': 'footer-contract-published',
             'label': 'FooterContractPublishedLinkXYZ', 'visible': True},
            {'kind': 'page', 'value': 'footer-contract-draft',
             'label': 'FooterContractDraftLinkXYZ', 'visible': True},
        ]
        _set_nav_menu(db, menu)

        resp = client.get('/preview/about')
        assert resp.status_code == 200, resp.data
        footer = _footer_html(resp)

        assert 'FooterContractPublishedLinkXYZ' in footer, \
            f'published page item missing from footer: {footer!r}'
        assert 'FooterContractDraftLinkXYZ' not in footer, \
            f'draft page item leaked into footer: {footer!r}'

    def test_dropdown_child_renders_in_header_but_not_footer(self, client, db):
        """A dropdown child (parent set to a top-level item's label) must
        render in the full response body (the header nav flattens/nests it)
        but must NOT appear in the footer slice — the assertion that proves
        the footer is top-level-only. Both halves are asserted in the same
        test so they cannot drift apart."""
        menu = [
            {'kind': 'url', 'value': '/dropdown-parent', 'label': 'DropdownParentXYZ',
             'visible': True},
            {'kind': 'url', 'value': '/dropdown-child', 'label': 'DropdownChildXYZ',
             'visible': True, 'parent': 'DropdownParentXYZ'},
        ]
        _set_nav_menu(db, menu)

        resp = client.get('/preview/about')
        assert resp.status_code == 200, resp.data
        full_body = resp.data.decode('utf-8', 'ignore')
        footer = _footer_html(resp)

        assert 'DropdownChildXYZ' in full_body, \
            'dropdown child should render somewhere in the page (header nav)'
        assert 'DropdownChildXYZ' not in footer, \
            f'dropdown child leaked into the top-level-only footer: {footer!r}'
        assert 'DropdownParentXYZ' in footer, \
            f'dropdown parent (top-level) missing from footer: {footer!r}'

    def test_stored_javascript_url_never_reaches_footer(self, client, db):
        """A kind='url' item whose value is a javascript: scheme, written
        directly to AdminConfig so it bypasses the save-time filter, must not
        appear in the footer slice — mirrors the header-side coverage at
        tests/test_ph_forms_drafts.py:111."""
        menu = [
            {'kind': 'url', 'value': 'javascript:alert(1)', 'label': 'StoredXSSFooterXYZ',
             'visible': True},
            {'kind': 'url', 'value': 'https://good-footer-example.test',
             'label': 'GoodFooterLinkXYZ', 'visible': True},
        ]
        _set_nav_menu(db, menu)

        resp = client.get('/preview/about')
        assert resp.status_code == 200, resp.data
        footer = _footer_html(resp)

        assert 'StoredXSSFooterXYZ' not in footer, \
            f'javascript: url item leaked into footer: {footer!r}'
        assert 'javascript:alert' not in footer.lower(), \
            f'javascript: scheme string leaked into footer: {footer!r}'
        assert 'GoodFooterLinkXYZ' in footer, \
            f'safe sibling missing from footer: {footer!r}'
