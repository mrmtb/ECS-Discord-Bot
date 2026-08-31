# app/admin_panel/routes/store_management.py

"""
Admin Panel Store Management Routes

This module contains routes for managing the store system:
- Store item management (CRUD)
- Order processing and tracking
- Store analytics and reporting
- Category management
"""

import logging
import json
from datetime import datetime, timedelta
from flask import render_template, request, jsonify, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import func, desc, and_, or_
from sqlalchemy.exc import IntegrityError

from .. import admin_panel_bp
from app.core import db
from app.models.store import StoreItem, StoreOrder
from app.models.core import User, Season
from app.models.admin_config import AdminAuditLog
from app.decorators import role_required
from app.store_helpers import get_current_store_season, validate_order_options
from app.utils.db_utils import transactional

# Set up the module logger
logger = logging.getLogger(__name__)

# The one definition of the order lifecycle. Previously re-declared as a
# literal list in four separate places, which is how the single-order and
# bulk paths drifted apart on timestamp handling.
ORDER_STATUSES = ('PENDING', 'PROCESSING', 'ORDERED', 'DELIVERED', 'CANCELLED')


@admin_panel_bp.route('/store')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def store_management():
    """Store management hub page."""
    try:
        # Get store statistics
        total_items = StoreItem.query.count()
        active_items = StoreItem.query.filter_by(is_active=True).count()
        total_orders = StoreOrder.query.count()
        pending_orders = StoreOrder.query.filter_by(status='PENDING').count()
        processing_orders = StoreOrder.query.filter_by(status='PROCESSING').count()
        
        # Recent orders (last 7 days)
        week_ago = datetime.utcnow() - timedelta(days=7)
        recent_orders = StoreOrder.query.filter(
            StoreOrder.order_date >= week_ago
        ).count()
        
        # Order status breakdown
        order_status_breakdown = db.session.query(
            StoreOrder.status,
            func.count(StoreOrder.id).label('count')
        ).group_by(StoreOrder.status).all()
        
        # Popular items (by order count)
        popular_items = db.session.query(
            StoreItem.name,
            func.count(StoreOrder.id).label('order_count')
        ).join(StoreOrder).group_by(StoreItem.id, StoreItem.name)\
         .order_by(desc('order_count')).limit(5).all()
        
        # Recent activity
        recent_activity = []
        
        # Recent orders
        latest_orders = StoreOrder.query.order_by(desc(StoreOrder.order_date)).limit(5).all()
        for order in latest_orders:
            recent_activity.append({
                'type': 'order',
                'timestamp': order.order_date,
                'description': f"New order for {order.item.name if order.item else 'Unknown Item'} by {order.orderer.username if order.orderer else 'Unknown User'}",
                'status': order.status
            })
        
        # Recent item updates
        latest_items = StoreItem.query.order_by(desc(StoreItem.updated_at)).limit(3).all()
        for item in latest_items:
            recent_activity.append({
                'type': 'item_update',
                'timestamp': item.updated_at,
                'description': f"Item '{item.name}' was updated",
                'status': 'active' if item.is_active else 'inactive'
            })
        
        # Sort by timestamp
        recent_activity.sort(key=lambda x: x['timestamp'], reverse=True)
        recent_activity = recent_activity[:10]
        
        stats = {
            'total_items': total_items,
            'active_items': active_items,
            'inactive_items': total_items - active_items,
            'total_orders': total_orders,
            'pending_orders': pending_orders,
            'processing_orders': processing_orders,
            'recent_orders': recent_orders,
            'order_status_breakdown': dict(order_status_breakdown),
            'popular_items': [{'name': name, 'count': count} for name, count in popular_items]
        }
        
        return render_template('admin_panel/store/management_flowbite.html',
                             stats=stats,
                             recent_activity=recent_activity)
    except Exception as e:
        logger.error(f"Error loading store management: {e}")
        flash('Store management unavailable. Check database connectivity and store models.', 'error')
        return redirect(url_for('admin_panel.dashboard'))


