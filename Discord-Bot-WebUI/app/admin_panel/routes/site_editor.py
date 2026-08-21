# app/admin_panel/routes/site_editor.py

"""
The in-place site editor — server side of the ONE page-editing system.

Shell:   GET  /admin-panel/site-editor/<page_id>       editor chrome + iframe
State:   GET  /admin-panel/site-editor/<page_id>/state draft doc + rev + catalog
Draft:   POST /admin-panel/site-editor/<page_id>/draft validated autosave
Section: POST /admin-panel/site-editor/<page_id>/render-section  swap payload
Publish: POST /admin-panel/site-editor/<page_id>/publish
Lock:    POST /admin-panel/site-editor/<page_id>/lock  (heartbeat / takeover)
         POST /admin-panel/site-editor/<page_id>/unlock

Contract with the client (site-editor JS):
- every draft write carries base_rev (the draft_rev it was built on); a
  mismatch returns 409 with the server's rev — the client must reload state,
  never blind-overwrite (kills the lost-update/stale-publish race).
- documents are ALWAYS passed through section_schema.validate_sections before
  touching the database; the response echoes normalization notes for toasts.
"""

import logging
from datetime import datetime, timedelta

from flask import render_template, request, jsonify, g, url_for, abort
from flask_login import login_required, current_user

from app.admin_panel import admin_panel_bp
from app.decorators import role_required
from app.models import SitePage, SitePageRevision, MediaUsage
from app.utils.db_utils import transactional

# The slug-lock rule is IMPORTED, never re-implemented here. This file used to
# carry a second copy that added a `home_*` prefix clause the server's rename
# guard never had — the two disagreed, and the looser one was the one the UI
# showed (WR-02). Bound at module scope on purpose: `site_editor._slug_locked`
# must BE `public_site._slug_locked`, not merely behave like it. Safe against
# circular import — public_site does not import this module, and routes/
# __init__.py loads public_site first regardless.
from app.admin_panel.routes.public_site import _slug_locked

logger = logging.getLogger(__name__)

# Site Editor is the least-privilege authoring role; admins keep everything.
_ROLES = ['Global Admin', 'Pub League Admin', 'Site Editor']

_AUTOSAVE_REVISION_EVERY = timedelta(minutes=5)
_AUTOSAVE_KEEP = 20


def _is_full_admin():
    try:
        from app.role_impersonation import get_effective_roles
        roles = get_effective_roles() or []
    except Exception:
        roles = [r.name for r in (getattr(current_user, 'roles', None) or [])]
    return any(r in ('Global Admin', 'Pub League Admin') for r in roles)


def _get_page(page_id):
    """The shared fetch for every editor route below. Delegates the block-
    slug refusal to public_site._get_real_page rather than re-deriving the
    rule here — a second copy in this file is exactly the drift (CR-01) that
    let a home-page content block stay reachable through the editor surface
    after the Pages-list guard was fixed. Keeps this function's existing
    contract of raising a 404 itself (its callers rely on that rather than
    checking a return value) and its existing trashed-row rejection."""
    from app.admin_panel.routes.public_site import _get_real_page
    page = _get_real_page(page_id)
    if not page or page.deleted_at is not None:
        abort(404)
    return page


def _page_settings_dict(page):
    """The page-metadata fields the editor's Page settings panel renders and
    the panel's POST echoes back on success."""
    return {'status': page.status, 'slug': page.slug, 'title': page.title,
            'excerpt': page.excerpt, 'featured_image_url': page.featured_image_url,
            'meta_title': page.meta_title, 'meta_description': page.meta_description,
            'slug_locked': _slug_locked(page.slug)}


def _rebuild_media_usage(page, doc):
    from app.services.section_schema import collect_asset_ids
    (g.db_session.query(MediaUsage)
     .filter_by(entity_type='page', entity_id=page.id)
     .delete(synchronize_session=False))
    for aid in collect_asset_ids(doc):
        g.db_session.add(MediaUsage(asset_id=aid, entity_type='page',
                                    entity_id=page.id, field='sections'))


def _snapshot(page, kind, label=None):
    g.db_session.add(SitePageRevision(
        page_id=page.id, title=page.title,
        sections=page.sections_draft if kind == 'autosave' else page.sections_published,
        kind=kind, label=label, created_at=datetime.utcnow(),
        created_by_id=getattr(current_user, 'id', None)))
    # Prune rolling autosaves (publish snapshots are pruned by the legacy
    # 30-cap in public_site._snapshot_revision's spirit — count-capped here).
    old = (g.db_session.query(SitePageRevision.id)
           .filter_by(page_id=page.id, kind='autosave')
           .order_by(SitePageRevision.created_at.desc())
           .offset(_AUTOSAVE_KEEP).all())
    if old:
        (g.db_session.query(SitePageRevision)
         .filter(SitePageRevision.id.in_([r.id for r in old]))
         .delete(synchronize_session=False))


