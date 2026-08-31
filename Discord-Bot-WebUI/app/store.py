# app/store.py

"""
Store Module -- coach-facing.

The league merchandise store. Coaches browse items and place one order per
season; the store tracks orders but processes no payment.

ADMINISTRATION LIVES AT /admin-panel/store/*, not here. The admin half of this
blueprint (the old /store/admin page, item CRUD, order management and the season
reset) was retired: its page rendered two divergent copies of itself behind a
`shell` flag, its JavaScript never initialised, and its Flowbite dropdown deleted
its own click handler at load, so every button on it was silently dead. The
routes below are kept as redirects so old bookmarks, links and the browser back
button all land on the surviving surface in app/admin_panel/routes/store_management.py.
"""

import logging

from flask import Blueprint, render_template, request, redirect, url_for, jsonify, g
from flask_login import login_required
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.models import StoreItem, StoreOrder
from app.alert_helpers import show_error
from app.decorators import role_required
from app.store_helpers import check_order_eligibility, validate_order_options
from app.utils.user_helpers import safe_current_user

logger = logging.getLogger(__name__)

# Create the blueprint for store management
store_bp = Blueprint('store', __name__, url_prefix='/store')


# ============================================================================
# COACH-FACING
# ============================================================================

@store_bp.route('/', endpoint='index', methods=['GET'])
@login_required
@role_required(['Pub League Coach', 'Pub League Admin', 'Global Admin'])
def store_index():
    """
    Display the store front page with available items for coaches to order.
    Only accessible by coaches and admins.
    """
    session = g.db_session

    try:
        # One shared definition of "may this person order" -- see app/store_helpers.py.
        # current_season_order is the order that BLOCKS ordering, so an order an
        # admin has granted a re-order on correctly stops appearing here.
        eligible, _reason, current_season, blocking_order = check_order_eligibility(
            session, safe_current_user.id
        )
        has_ordered_this_season = blocking_order is not None
        current_season_order = blocking_order

        # Get all active store items
        items = session.query(StoreItem).filter(
            StoreItem.is_active == True
        ).order_by(StoreItem.category, StoreItem.name).all()

        # Get user's recent orders
        recent_orders = session.query(StoreOrder).options(
            selectinload(StoreOrder.item),
            selectinload(StoreOrder.season)
        ).filter(
            StoreOrder.ordered_by == safe_current_user.id
        ).order_by(StoreOrder.order_date.desc()).limit(5).all()

        return render_template(
            'store/index_flowbite.html',
            title='League Store',
            items=items,
            recent_orders=recent_orders,
            current_season=current_season,
            has_ordered_this_season=has_ordered_this_season,
            current_season_order=current_season_order
        )

    except Exception as e:
        logger.exception(f"Error loading store: {str(e)}")
        show_error('Error loading store items.')
        return redirect(url_for('main.index'))


@store_bp.route('/order/<int:item_id>', endpoint='place_order', methods=['POST'])
@login_required
@role_required(['Pub League Coach', 'Pub League Admin', 'Global Admin'])
def place_order(item_id):
    """
    Place an order for a store item.
    """
    session = g.db_session
    item = session.query(StoreItem).get(item_id)

    if not item:
        return jsonify({'success': False, 'message': 'Store item not found.'}), 404

    if not item.is_active:
        return jsonify({'success': False, 'message': 'This item is no longer available.'}), 400

    try:
        eligible, reason, current_season, _blocking = check_order_eligibility(
            session, safe_current_user.id
        )
        if not eligible:
            return jsonify({'success': False, 'message': reason}), 400

        # Get order details from form
        quantity = int(request.form.get('quantity', 1))
        notes = request.form.get('notes', '').strip()

        # Validate quantity
        if quantity < 1:
            return jsonify({'success': False, 'message': 'Quantity must be at least 1.'}), 400

        # Colour/size are required only when the item declares options, and must
        # be one of them -- the same rule the mobile API already used. The old
        # code required both unconditionally, which is why the form posted the
        # sentinels 'N/A' and 'One Size' and why items with no options could not
        # be ordered from a browser at all.
        ok, message, selected_color, selected_size = validate_order_options(
            item, request.form.get('color'), request.form.get('size')
        )
        if not ok:
            return jsonify({'success': False, 'message': message}), 400

        # Create order
        order = StoreOrder(
            item_id=item_id,
            ordered_by=safe_current_user.id,
            quantity=quantity,
            selected_color=selected_color,
            selected_size=selected_size,
            notes=notes if notes else None,
            season_id=current_season.id
        )

        session.add(order)
        session.commit()

        logger.info(f"Order placed for item '{item.name}' by user {safe_current_user.id}")
        return jsonify({
            'success': True,
            'message': f"Order placed successfully for {quantity}x {item.name}."
        })

    except IntegrityError:
        # uq_store_orders_live_per_season. The eligibility check above cannot
        # cover a browser POST racing a phone POST; this is the backstop, and it
        # returns the same message the check would have.
        session.rollback()
        logger.info(f"Duplicate store order blocked for user {safe_current_user.id}")
        return jsonify({
            'success': False,
            'message': 'You have already placed an order this season. Only one order per season is allowed.'
        }), 409
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid quantity specified.'}), 400
    except Exception as e:
        session.rollback()
        logger.exception(f"Error placing order: {str(e)}")
        return jsonify({
            'success': False,
            'message': 'Error placing order.'
        }), 500