@admin_panel_bp.route('/store/items')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def store_items():
    """Store items management page."""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = 20
        
        # Build query with filters
        query = StoreItem.query
        
        # Category filter
        category = request.args.get('category')
        if category and category != 'all':
            query = query.filter(StoreItem.category == category)
        
        # Status filter
        status = request.args.get('status')
        if status == 'active':
            query = query.filter(StoreItem.is_active == True)
        elif status == 'inactive':
            query = query.filter(StoreItem.is_active == False)
        
        # Search filter
        search = request.args.get('search', '').strip()
        if search:
            query = query.filter(or_(
                StoreItem.name.ilike(f'%{search}%'),
                StoreItem.description.ilike(f'%{search}%'),
                StoreItem.category.ilike(f'%{search}%')
            ))
        
        # Order by
        order_by = request.args.get('order_by', 'name')
        if order_by == 'name':
            query = query.order_by(StoreItem.name)
        elif order_by == 'created_at':
            query = query.order_by(desc(StoreItem.created_at))
        elif order_by == 'updated_at':
            query = query.order_by(desc(StoreItem.updated_at))
        elif order_by == 'category':
            query = query.order_by(StoreItem.category, StoreItem.name)
        
        items = query.paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        # Get all categories for filter dropdown
        categories = db.session.query(StoreItem.category).filter(
            StoreItem.category.isnot(None)
        ).distinct().all()
        categories = [cat[0] for cat in categories if cat[0]]
        
        return render_template('admin_panel/store/items_flowbite.html',
                             items=items,
                             categories=categories,
                             current_filters={
                                 'category': category or 'all',
                                 'status': status or 'all',
                                 'search': search,
                                 'order_by': order_by
                             })
    except Exception as e:
        logger.error(f"Error loading store items: {e}")
        flash('Store items data unavailable. Verify database connection and item models.', 'error')
        return redirect(url_for('admin_panel.store_management'))


def _resolve_item_image(image_url):
    """Return the image URL for an item, uploading a posted file if there is one.

    An uploaded file wins over the URL field. Reuses the media library's
    save_public_image (validation, re-encode, responsive variants) rather than
    inventing a second image pipeline. Returns (url, error_message); on error
    the caller keeps the URL field and shows the message, because a silently
    discarded upload is exactly what this replaces -- the previous store code
    read the file and threw it away behind a TODO while the form kept offering
    the control.
    """
    upload = request.files.get('image_file')
    if not upload or not upload.filename:
        return image_url or None, None

    try:
        from app.services.media_service import save_public_image, MediaValidationError
    except Exception:
        logger.exception("Media service unavailable for store item image upload")
        return image_url or None, 'Image upload is unavailable right now.'

    try:
        asset = save_public_image(upload, uploaded_by_id=current_user.id, session=db.session)
        return asset.url, None
    except MediaValidationError as exc:
        return image_url or None, str(exc)
    except Exception:
        logger.exception("Error uploading store item image")
        return image_url or None, 'Could not process that image.'


