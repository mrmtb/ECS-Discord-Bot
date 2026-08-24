"""
Legal Routes Module

This module provides public routes for legal pages like Privacy Policy and Terms of Service.
These routes are accessible without authentication.
"""

from flask import Blueprint, render_template

legal_bp = Blueprint('legal', __name__)


@legal_bp.context_processor
def _legal_public_context():
    """Give the legal templates the REAL public-site context.

    These pages extend ``public/base_public.html``, whose nav, status strip,
    footer and CTA all read variables produced by ``_inject_public_context()``.
    That function is registered as a ``@public_bp.context_processor``, so it
    runs for ``public.*`` endpoints only — never for ``legal.*``. Without this,
    the templates had to invent values, and the invented CTA hardcoded
    ``mode: 'waitlist'``: /privacy, /terms, /terms-of-service and
    /delete-account announced "Waitlist open" even when registration was open.

    The import is deferred to call time so this module stays importable
    regardless of blueprint registration order, and every helper inside
    ``_inject_public_context`` is already exception-guarded.
    """
    from app.public_site import _inject_public_context
    return _inject_public_context()


@legal_bp.route('/privacy')
def privacy_policy():
    """Display the privacy policy page."""
    return render_template('legal/privacy_policy.html')


@legal_bp.route('/terms')
def terms_of_service():
    """Display the terms of service page."""
    return render_template('legal/terms_of_service.html')


# Alias routes for app store requirements
# privacy_policy_alias() REMOVED — dead route. It registered GET /privacy-policy as an
# "alias", but main_bp (app/main.py:947::privacy_policy) registers first (blueprints.py:190
# vs :381), so the alias was never reachable. The canonical route already serves this path.


@legal_bp.route('/terms-of-service')
def terms_of_service_alias():
    """Alias for /terms for app store compatibility."""
    return render_template('legal/terms_of_service.html')


@legal_bp.route('/delete-account')
def delete_account_info():
    """Public account deletion info page for Google Play Store compliance."""
    return render_template('legal/delete_account.html')
