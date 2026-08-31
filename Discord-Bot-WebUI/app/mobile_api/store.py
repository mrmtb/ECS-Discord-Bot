# app/mobile_api/store.py

"""
Mobile API Store Endpoints

Provides league store functionality for mobile clients:
- Browse store items
- Place orders
- View order history
- Check ordering eligibility
"""

import json
import logging
from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.mobile_api import mobile_api_v2
from app.decorators import jwt_role_required
from app.core.session_manager import managed_session
from app.models import User, StoreItem, StoreOrder
from app.store_helpers import check_order_eligibility, validate_order_options

logger = logging.getLogger(__name__)


@mobile_api_v2.route('/store/items', methods=['GET'])
@jwt_required()
@jwt_role_required(['Pub League Coach', 'Pub League Admin', 'Global Admin'])
def get_store_items():
    """
    Get all active store items.

    Query Parameters:
        category: Filter by category (optional)

    Returns:
        JSON with list of store items
    """
    category = request.args.get('category', '').strip()

    with managed_session() as session:
        query = session.query(StoreItem).filter(StoreItem.is_active == True)

        if category:
            query = query.filter(StoreItem.category == category)

        query = query.order_by(StoreItem.category, StoreItem.name)
        items = query.all()

        items_data = []
        for item in items:
            # The column comes back already decoded (json/jsonb), so json.loads()
            # here raised TypeError and this endpoint reported EVERY item as
            # having no colours and no sizes. See parse_option_list().
            colors = item.color_options
            sizes = item.size_options

            items_data.append({
                "id": item.id,
                "name": item.name,
                "description": item.description,
                "image_url": item.image_url,
                "category": item.category,
                "price": float(item.price) if item.price else None,
                "available_colors": colors,
                "available_sizes": sizes,
                "is_active": item.is_active
            })

        # Get unique categories for filtering
        categories = list(set(item.category for item in items if item.category))

        return jsonify({
            "items": items_data,
            "categories": sorted(categories),
            "total": len(items_data)
        }), 200


@mobile_api_v2.route('/store/items/<int:item_id>', methods=['GET'])
@jwt_required()
@jwt_role_required(['Pub League Coach', 'Pub League Admin', 'Global Admin'])
def get_store_item(item_id: int):
    """
    Get details for a specific store item.

    Args:
        item_id: Store item ID

    Returns:
        JSON with item details
    """
    with managed_session() as session:
        item = session.query(StoreItem).get(item_id)

        if not item:
            return jsonify({"msg": "Store item not found"}), 404

        # Already-decoded column -- see parse_option_list().
        colors = item.color_options
        sizes = item.size_options

        return jsonify({
            "item": {
                "id": item.id,
                "name": item.name,
                "description": item.description,
                "image_url": item.image_url,
                "category": item.category,
                "price": float(item.price) if item.price else None,
                "available_colors": colors,
                "available_sizes": sizes,
                "is_active": item.is_active
            }
        }), 200