@admin_panel_bp.route('/store/items/create', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def create_store_item():
    """Create new store item."""
    if request.method == 'POST':
        # Get form data
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        image_url = request.form.get('image_url', '').strip()
        category = request.form.get('category', '').strip()
        price = request.form.get('price', '').strip()

        # Get colors and sizes
        colors = []
        sizes = []
        for key, value in request.form.items():
            if key.startswith('color_') and value.strip():
                colors.append(value.strip())
            elif key.startswith('size_') and value.strip():
                sizes.append(value.strip())

        # Validation
        if not name:
            flash('Item name is required.', 'error')
            return render_template('admin_panel/store/item_form_flowbite.html',
                                 action='create', item=None)

        # Check for duplicate name
        if StoreItem.query.filter_by(name=name).first():
            flash('An item with this name already exists.', 'error')
            return render_template('admin_panel/store/item_form_flowbite.html',
                                 action='create', item=None)

        try:
            price_value = float(price) if price else None
        except ValueError:
            flash('Invalid price format.', 'error')
            return render_template('admin_panel/store/item_form_flowbite.html',
                                 action='create', item=None)

        resolved_image, image_error = _resolve_item_image(image_url)
        if image_error:
            flash(image_error, 'error')
            return render_template('admin_panel/store/item_form_flowbite.html',
                                 action='create', item=None)

        # Create item
        item = StoreItem(
            name=name,
            description=description or None,
            image_url=resolved_image,
            category=category or None,
            price=price_value,
            available_colors=json.dumps(colors) if colors else None,
            available_sizes=json.dumps(sizes) if sizes else None,
            created_by=current_user.id,
            is_active=True
        )

        db.session.add(item)

        # Log the action
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='create_store_item',
            resource_type='store',
            resource_id=str(item.id),
            new_value=f"Created store item: {item.name}",
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        flash(f'Store item "{item.name}" created successfully.', 'success')
        return redirect(url_for('admin_panel.store_items'))

    # GET request - show form
    return render_template('admin_panel/store/item_form_flowbite.html',
                         action='create', item=None)


@admin_panel_bp.route('/store/items/<int:item_id>/edit', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def edit_store_item(item_id):
    """Edit store item."""
    item = StoreItem.query.get_or_404(item_id)

    if request.method == 'POST':
        # Store old values for audit log
        old_values = {
            'name': item.name,
            'description': item.description,
            'category': item.category,
            'is_active': item.is_active
        }

        # Read and validate EVERYTHING before touching `item`.
        #
        # @transactional treats ANY normal return as success and commits, so a
        # `flash(...) + render_template(...)` placed after a partial mutation
        # persists half an edit while telling the admin it failed -- rename the
        # item, attach a 20MB photo, and the rename sticks while the error says
        # the image was rejected.
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip() or None
        category = request.form.get('category', '').strip() or None
        price_raw = request.form.get('price', '').strip()
        is_active = 'is_active' in request.form

        colors = []
        sizes = []
        for key, value in request.form.items():
            if key.startswith('color_') and value.strip():
                colors.append(value.strip())
            elif key.startswith('size_') and value.strip():
                sizes.append(value.strip())

        def _reject(message):
            # Roll back first: a failed upload may already have flushed a
            # MediaAsset row, and `item` must re-render as it is stored.
            flash(message, 'error')
            db.session.rollback()
            return render_template('admin_panel/store/item_form_flowbite.html',
                                   action='edit', item=item)

        if not name:
            return _reject('Item name is required.')

        try:
            price_value = float(price_raw) if price_raw else None
        except ValueError:
            return _reject('Invalid price format.')

        duplicate = StoreItem.query.filter(
            and_(StoreItem.name == name, StoreItem.id != item.id)
        ).first()
        if duplicate:
            return _reject('An item with this name already exists.')

        resolved_image, image_error = _resolve_item_image(
            request.form.get('image_url', '').strip()
        )
        if image_error:
            return _reject(image_error)

        # Every check passed -- now mutate, so the commit is all-or-nothing.
        item.name = name
        item.description = description
        item.category = category
        item.price = price_value
        item.is_active = is_active
        item.image_url = resolved_image
        item.available_colors = json.dumps(colors) if colors else None
        item.available_sizes = json.dumps(sizes) if sizes else None
        item.updated_at = datetime.utcnow()

        # Log the action
        changes = []
        for key, old_value in old_values.items():
            new_value = getattr(item, key)
            if old_value != new_value:
                changes.append(f"{key}: '{old_value}' -> '{new_value}'")

        if changes:
            AdminAuditLog.log_action(
                user_id=current_user.id,
                action='update_store_item',
                resource_type='store',
                resource_id=str(item.id),
                old_value=str(old_values),
                new_value=f"Updated: {'; '.join(changes)}",
                ip_address=request.remote_addr,
                user_agent=request.headers.get('User-Agent')
            )

        flash(f'Store item "{item.name}" updated successfully.', 'success')
        return redirect(url_for('admin_panel.store_items'))

    # GET request - show form
    return render_template('admin_panel/store/item_form_flowbite.html',
                         action='edit', item=item)


@admin_panel_bp.route('/store/items/<int:item_id>/delete', methods=['POST'])
@login_required
# Pub League Admin could delete items on the retired /store/admin page; keep that
# parity rather than silently narrowing it to Global Admin. This route still
# refuses when the item has orders, so it is strictly safer than the old one,
# which cascade-deleted the order history behind a trash icon.
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def delete_store_item(item_id):
    """Delete store item."""
    item = StoreItem.query.get_or_404(item_id)

    # Check if item has orders
    order_count = StoreOrder.query.filter_by(item_id=item.id).count()
    if order_count > 0:
        flash(f'Cannot delete item "{item.name}" - it has {order_count} associated orders. Consider deactivating instead.', 'error')
        return redirect(url_for('admin_panel.store_items'))

    item_name = item.name

    # Log the action before deletion
    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='delete_store_item',
        resource_type='store',
        resource_id=str(item.id),
        old_value=f"Deleted store item: {item_name}",
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    db.session.delete(item)

    flash(f'Store item "{item_name}" deleted successfully.', 'success')

    return redirect(url_for('admin_panel.store_items'))


@admin_panel_bp.route('/store/orders')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def store_orders():
    """Store orders management page."""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = 20
        
        # Build query with filters
        query = StoreOrder.query.join(StoreItem).join(User, StoreOrder.ordered_by == User.id)
        
        # Status filter
        status = request.args.get('status')
        if status and status != 'all':
            query = query.filter(StoreOrder.status == status)
        
        # Date range filter
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        if date_from:
            try:
                from_date = datetime.strptime(date_from, '%Y-%m-%d')
                query = query.filter(StoreOrder.order_date >= from_date)
            except ValueError:
                pass
        if date_to:
            try:
                to_date = datetime.strptime(date_to, '%Y-%m-%d')
                # Add one day to include the entire day
                to_date = to_date.replace(hour=23, minute=59, second=59)
                query = query.filter(StoreOrder.order_date <= to_date)
            except ValueError:
                pass
        
        # Search filter
        search = request.args.get('search', '').strip()
        if search:
            query = query.filter(or_(
                StoreItem.name.ilike(f'%{search}%'),
                User.username.ilike(f'%{search}%'),
                StoreOrder.selected_color.ilike(f'%{search}%'),
                StoreOrder.selected_size.ilike(f'%{search}%')
            ))
        
        # Order by
        order_by = request.args.get('order_by', 'order_date_desc')
        if order_by == 'order_date_desc':
            query = query.order_by(desc(StoreOrder.order_date))
        elif order_by == 'order_date_asc':
            query = query.order_by(StoreOrder.order_date)
        elif order_by == 'status':
            query = query.order_by(StoreOrder.status, desc(StoreOrder.order_date))
        elif order_by == 'item_name':
            query = query.order_by(StoreItem.name, desc(StoreOrder.order_date))
        elif order_by == 'orderer':
            query = query.order_by(User.username, desc(StoreOrder.order_date))
        
        orders = query.paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        # Get order statuses for filter dropdown
        order_statuses = list(ORDER_STATUSES)
        
        return render_template('admin_panel/store/orders_flowbite.html',
                             orders=orders,
                             order_statuses=order_statuses,
                             current_filters={
                                 'status': status or 'all',
                                 'date_from': date_from or '',
                                 'date_to': date_to or '',
                                 'search': search,
                                 'order_by': order_by
                             })
    except Exception as e:
        logger.error(f"Error loading store orders: {e}")
        flash('Store orders data unavailable. Verify database connection and order models.', 'error')
        return redirect(url_for('admin_panel.store_management'))


@admin_panel_bp.route('/store/orders/<int:order_id>/update-status', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def update_order_status(order_id):
    """Update order status."""
    order = StoreOrder.query.get_or_404(order_id)
    new_status = request.form.get('status')

    if new_status not in ORDER_STATUSES:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Invalid status.'}), 400
        flash('Invalid status.', 'error')
        return redirect(url_for('admin_panel.store_orders'))

    old_status = order.status
    order.status = new_status

    # Update timestamps based on status
    if new_status == 'PROCESSING' and old_status == 'PENDING':
        order.processed_date = datetime.utcnow()
        order.processed_by = current_user.id
    elif new_status == 'DELIVERED':
        order.delivered_date = datetime.utcnow()
        if not order.processed_by:
            order.processed_by = current_user.id

    # Log the action
    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='update_order_status',
        resource_type='store',
        resource_id=str(order.id),
        old_value=old_status,
        new_value=new_status,
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True,
                        'message': f'Order status updated from {old_status} to {new_status}.'})

    flash(f'Order status updated from {old_status} to {new_status}.', 'success')

    return redirect(url_for('admin_panel.store_orders'))


@admin_panel_bp.route('/store/orders/<int:order_id>/details')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def order_details(order_id):
    """Get order details via AJAX."""
    try:
        order = StoreOrder.query.get_or_404(order_id)
        
        details = {
            'id': order.id,
            'item_name': order.item.name if order.item else 'Unknown Item',
            'item_image': order.item.image_url if order.item else None,
            'orderer_name': order.orderer.username if order.orderer else 'Unknown User',
            'quantity': order.quantity,
            'selected_color': order.selected_color,
            'selected_size': order.selected_size,
            'notes': order.notes,
            'status': order.status,
            'order_date': order.order_date.strftime('%Y-%m-%d %H:%M:%S') if order.order_date else None,
            'processed_date': order.processed_date.strftime('%Y-%m-%d %H:%M:%S') if order.processed_date else None,
            'delivered_date': order.delivered_date.strftime('%Y-%m-%d %H:%M:%S') if order.delivered_date else None,
            'processor_name': order.processor.username if order.processor else None,
            'season_name': order.season.name if order.season else None
        }
        
        return jsonify({'success': True, 'order': details})
        
    except Exception as e:
        logger.error(f"Error getting order details: {e}")
        return jsonify({'success': False, 'message': 'Error retrieving order details'}), 500


@admin_panel_bp.route('/store/orders/<int:order_id>/reorder-grant', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def reorder_grant(order_id):
    """Let ONE coach place another order this season, without touching anyone else.

    Stamps eligibility_reset_at so the order stops counting against the
    one-order-per-season rule while keeping its season_id, its status and its
    place in the coach's history. Before this route existed the only lever was
    the all-or-nothing season reset -- and that reset had never actually run,
    because its confirm button lived in JavaScript that never initialised.
    """
    order = StoreOrder.query.get_or_404(order_id)
    data = request.get_json(silent=True) or {}
    allow = bool(data.get('allow', True))
    coach = order.orderer.username if order.orderer else f'user {order.ordered_by}'

    if allow:
        if order.eligibility_reset_at:
            return jsonify({'success': False,
                            'message': f'{coach} can already place another order this season.'}), 409
        order.eligibility_reset_at = datetime.utcnow()
        order.eligibility_reset_by = current_user.id
        message = (f'{coach} can now place another order this season. '
                   f'Order #{order.id} is unchanged.')
    else:
        if not order.eligibility_reset_at:
            return jsonify({'success': False,
                            'message': f'{coach} has no re-order permission to revoke.'}), 409
        if order.season_id is None:
            # `season_id = NULL` is never true in SQL, so the guard below would
            # be vacuous and this order never blocked anything anyway.
            return jsonify({'success': False,
                            'message': 'That order has no season, so it never blocked ordering.'}), 409
        # Revoking after the coach already used the grant would leave two live
        # orders and trip uq_store_orders_live_per_season as an opaque
        # IntegrityError. Refuse with an explanation instead.
        live = StoreOrder.query.filter(
            StoreOrder.ordered_by == order.ordered_by,
            StoreOrder.season_id == order.season_id,
            StoreOrder.eligibility_reset_at.is_(None),
            StoreOrder.id != order.id
        ).first()
        if live:
            return jsonify({
                'success': False,
                'message': (f'{coach} already placed order #{live.id} using this grant. '
                            f'Delete that order first if you want to revoke.')
            }), 409
        order.eligibility_reset_at = None
        order.eligibility_reset_by = None
        message = f'Re-order permission for {coach} revoked.'

    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='store_reorder_grant' if allow else 'store_reorder_revoke',
        resource_type='store',
        resource_id=str(order.id),
        old_value=coach,
        new_value=f'season {order.season_id}',
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    try:
        # The guard above is a check-then-write with no lock. Two revokes
        # confirmed at once each see the other as still reset, both pass, and
        # the second commit trips uq_store_orders_live_per_season. Catch it so
        # the admin gets the same explanation instead of a 500.
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'{coach} already has a live order for this season. Reload and try again.'
        }), 409

    return jsonify({'success': True, 'message': message})