@store_bp.route('/my-orders', endpoint='my_orders', methods=['GET'])
@login_required
@role_required(['Pub League Coach', 'Pub League Admin', 'Global Admin'])
def my_orders():
    """
    Display the user's order history.
    """
    session = g.db_session

    try:
        orders = session.query(StoreOrder).options(
            selectinload(StoreOrder.item),
            selectinload(StoreOrder.processor),
            selectinload(StoreOrder.season)
        ).filter(
            StoreOrder.ordered_by == safe_current_user.id
        ).order_by(StoreOrder.order_date.desc()).all()

        return render_template(
            'store/my_orders_flowbite.html',
            title='My Orders',
            orders=orders
        )

    except Exception as e:
        logger.exception(f"Error loading user orders: {str(e)}")
        show_error('Error loading your orders.')
        return redirect(url_for('store.index'))


# ============================================================================
# RETIRED ADMIN ROUTES -- redirects to /admin-panel/store/*
#
# These endpoints are kept (rather than deleted) so url_for() calls, bookmarks
# and old links keep resolving. GET routes send the browser to the equivalent
# admin-panel page; POST routes answer with 410 Gone and the new URL, because
# silently redirecting a mutation to a page that will not perform it is exactly
# the kind of "reports success, does nothing" behaviour that hid this outage.
# ============================================================================

def _moved(endpoint, **values):
    """Redirect a retired GET route to its admin-panel replacement."""
    return redirect(url_for(endpoint, **values), code=302)


def _gone(endpoint, **values):
    """Answer a retired mutating route honestly instead of pretending it worked."""
    return jsonify({
        'success': False,
        'message': 'This endpoint moved to the admin panel. Reload the page.',
        'moved_to': url_for(endpoint, **values)
    }), 410


@store_bp.route('/admin', endpoint='admin', methods=['GET'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def store_admin():
    """Retired -- store administration now lives at /admin-panel/store."""
    return _moved('admin_panel.store_management')


@store_bp.route('/admin/item/create', endpoint='create_item', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def create_item():
    """Retired -- see admin_panel.create_store_item."""
    if request.method == 'GET':
        return _moved('admin_panel.create_store_item')
    return _gone('admin_panel.create_store_item')


@store_bp.route('/admin/item/<int:item_id>/edit', endpoint='edit_item', methods=['GET', 'POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def edit_item(item_id):
    """Retired -- see admin_panel.edit_store_item.

    POST answers 410 rather than redirecting: a 302 makes the browser re-issue
    the request as a GET, so a stale tab submitting an edit would land on the
    new form with its changes silently dropped.
    """
    if request.method == 'GET':
        return _moved('admin_panel.edit_store_item', item_id=item_id)
    return _gone('admin_panel.edit_store_item', item_id=item_id)


@store_bp.route('/admin/item/<int:item_id>/delete', endpoint='delete_item', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def delete_item(item_id):
    """Retired -- see admin_panel.delete_store_item.

    Note the surviving route REFUSES to delete an item that has orders and asks
    you to deactivate it instead. This one used to cascade-delete every order for
    the item behind a trash icon, with no warning and no audit row.
    """
    return _gone('admin_panel.store_items')


@store_bp.route('/admin/order/<int:order_id>/update', endpoint='update_order', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def update_order(order_id):
    """Retired -- see admin_panel.update_order_status."""
    return _gone('admin_panel.update_order_status', order_id=order_id)


@store_bp.route('/admin/orders/bulk-update', endpoint='bulk_update_orders', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def bulk_update_orders():
    """Retired -- see admin_panel.store_orders."""
    return _gone('admin_panel.store_orders')


@store_bp.route('/admin/orders/bulk-delete', endpoint='bulk_delete_orders', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def bulk_delete_orders():
    """Retired -- see admin_panel.store_orders."""
    return _gone('admin_panel.store_orders')


@store_bp.route('/admin/order/<int:order_id>/delete', endpoint='delete_order', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def delete_order(order_id):
    """Retired -- see admin_panel.delete_store_order."""
    return _gone('admin_panel.delete_store_order', order_id=order_id)


@store_bp.route('/admin/reset-season-ordering', endpoint='reset_season_ordering', methods=['POST'])
@login_required
@role_required(['Pub League Admin', 'Global Admin'])
def reset_season_ordering():
    """Retired -- see admin_panel.reset_season_ordering.

    The old implementation had never actually run: its confirm button lived
    inside JavaScript that never initialised. Both of its modes were destructive
    -- one hard-deleted every order for the season, the other permanently nulled
    season_id despite a comment claiming it was temporary. The replacement stamps
    eligibility_reset_at and keeps everything.
    """
    return _gone('admin_panel.reset_season_ordering')