@mobile_api_v2.route('/store/eligibility', methods=['GET'])
@jwt_required()
@jwt_role_required(['Pub League Coach', 'Pub League Admin', 'Global Admin'])
def check_store_eligibility():
    """
    Check if the current user is eligible to place an order this season.

    Returns:
        JSON with eligibility status and current season info
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        # Shared with the web store -- see app/store_helpers.py. An order an admin
        # has granted a re-order on keeps its season_id but stops blocking here,
        # so the app becomes eligible again with no client change.
        eligible, reason, current_season, blocking_order = check_order_eligibility(
            session, current_user_id
        )

        if not current_season:
            return jsonify({
                "eligible": False,
                "reason": "No current season found",
                "season": None
            }), 200

        season_payload = {
            "id": current_season.id,
            "name": current_season.name
        }

        if blocking_order:
            return jsonify({
                "eligible": False,
                "reason": reason,
                "season": season_payload,
                "existing_order": {
                    "id": blocking_order.id,
                    "item_id": blocking_order.item_id,
                    "status": blocking_order.status,
                    "order_date": blocking_order.order_date.isoformat() if blocking_order.order_date else None
                }
            }), 200

        return jsonify({
            "eligible": True,
            "reason": None,
            "season": season_payload,
            "existing_order": None
        }), 200


@mobile_api_v2.route('/store/orders', methods=['POST'])
@jwt_required()
@jwt_role_required(['Pub League Coach', 'Pub League Admin', 'Global Admin'])
def place_order():
    """
    Place an order for a store item.

    Expected JSON:
        item_id: ID of the store item to order
        quantity: Number of items (default: 1)
        color: Selected color (required if item has colors)
        size: Selected size (required if item has sizes)
        notes: Optional notes

    Returns:
        JSON with order confirmation
    """
    current_user_id = int(get_jwt_identity())

    data = request.get_json()
    if not data:
        return jsonify({"msg": "Missing request data"}), 400

    item_id = data.get('item_id')
    quantity = data.get('quantity', 1)
    # Raw, not pre-stripped: a client sending an explicit null used to raise
    # AttributeError here. validate_order_options() handles None.
    color = data.get('color')
    size = data.get('size')
    notes = (data.get('notes') or '').strip()

    if not item_id:
        return jsonify({"msg": "item_id is required"}), 400

    try:
        quantity = int(quantity)
        if quantity < 1:
            return jsonify({"msg": "Quantity must be at least 1"}), 400
    except (ValueError, TypeError):
        return jsonify({"msg": "Invalid quantity"}), 400

    with managed_session() as session:
        # Get the item
        item = session.query(StoreItem).get(item_id)
        if not item:
            return jsonify({"msg": "Store item not found"}), 404

        if not item.is_active:
            return jsonify({"msg": "This item is no longer available"}), 400

        # Same eligibility rule as the web store -- see app/store_helpers.py.
        eligible, reason, current_season, _blocking = check_order_eligibility(
            session, current_user_id
        )
        if not current_season:
            return jsonify({"msg": "No current season found. Cannot place order."}), 400
        if not eligible:
            return jsonify({"msg": reason}), 400

        # Same colour/size rule as the web store: required only when the item
        # declares options, and validated against them.
        ok, message, selected_color, selected_size = validate_order_options(item, color, size)
        if not ok:
            return jsonify({"msg": message}), 400

        # Create order
        order = StoreOrder(
            item_id=item_id,
            ordered_by=current_user_id,
            quantity=quantity,
            selected_color=selected_color,
            selected_size=selected_size,
            notes=notes if notes else None,
            season_id=current_season.id
        )

        session.add(order)
        try:
            session.commit()
        except IntegrityError:
            # uq_store_orders_live_per_season -- a phone POST racing a browser
            # POST. Answer with the message the check above would have given
            # rather than a 500.
            session.rollback()
            logger.info(f"Duplicate store order blocked for user {current_user_id}")
            return jsonify({
                "msg": f"You have already placed an order this season ({current_season.name}). Only one order per season is allowed."
            }), 400

        logger.info(f"Order placed for item '{item.name}' by user {current_user_id}")

        return jsonify({
            "success": True,
            "message": f"Order placed successfully for {quantity}x {item.name}",
            "order": {
                "id": order.id,
                "item_id": order.item_id,
                "item_name": item.name,
                "quantity": order.quantity,
                "color": order.selected_color,
                "size": order.selected_size,
                "status": order.status,
                "order_date": order.order_date.isoformat() if order.order_date else None
            }
        }), 201


@mobile_api_v2.route('/store/my-orders', methods=['GET'])
@jwt_required()
@jwt_role_required(['Pub League Coach', 'Pub League Admin', 'Global Admin'])
def get_my_orders():
    """
    Get the current user's order history.

    Returns:
        JSON with list of orders
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        orders = session.query(StoreOrder).options(
            selectinload(StoreOrder.item),
            selectinload(StoreOrder.season)
        ).filter(
            StoreOrder.ordered_by == current_user_id
        ).order_by(StoreOrder.order_date.desc()).all()

        orders_data = []
        for order in orders:
            orders_data.append({
                "id": order.id,
                "item": {
                    "id": order.item.id,
                    "name": order.item.name,
                    "image_url": order.item.image_url
                } if order.item else None,
                "quantity": order.quantity,
                "color": order.selected_color,
                "size": order.selected_size,
                "status": order.status,
                "notes": order.notes,
                "order_date": order.order_date.isoformat() if order.order_date else None,
                "processed_date": order.processed_date.isoformat() if order.processed_date else None,
                "delivered_date": order.delivered_date.isoformat() if order.delivered_date else None,
                "season": {
                    "id": order.season.id,
                    "name": order.season.name
                } if order.season else None
            })

        return jsonify({
            "orders": orders_data,
            "total": len(orders_data)
        }), 200


@mobile_api_v2.route('/store/orders/<int:order_id>', methods=['GET'])
@jwt_required()
@jwt_role_required(['Pub League Coach', 'Pub League Admin', 'Global Admin'])
def get_order_detail(order_id: int):
    """
    Get details for a specific order.

    Args:
        order_id: Order ID

    Returns:
        JSON with order details
    """
    current_user_id = int(get_jwt_identity())

    with managed_session() as session:
        # Get user to check role
        user = session.query(User).options(
            selectinload(User.roles)
        ).get(current_user_id)

        if not user:
            return jsonify({"msg": "User not found"}), 404

        user_roles = [role.name for role in user.roles]
        is_admin = any(r in ['Global Admin', 'Pub League Admin'] for r in user_roles)

        # Get order
        order = session.query(StoreOrder).options(
            selectinload(StoreOrder.item),
            selectinload(StoreOrder.season),
            selectinload(StoreOrder.orderer),
            selectinload(StoreOrder.processor)
        ).get(order_id)

        if not order:
            return jsonify({"msg": "Order not found"}), 404

        # Check authorization - user can only view their own orders unless admin
        if order.ordered_by != current_user_id and not is_admin:
            return jsonify({"msg": "Not authorized to view this order"}), 403

        return jsonify({
            "order": {
                "id": order.id,
                "item": {
                    "id": order.item.id,
                    "name": order.item.name,
                    "description": order.item.description,
                    "image_url": order.item.image_url,
                    "price": float(order.item.price) if order.item.price else None
                } if order.item else None,
                "quantity": order.quantity,
                "color": order.selected_color,
                "size": order.selected_size,
                "status": order.status,
                "notes": order.notes,
                "order_date": order.order_date.isoformat() if order.order_date else None,
                "processed_date": order.processed_date.isoformat() if order.processed_date else None,
                "delivered_date": order.delivered_date.isoformat() if order.delivered_date else None,
                "ordered_by": {
                    "id": order.orderer.id,
                    "username": order.orderer.username
                } if order.orderer else None,
                "processed_by": {
                    "id": order.processor.id,
                    "username": order.processor.username
                } if order.processor else None,
                "season": {
                    "id": order.season.id,
                    "name": order.season.name
                } if order.season else None
            }
        }), 200
