# tests/test_ph_website_hub.py

"""
Regression net for Phase 2 success criteria 1, 2, 3 and 5 (the "website hub a
volunteer recognizes"), verified as ALREADY WORKING on `master` on
2026-08-19 (see .planning/phases/02-the-website-hub-a-volunteer-recognizes/
02-RESEARCH.md). This module builds nothing — it locks behavior that already
exists so it cannot silently regress during Phases 3 through 6.

A failure in this module means a surface regressed, not that a feature is
missing. Do not "fix" a red test here by weakening the assertion; report it.

Complements (does not duplicate) tests/test_ph_footer_menu.py (footer/menu
wiring) and tests/test_ph_editor_shell.py (editor shell rendering, edit-mode
admin-bar suppression, and the admin-nav-tab-exists regression guard).

The "no legacy floating edit affordance" half of criterion 2 is enforced as a
shell source-sweep in this plan's <verify> block, not as a pytest case here —
see PLAN.md task 2.
"""

import re
from datetime import datetime

import pytest

from app.models import SitePage, NewsPost


# --------------------------------------------------------------------------- #
# Fixtures — copied in shape from tests/test_ph_editor_shell.py (deliberately
# module-local there, so duplicating here is the established pattern).
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


# The seven section endpoints criterion 1 names (hub_flowbite.html:49-60).
_HUB_SECTION_ENDPOINTS = [
    'admin_panel.public_site_pages',
    'admin_panel.public_site_news',
    'admin_panel.public_site_faqs',
    'admin_panel.public_site_media',
    'admin_panel.public_site_menu',
    'admin_panel.public_site_appearance',
    'calendar.calendar_view',
]

_DOC = {'v': 1, 'sections': [
    {'id': 's1', 'type': 'content', 'theme': 'inherit', 'settings': {},
     'blocks': [{'id': 'b1', 'type': 'heading', 'level': 2, 'html': 'Hi there'}]}]}


def _make_page(db, slug):
    """Mirrors _make_page in tests/test_ph_editor_shell.py: a published
    SitePage with both draft and published section docs populated, so it
    round-trips through the real section renderer (not a fallback path)."""
    p = SitePage(slug=slug, title='Website Hub Test', status='published',
                 sections_draft=_DOC, sections_published=_DOC)
    db.session.add(p)
    db.session.commit()
    return p


# --------------------------------------------------------------------------- #
# Task 1 — criterion 1 (one hub, one nav entry) + criterion 5 (Posts/Pages
# stay separate, Posts list carries Category + Date).
# --------------------------------------------------------------------------- #

class TestWebsiteHub:
    def test_hub_links_all_seven_named_sections(self, app, db, gadmin_client):
        # A 200 here already proves no BuildError from any of the hub's ten
        # url_for() cards (extras are fine; absences are not — see plan
        # <interfaces>). Then confirm each of the seven CRITERION-NAMED
        # section endpoints is actually reachable from the rendered body.
        r = gadmin_client.get('/admin-panel/public-site')
        assert r.status_code == 200, (r.status_code, r.get_data(as_text=True)[:400])
        html = r.get_data(as_text=True)

        with app.test_request_context():
            from flask import url_for
            resolved = {ep: url_for(ep) for ep in _HUB_SECTION_ENDPOINTS}

        for endpoint, url in resolved.items():
            assert url in html, (
                f'hub is missing a link to {endpoint!r} (resolved url {url!r}) '
                f'— criterion 1 requires all seven named sections reachable from the hub')

    def test_nav_public_site_entry_occurs_exactly_once_and_reads_website(
            self, app, db, gadmin_client):
        # "A single entry" (criterion 1) means the count, not mere presence.
        r = gadmin_client.get('/admin-panel/public-site/pages')
        assert r.status_code == 200, (r.status_code, r.get_data(as_text=True)[:400])
        html = r.get_data(as_text=True)

        count = html.count('data-nav-item="public-site"')
        assert count == 1, (
            f'expected exactly one public-site nav entry, found {count} — '
            f'criterion 1 requires a SINGLE "Website" entry, not a duplicated tab')

        assert '<span class="hidden lg:inline">Website</span>' in html, (
            'nav entry visible label must read "Website" (02-01 renamed it '
            'from "Public Site")')
        assert '<span class="hidden lg:inline">Public Site</span>' not in html, (
            'the old "Public Site" label must not still be present alongside the rename')