@admin_panel_bp.route('/site-editor/home')
@login_required
@role_required(_ROLES)
def site_editor_home():
    """Convenience entry: edit the home page (nav tabs/cards link here)."""
    page = SitePage.query.filter_by(slug='home').first()
    if not page:
        from flask import redirect
        return redirect(url_for('admin_panel.public_site_pages'))
    from flask import redirect
    return redirect(url_for('admin_panel.site_editor', page_id=page.id))


@admin_panel_bp.route('/site-editor/<int:page_id>')
@login_required
@role_required(_ROLES)
def site_editor(page_id):
    """Editor shell: top bar + same-origin iframe of the page's draft render."""
    page = _get_page(page_id)
    pages = (SitePage.query
             .filter(SitePage.deleted_at.is_(None),
                     ~SitePage.slug.like('home\\_%'))
             .order_by(SitePage.title.asc()).all())
    preview_url = _public_page_url(page) + '?edit=1'
    return render_template('admin_panel/public_site/site_editor_flowbite.html',
                           page=page, pages=pages, preview_url=preview_url,
                           is_full_admin=_is_full_admin())


def _public_page_url(page):
    fixed = {'home': 'public.home', 'about': 'public.about', 'guide': 'public.guide',
             'guests': 'public.guests', 'faqs': 'public.faqs',
             'register': 'public.register', 'contact': 'public.contact'}
    if page.slug in fixed:
        return url_for(fixed[page.slug])
    return url_for('public.dynamic_page', slug=page.slug)


@admin_panel_bp.route('/site-editor/<int:page_id>/state')
@login_required
@role_required(_ROLES)
def site_editor_state(page_id):
    from app.services.section_schema import (VOLUNTEER_BLOCK_TYPES,
                                             ADMIN_BLOCK_TYPES, SECTION_TYPES,
                                             DYNAMIC_BLOCK_TYPES)
    page = _get_page(page_id)
    doc = page.sections_draft or page.sections_published
    if doc is None:
        # Page not yet converted (both section docs NULL) but the public view
        # still renders rich fallback content via the converter. Seed the editor
        # with that SAME doc — NOT an empty one — otherwise the first structural
        # edit + Publish writes an empty doc to sections_published and silently
        # erases the fallback (which only renders while sections_published is NULL).
        try:
            from app.services.section_converter import build_doc_for_page
            from app.services.section_schema import validate_sections
            doc, _ = validate_sections(build_doc_for_page(g.db_session, page), is_admin=True)
        except Exception:
            logger.exception('site_editor /state fallback build failed for %r', page.slug)
            doc = {'v': 1, 'sections': []}
    return jsonify({
        'success': True,
        'page': {'id': page.id, 'slug': page.slug, 'title': page.title,
                 'status': page.status,
                 'published_at': page.published_at.isoformat() if page.published_at else None,
                 'has_unpublished_changes': page.sections_draft != page.sections_published,
                 'excerpt': page.excerpt, 'featured_image_url': page.featured_image_url,
                 'meta_title': page.meta_title, 'meta_description': page.meta_description,
                 'slug_locked': _slug_locked(page.slug)},
        'doc': doc,
        'draft_rev': page.draft_rev or 0,
        'catalog': {
            'sections': list(SECTION_TYPES),
            'blocks': list(ADMIN_BLOCK_TYPES if _is_full_admin() else VOLUNTEER_BLOCK_TYPES),
            'dynamic': list(DYNAMIC_BLOCK_TYPES),
        },
        'preview_url': _public_page_url(page),
    })


def _doc_has_admin_blocks(doc):
    """True if a stored doc already contains admin-only blocks (embed_raw).
    Such content was authored + sanitized by an admin; a Site Editor saving an
    unrelated change must not have it stripped just because their role can't
    author it — so we validate their save as admin when it's already present."""
    if not isinstance(doc, dict):
        return False
    from app.services.section_schema import VOLUNTEER_BLOCK_TYPES
    for s in doc.get('sections', []):
        for b in s.get('blocks', []):
            if b.get('type') not in VOLUNTEER_BLOCK_TYPES:
                return True
    return False