@admin_panel_bp.route('/store/orders/<int:order_id>/delete', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def delete_store_order(order_id):
    """Permanently delete a single order. Audited -- this destroys data."""
    order = StoreOrder.query.get_or_404(order_id)
    describe = (f'#{order.id} {order.item.name if order.item else "Unknown Item"} '
                f'for {order.orderer.username if order.orderer else "Unknown"}')

    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='store_delete_order',
        resource_type='store',
        resource_id=str(order.id),
        old_value=describe,
        new_value='deleted',
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    db.session.delete(order)
    return jsonify({'success': True, 'message': f'Order {describe} deleted.'})


@admin_panel_bp.route('/store/orders/<int:order_id>/options', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def update_order_options(order_id):
    """Set an order's colour and size.

    Orders placed from the phone before the jsonb parsing fix carry no colour or
    size -- the app was served empty option lists, so there was nothing to pick,
    and the same bug suppressed the server-side requirement. Those orders cannot
    be fulfilled and nothing in the database can recover the intent, so an admin
    needs a way to record what the coach asks for without making them re-order.
    """
    order = StoreOrder.query.get_or_404(order_id)
    if not order.item:
        return jsonify({'success': False, 'message': 'That order has no item.'}), 409

    data = request.get_json(silent=True) or {}

    ok, message, color, size = validate_order_options(
        order.item, data.get('color'), data.get('size')
    )
    if not ok:
        return jsonify({'success': False, 'message': message}), 400

    before = f'{order.selected_color or "-"} / {order.selected_size or "-"}'
    order.selected_color = color
    order.selected_size = size
    after = f'{color or "-"} / {size or "-"}'

    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='store_update_order_options',
        resource_type='store',
        resource_id=str(order.id),
        old_value=before,
        new_value=after,
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    return jsonify({'success': True,
                    'message': f'Order #{order.id} set to {after}.'})


@admin_panel_bp.route('/store/orders/bulk-status', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def bulk_update_order_status():
    """Set the status on many orders at once."""
    data = request.get_json(silent=True) or {}
    order_ids = data.get('order_ids') or []
    new_status = (data.get('status') or '').strip().upper()

    if not order_ids:
        return jsonify({'success': False, 'message': 'No orders selected.'}), 400
    if new_status not in ORDER_STATUSES:
        return jsonify({'success': False, 'message': 'Invalid status.'}), 400

    orders = StoreOrder.query.filter(StoreOrder.id.in_(order_ids)).all()
    if not orders:
        return jsonify({'success': False, 'message': 'None of those orders exist.'}), 404

    now = datetime.utcnow()
    for order in orders:
        old_status = order.status
        order.status = new_status
        # Same timestamp rules as the single-order route, so a bulk update and a
        # one-off update leave identical rows.
        if new_status == 'PROCESSING' and old_status == 'PENDING':
            order.processed_date = now
            order.processed_by = current_user.id
        elif new_status == 'DELIVERED':
            order.delivered_date = now
            if not order.processed_by:
                order.processed_by = current_user.id

    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='store_bulk_update_order_status',
        resource_type='store',
        resource_id=','.join(str(o.id) for o in orders)[:255],
        old_value=f'{len(orders)} order(s)',
        new_value=new_status,
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    # Report what actually changed, not what was asked for: ids that do not
    # exist are silently absent from `orders`, and saying "5 updated" when 3
    # landed is the reports-success-does-nothing pattern this page is fixing.
    message = f'{len(orders)} order(s) set to {new_status}.'
    missing = len(order_ids) - len(orders)
    if missing > 0:
        message += f' {missing} selected order(s) no longer exist.'

    return jsonify({'success': True, 'message': message, 'updated': len(orders)})


@admin_panel_bp.route('/store/orders/bulk-delete', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def bulk_delete_orders():
    """Permanently delete many orders at once. Audited -- this destroys data."""
    data = request.get_json(silent=True) or {}
    order_ids = data.get('order_ids') or []

    if not order_ids:
        return jsonify({'success': False, 'message': 'No orders selected.'}), 400

    orders = StoreOrder.query.filter(StoreOrder.id.in_(order_ids)).all()
    if not orders:
        return jsonify({'success': False, 'message': 'None of those orders exist.'}), 404

    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='store_bulk_delete_orders',
        resource_type='store',
        resource_id=','.join(str(o.id) for o in orders)[:255],
        old_value=f'{len(orders)} order(s)',
        new_value='deleted',
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    for order in orders:
        db.session.delete(order)

    message = f'{len(orders)} order(s) deleted.'
    missing = len(order_ids) - len(orders)
    if missing > 0:
        message += f' {missing} selected order(s) no longer existed.'

    return jsonify({'success': True, 'message': message, 'deleted': len(orders)})


@admin_panel_bp.route('/store/orders/reset-season', methods=['POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def reset_season_ordering():
    """Let every coach order again for the current season -- non-destructively.

    Replaces the old /store/admin implementation, which had two modes and both
    lost data: 'all' hard-DELETEd every order for the season with no audit row,
    and 'eligibility' permanently set season_id = NULL despite a comment claiming
    it was temporary, which erased those orders from every season-scoped query
    and made them render a null season in my-orders forever.

    Both modes here keep every row and every season_id. The whole batch shares
    one timestamp, which is what makes the undo below a single UPDATE.
    """
    data = request.get_json(silent=True) or {}
    reset_type = (data.get('reset_type') or '').strip()

    if reset_type not in ('eligibility', 'cancel_and_reset'):
        return jsonify({'success': False, 'message': 'Invalid reset type.'}), 400

    current_season = get_current_store_season(db.session)
    if not current_season:
        return jsonify({'success': False, 'message': 'No current season found.'}), 400

    reset_at = datetime.utcnow()

    # Two different populations on purpose:
    #  * orders to STAMP  -- only ones still blocking (not already reset)
    #  * orders to CANCEL -- every open order for the season, including ones a
    #    previous per-coach grant already reset. Restricting the cancel to
    #    un-reset rows would leave a PENDING order from an earlier grant to be
    #    fulfilled, contradicting what the modal promises.
    season_orders = StoreOrder.query.filter(
        StoreOrder.season_id == current_season.id
    ).all()
    orders = [o for o in season_orders if o.eligibility_reset_at is None]

    for order in orders:
        order.eligibility_reset_at = reset_at
        order.eligibility_reset_by = current_user.id

    cancelled = 0
    if reset_type == 'cancel_and_reset':
        for order in season_orders:
            if order.status not in ('DELIVERED', 'CANCELLED'):
                order.status = 'CANCELLED'
                cancelled += 1

    AdminAuditLog.log_action(
        user_id=current_user.id,
        action='store_reset_season_ordering',
        resource_type='store',
        resource_id=str(current_season.id),
        old_value=f'{len(orders)} live order(s) in {current_season.name}',
        new_value=f'{reset_type} at {reset_at.isoformat()}',
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent')
    )

    message = (f'{len(orders)} order(s) in {current_season.name} were kept and marked reset. '
               f'Coaches may order again.')
    if cancelled:
        message += f' {cancelled} open order(s) marked CANCELLED.'

    return jsonify({
        'success': True,
        # One stamp for the batch, so the ELIGIBILITY half is reversible with:
        #   UPDATE store_orders SET eligibility_reset_at = NULL,
        #          eligibility_reset_by = NULL
        #    WHERE eligibility_reset_at = '<reset_token>';
        #
        # Two caveats, deliberately spelled out rather than implied:
        #  * it does NOT restore status. cancel_and_reset overwrites the old
        #    status in place and nothing records it, so CANCELLED is permanent.
        #  * it only works until someone re-orders -- once a coach has a new
        #    live order, un-stamping the old one trips
        #    uq_store_orders_live_per_season and the UPDATE aborts.
        'reset_token': reset_at.isoformat(),
        'undo_restores': 'eligibility only, and only until someone re-orders',
        'message': message
    })


@admin_panel_bp.route('/store/analytics')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def store_analytics():
    """Store analytics and reporting page."""
    try:
        # Date range for analysis (default: last 30 days)
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=30)
        
        # Custom date range from parameters
        custom_start = request.args.get('start_date')
        custom_end = request.args.get('end_date')
        if custom_start:
            try:
                start_date = datetime.strptime(custom_start, '%Y-%m-%d')
            except ValueError:
                pass
        if custom_end:
            try:
                end_date = datetime.strptime(custom_end, '%Y-%m-%d')
                end_date = end_date.replace(hour=23, minute=59, second=59)
            except ValueError:
                pass
        
        # Order statistics by status
        status_stats = db.session.query(
            StoreOrder.status,
            func.count(StoreOrder.id).label('count')
        ).filter(
            StoreOrder.order_date.between(start_date, end_date)
        ).group_by(StoreOrder.status).all()
        
        # Popular items
        popular_items = db.session.query(
            StoreItem.name,
            func.count(StoreOrder.id).label('total_orders'),
            func.sum(StoreOrder.quantity).label('total_quantity')
        ).join(StoreOrder).filter(
            StoreOrder.order_date.between(start_date, end_date)
        ).group_by(StoreItem.id, StoreItem.name)\
         .order_by(desc('total_orders')).limit(10).all()
        
        # Orders by day (for chart)
        daily_orders = db.session.query(
            func.date(StoreOrder.order_date).label('date'),
            func.count(StoreOrder.id).label('count')
        ).filter(
            StoreOrder.order_date.between(start_date, end_date)
        ).group_by(func.date(StoreOrder.order_date))\
         .order_by('date').all()
        
        # Category analysis
        category_stats = db.session.query(
            StoreItem.category,
            func.count(StoreOrder.id).label('order_count'),
            func.sum(StoreOrder.quantity).label('quantity_sum')
        ).join(StoreOrder).filter(
            and_(
                StoreOrder.order_date.between(start_date, end_date),
                StoreItem.category.isnot(None)
            )
        ).group_by(StoreItem.category).all()
        
        # Top customers
        top_customers = db.session.query(
            User.username,
            func.count(StoreOrder.id).label('order_count'),
            func.sum(StoreOrder.quantity).label('total_items')
        ).join(StoreOrder).filter(
            StoreOrder.order_date.between(start_date, end_date)
        ).group_by(User.id, User.username)\
         .order_by(desc('order_count')).limit(10).all()
        
        analytics_data = {
            'date_range': {
                'start': start_date.strftime('%Y-%m-%d'),
                'end': end_date.strftime('%Y-%m-%d')
            },
            'status_stats': dict(status_stats),
            'popular_items': [
                {
                    'name': name,
                    'orders': total_orders,
                    'quantity': total_quantity
                }
                for name, total_orders, total_quantity in popular_items
            ],
            'daily_orders': [
                {
                    'date': date.strftime('%Y-%m-%d'),
                    'count': count
                }
                for date, count in daily_orders
            ],
            'category_stats': [
                {
                    'category': category or 'Uncategorized',
                    'orders': order_count,
                    'quantity': quantity_sum
                }
                for category, order_count, quantity_sum in category_stats
            ],
            'top_customers': [
                {
                    'username': username,
                    'orders': order_count,
                    'items': total_items
                }
                for username, order_count, total_items in top_customers
            ]
        }
        
        return render_template('admin_panel/store/analytics_flowbite.html',
                             analytics=analytics_data)
        
    except Exception as e:
        logger.error(f"Error loading store analytics: {e}")
        flash('Store analytics unavailable. Verify database connection and analytics data.', 'error')
        return redirect(url_for('admin_panel.store_management'))


# API Endpoints for AJAX operations

@admin_panel_bp.route('/api/store/items', methods=['GET', 'POST'])
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
@transactional
def store_items_api():
    """Manage store items via API."""
    if request.method == 'GET':
        try:
            items = StoreItem.query.filter_by(is_active=True).all()
            return jsonify([{
                'id': item.id,
                'name': item.name,
                'description': item.description,
                'price': float(item.price) if item.price else 0,
                'category': item.category,
                'stock_quantity': getattr(item, 'stock_quantity', 0),
                'available_colors': item.color_options,
                'available_sizes': item.size_options,
                'created_at': item.created_at.isoformat()
            } for item in items])
        except Exception as e:
            logger.error(f"Error getting store items: {e}")
            return jsonify({'error': 'Failed to get store items'}), 500

    elif request.method == 'POST':
        data = request.get_json()

        item = StoreItem(
            name=data['name'],
            description=data.get('description', ''),
            price=data.get('price', 0),
            category=data.get('category', ''),
            available_colors=json.dumps(data.get('colors', [])),
            available_sizes=json.dumps(data.get('sizes', [])),
            created_by=current_user.id
        )

        db.session.add(item)

        # Log item creation
        AdminAuditLog.log_action(
            user_id=current_user.id,
            action='create_store_item',
            resource_type='store',
            resource_id=str(item.id),
            new_value=f"Created store item: {item.name}",
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent')
        )

        return jsonify({
            'success': True,
            'message': f'Item "{item.name}" created successfully',
            'item_id': item.id
        })


@admin_panel_bp.route('/api/store/orders')
@login_required
@role_required(['Global Admin', 'Pub League Admin'])
def store_orders_api():
    """Get store orders with filtering."""
    try:
        status_filter = request.args.get('status')
        query = StoreOrder.query.join(StoreItem).join(User, StoreOrder.ordered_by == User.id)
        
        if status_filter:
            query = query.filter(StoreOrder.status == status_filter)
            
        orders = query.order_by(StoreOrder.order_date.desc()).limit(50).all()
        
        return jsonify([{
            'id': order.id,
            'item_name': order.item.name,
            'orderer_name': order.orderer.username,
            'quantity': order.quantity,
            'selected_color': order.selected_color,
            'selected_size': order.selected_size,
            'status': order.status,
            'order_date': order.order_date.isoformat(),
            'notes': order.notes
        } for order in orders])
        
    except Exception as e:
        logger.error(f"Error getting store orders: {e}")
        return jsonify({'error': 'Failed to get orders'}), 500