class TestPostsAndPagesStaySeparate:
    def test_pages_and_news_render_distinct_tables_at_distinct_urls(
            self, app, db, gadmin_client):
        # Both list templates fall back to an empty_state() when their query
        # returns nothing (see pages_list_flowbite.html / news_list_flowbite.html),
        # which would never render the <th> headers this test checks — seed one
        # row of each so the real table markup is what's under test.
        _make_page(db, 'hub-lock-separation-page')
        db.session.add(NewsPost(
            slug='hub-lock-separation-post', title='Separation Post',
            excerpt='seeded so the Posts table (not empty_state) renders',
            body_html='<p>body</p>', status='published',
            published_at=datetime(2026, 1, 1)))
        db.session.commit()

        pages_resp = gadmin_client.get('/admin-panel/public-site/pages')
        news_resp = gadmin_client.get('/admin-panel/public-site/news')
        assert pages_resp.status_code == 200, pages_resp.get_data(as_text=True)[:400]
        assert news_resp.status_code == 200, news_resp.get_data(as_text=True)[:400]

        pages_html = pages_resp.get_data(as_text=True)
        news_html = news_resp.get_data(as_text=True)

        # <th>-scoped: immune to the word appearing elsewhere in admin chrome.
        assert '>Category</th>' in news_html, \
            'Posts list must carry a Category column header'
        assert '>Date</th>' in news_html, \
            'Posts list must carry a Date column header'

        assert '>URL</th>' in pages_html, \
            'Pages list must carry a URL column header'
        assert '>Updated</th>' in pages_html, \
            'Pages list must carry an Updated column header'
        assert '>Category</th>' not in pages_html, (
            'Pages list must NOT gain a Category column — Posts and Pages are '
            'separate sections (criterion 5); a shared column would blur that')

    def test_seeded_post_shows_its_category_and_date_in_the_list(self, db, gadmin_client):
        post = NewsPost(
            slug='hub-lock-category-post', title='Hub Lock Category Post',
            excerpt='seeded for the Posts-list regression lock',
            body_html='<p>body</p>', status='published',
            category='Community Night',
            published_at=datetime(2026, 3, 4, 12, 0, 0))
        db.session.add(post)
        db.session.commit()

        r = gadmin_client.get('/admin-panel/public-site/news')
        assert r.status_code == 200, r.get_data(as_text=True)[:400]
        html = r.get_data(as_text=True)

        assert 'Hub Lock Category Post' in html
        assert 'Community Night' in html, \
            'seeded post category must render in its Posts-list row'
        assert 'Mar 4, 2026' in html, \
            'seeded post date must render in its Posts-list row'


# --------------------------------------------------------------------------- #
# Task 2 — criterion 2 (admin bar contents + anonymous control) and
# criterion 3 (Edit-to-View round trip, both directions).
# --------------------------------------------------------------------------- #

_ADMIN_BAR_ROOT = 'id="ecs-admin-bar"'
_ADMIN_BAR_SLICE_LEN = 4000  # the bar is ~40 lines of markup; ample headroom


def _bar_slice(html):
    """Bounded slice forward from the admin bar's root element id, so a match
    cannot be satisfied by unrelated markup further down the page."""
    idx = html.find(_ADMIN_BAR_ROOT)
    assert idx != -1, 'admin bar root element id not found in response body'
    return html[idx:idx + _ADMIN_BAR_SLICE_LEN]


class TestAdminBarRoundTrip:
    def test_anonymous_visitor_sees_no_admin_bar(self, db, client):
        page = _make_page(db, 'hub-lock-anon-page')
        r = client.get(f'/preview/{page.slug}')
        assert r.status_code == 200, r.get_data(as_text=True)[:400]
        html = r.get_data(as_text=True)
        assert _ADMIN_BAR_ROOT not in html, (
            'admin bar must not render for an anonymous visitor — this is the '
            'control proving _is_site_admin() actually gates the bar, not '
            'merely that it happens to be present for an admin')

    def test_admin_sees_exactly_one_admin_bar_with_full_contents(
            self, app, db, gadmin_client):
        page = _make_page(db, 'hub-lock-admin-bar-page')
        r = gadmin_client.get(f'/preview/{page.slug}')
        assert r.status_code == 200, r.get_data(as_text=True)[:400]
        html = r.get_data(as_text=True)

        count = html.count(_ADMIN_BAR_ROOT)
        assert count == 1, f'expected exactly one admin bar, found {count}'

        bar = _bar_slice(html)

        with app.test_request_context():
            from flask import url_for
            hub_url = url_for('admin_panel.public_site_hub')
            new_page_url = url_for('admin_panel.public_site_page_new')
            new_post_url = url_for('admin_panel.public_site_news_new')

        assert hub_url in bar, 'admin bar must link site name to the Website hub'
        assert new_page_url in bar, 'admin bar "+ New" must offer a new Page'
        assert new_post_url in bar, 'admin bar "+ New" must offer a new Post'
        assert 'Howdy,' in bar, 'admin bar must greet the signed-in admin'
        assert 'Log out' in bar, 'admin bar must offer Log out'

    def test_edit_link_targets_the_seeded_pages_own_editor(self, app, db, gadmin_client):
        page = _make_page(db, 'hub-lock-edit-target-page')
        r = gadmin_client.get(f'/preview/{page.slug}')
        assert r.status_code == 200, r.get_data(as_text=True)[:400]
        bar = _bar_slice(r.get_data(as_text=True))

        with app.test_request_context():
            from flask import url_for
            edit_url = url_for('admin_panel.site_editor', page_id=page.id)

        assert edit_url in bar, (
            f'admin bar Edit link must target THIS page\'s own editor '
            f'({edit_url!r}) — a bar linking to a different page\'s editor '
            f'would silently pass a substring check on /site-editor/ alone')

    def test_editor_exit_url_equals_seeded_pages_public_url_exactly(
            self, app, db, gadmin_client):
        page = _make_page(db, 'hub-lock-roundtrip-page')
        r = gadmin_client.get(f'/admin-panel/site-editor/{page.id}')
        assert r.status_code == 200, r.get_data(as_text=True)[:400]
        html = r.get_data(as_text=True)

        match = re.search(r'data-exit-url="([^"]*)"', html)
        assert match is not None, 'data-exit-url attribute not found in editor shell'
        exit_url = match.group(1)

        with app.test_request_context():
            from flask import url_for
            expected_public_url = url_for('public.dynamic_page', slug=page.slug)

        assert exit_url == expected_public_url, (
            f'data-exit-url must equal the page\'s own public URL exactly '
            f'(no ?edit=1 residue): got {exit_url!r}, expected '
            f'{expected_public_url!r}')
        assert 'edit=1' not in exit_url, \
            f'data-exit-url must not carry ?edit=1 residue: {exit_url!r}'