@admin_panel_bp.route('/site-editor/<int:page_id>/draft', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def site_editor_draft(page_id):
    from app.services.section_schema import validate_sections
    page = _get_page(page_id)
    payload = request.get_json(silent=True) or {}
    base_rev = payload.get('base_rev')
    if base_rev is None:
        return jsonify({'success': False, 'error': 'stale_rev',
                        'draft_rev': page.draft_rev or 0}), 409

    # Preserve admin-only blocks (embed_raw) a Site Editor can't author but that
    # already live in the draft — validate as admin when they're present so the
    # save doesn't silently strip them.
    as_admin = _is_full_admin() or _doc_has_admin_blocks(page.sections_draft)
    doc, notes = validate_sections(payload.get('doc'), is_admin=as_admin)
    now = datetime.utcnow()

    # Atomic compare-and-set on draft_rev: reject if another writer advanced it
    # since the client loaded (two tabs / a racing autosave). The UPDATE's WHERE
    # clause makes the check-and-increment a single statement — an unlocked
    # read-then-write could let two same-base_rev saves both "win".
    from app.models import SitePage as _SP
    new_rev = int(base_rev) + 1
    updated = (g.db_session.query(_SP)
               .filter(_SP.id == page.id, _SP.draft_rev == int(base_rev))
               .update({'sections_draft': doc, 'draft_rev': new_rev,
                        'draft_updated_at': now,
                        'draft_updated_by_id': getattr(current_user, 'id', None)},
                       synchronize_session=False))
    if not updated:
        g.db_session.rollback()
        fresh = g.db_session.query(_SP.draft_rev).filter_by(id=page.id).first()
        return jsonify({'success': False, 'error': 'stale_rev',
                        'draft_rev': (fresh[0] if fresh else 0)}), 409
    g.db_session.expire(page)

    # The atomic UPDATE above already stored the doc + bumped draft_rev; page was
    # expired, so it now reflects the committed state.
    _rebuild_media_usage(page, doc)

    # Rolling autosave revision at most every N minutes (crash safety without
    # unbounded growth) — a checkpoint of the just-saved draft.
    last_auto = (g.db_session.query(SitePageRevision.created_at)
                 .filter_by(page_id=page.id, kind='autosave')
                 .order_by(SitePageRevision.created_at.desc()).first())
    if not last_auto or now - last_auto[0] > _AUTOSAVE_REVISION_EVERY:
        g.db_session.add(SitePageRevision(
            page_id=page.id, title=page.title, sections=doc, kind='autosave',
            created_at=now, created_by_id=getattr(current_user, 'id', None)))
        old = (g.db_session.query(SitePageRevision.id)
               .filter_by(page_id=page.id, kind='autosave')
               .order_by(SitePageRevision.created_at.desc())
               .offset(_AUTOSAVE_KEEP).all())
        if old:
            (g.db_session.query(SitePageRevision)
             .filter(SitePageRevision.id.in_([r.id for r in old]))
             .delete(synchronize_session=False))

    resp = {'success': True, 'draft_rev': new_rev, 'notes': notes, 'doc': doc}
    sid = payload.get('render_section')
    if sid:
        from app.services.site_renderer import render_single_section
        g.db_session.flush()
        resp['section_html'] = render_single_section(page, sid, mode='draft',
                                                     session=g.db_session)
    return jsonify(resp)


@admin_panel_bp.route('/site-editor/<int:page_id>/render-section', methods=['POST'])
@login_required
@role_required(_ROLES)
def site_editor_render_section(page_id):
    """Render one draft section (used after undo/redo, which restores client
    state without a draft write first)."""
    from app.services.site_renderer import render_single_section
    page = _get_page(page_id)
    sid = (request.get_json(silent=True) or {}).get('section_id')
    html = render_single_section(page, sid, mode='draft', session=g.db_session)
    if html is None:
        return jsonify({'success': False, 'error': 'unknown_section'}), 404
    return jsonify({'success': True, 'section_html': html})


@admin_panel_bp.route('/site-editor/<int:page_id>/page-settings', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def site_editor_page_settings(page_id):
    """JSON write target for the editor's Page settings panel — status,
    permalink, excerpt, featured image and SEO. Delegates every field write to
    apply_page_settings (app/admin_panel/routes/public_site.py) so the panel
    and the legacy settings form can never drift apart (T-03-05). Uses _ROLES,
    NOT _ADMIN_ROLES — a Site Editor must be able to edit page settings;
    _ADMIN_ROLES is reserved for Appearance.

    Page-settings saves are NOT compare-and-swap protected on draft_rev in
    general (metadata lives in different columns than the section document,
    so there's no lost-update hazard against it, and bumping draft_rev here
    would spuriously invalidate every other open tab's base_rev). The one
    exception is the draft -> published transition, which copies
    sections_draft into sections_published -- exactly the stale-publish race
    /publish's CAS exists to prevent -- so THAT transition alone carries
    base_rev, checked identically to site_editor_publish. This endpoint never
    writes draft_rev itself.
    """
    page = _get_page(page_id)
    data = request.get_json(silent=True) or {}

    transitioning_to_published = (data.get('status') == 'published'
                                  and page.status != 'published')
    if transitioning_to_published:
        base_rev = data.get('base_rev')
        # base_rev arrives from the client, so a non-numeric value is a bad
        # request, not a server fault — int() would otherwise raise ValueError
        # and surface as a 500.
        try:
            base_rev_int = int(base_rev)
        except (TypeError, ValueError):
            base_rev_int = None
        if base_rev_int is None or base_rev_int != (page.draft_rev or 0):
            return jsonify({'success': False, 'error': 'stale_rev',
                            'draft_rev': page.draft_rev or 0}), 409

    old_slug = page.slug
    from app.admin_panel.routes.public_site import apply_page_settings
    ok, error = apply_page_settings(page, data)
    if not ok:
        # Always 400: the stale-revision 409 is returned EARLIER in this same
        # function by the base_rev check above (the one implementation of that
        # check), so by the time control reaches here the only refusal
        # apply_page_settings can produce is its content refusal.
        return jsonify({'success': False, 'error': error,
                        'draft_rev': page.draft_rev or 0}), 400

    return jsonify({'success': True, 'page': _page_settings_dict(page),
                    'slug_changed': page.slug != old_slug})


@admin_panel_bp.route('/site-editor/<int:page_id>/publish', methods=['POST'])
@login_required
@role_required(_ROLES)
@transactional
def site_editor_publish(page_id):
    from app.services.public_cache import bump_public_cache_after_commit as bump_public_cache
    page = _get_page(page_id)
    payload = request.get_json(silent=True) or {}
    base_rev = payload.get('base_rev')
    if base_rev is None or int(base_rev) != (page.draft_rev or 0):
        return jsonify({'success': False, 'error': 'stale_rev',
                        'draft_rev': page.draft_rev or 0}), 409
    # Empty guard: the canonical empty doc {'v':1,'sections':[]} is truthy, so
    # test the section list, not the dict — otherwise a never-edited new page
    # (or one whose sections were all deleted) could be published blank.
    if not (page.sections_draft or {}).get('sections'):
        return jsonify({'success': False, 'error': 'empty_draft'}), 400

    page.sections_published = page.sections_draft
    page.published_at = datetime.utcnow()
    page.status = 'published'
    _snapshot(page, 'publish', label=(payload.get('label') or '').strip()[:60] or None)
    bump_public_cache('page', page.slug)
    if page.slug == 'home':
        bump_public_cache('global')  # home carries site-wide dynamic content
    return jsonify({'success': True, 'draft_rev': page.draft_rev or 0,
                    'published_at': page.published_at.isoformat()})


@admin_panel_bp.route('/site-editor/<int:page_id>/lock', methods=['POST'])
@login_required
@role_required(_ROLES)
def site_editor_lock(page_id):
    from app.services.public_cache import acquire_edit_lock
    _get_page(page_id)
    force = bool((request.get_json(silent=True) or {}).get('force'))
    ok, holder = acquire_edit_lock(
        page_id, getattr(current_user, 'id', 0),
        getattr(current_user, 'username', 'someone'), force=force)
    return jsonify({'success': ok, 'holder': holder})


@admin_panel_bp.route('/site-editor/<int:page_id>/unlock', methods=['POST'])
@login_required
@role_required(_ROLES)
def site_editor_unlock(page_id):
    # Closes the one page-id route that reached the lock layer without first
    # resolving the row (reported by 04-03, closed 2026-08-20). The exposure was
    # never large — release_edit_lock only deletes a key whose holder matches the
    # caller, so a Site Editor could not release someone else's lock, and this
    # route never read or wrote the SitePage row. But it was the single hole in
    # "every route taking a client-supplied page id goes through the shared
    # fetch", and that invariant is worth more than the individual exposure: it
    # is what stops the NEXT route from re-opening CR-01.
    _get_page(page_id)
    from app.services.public_cache import release_edit_lock
    release_edit_lock(page_id, getattr(current_user, 'id', 0))
    return jsonify({'success': True})
