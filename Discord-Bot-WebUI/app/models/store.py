# app/models/store.py

"""
Store Models Module

This module contains models related to the store system:
- StoreItem: Items available in the store
- StoreOrder: Orders placed in the store
"""

import json
import logging
from datetime import datetime

from app.core import db

logger = logging.getLogger(__name__)


def parse_option_list(raw):
    """Decode a store item's available_colors / available_sizes into a list.

    THE MODEL DECLARES THESE COLUMNS `db.Text`, BUT THE DATABASE HOLDS json/jsonb.
    psycopg2 typecasts json/jsonb by OID, so SQLAlchemy hands back an already
    decoded Python list -- not a string. `json.loads(a_list)` raises TypeError,
    and every read site used to swallow that into `[]`, so every JSON API
    reported that no item had any colours or sizes while the browser showed them
    fine (the Jinja `| replace("'", '\"') | fromjson` idiom stringifies the list,
    which round-trips by accident).

    So: accept the decoded list directly, a JSON string, or a Python-repr string
    (some rows were written that way). Never raise -- a bad value means "this
    item declares no options", which is the safe reading.
    """
    if raw is None:
        return []

    # json/jsonb column -> already decoded by the driver.
    if isinstance(raw, (list, tuple)):
        return [str(v) for v in raw if v is not None and str(v).strip()]
    if isinstance(raw, dict):
        logger.warning("Store item options are an object, expected an array: %r", raw)
        return []
    if not isinstance(raw, str):
        return []

    text = raw.strip()
    if not text:
        return []

    for candidate in (text, text.replace("'", '"')):
        try:
            value = json.loads(candidate)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if isinstance(value, (list, tuple)):
            return [str(v) for v in value if v is not None and str(v).strip()]
        return []

    logger.warning("Could not parse store item options: %r", raw)
    return []


class StoreItem(db.Model):
    """Model representing an item available in the mock store."""
    __tablename__ = 'store_items'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(500), nullable=True)
    available_colors = db.Column(db.Text, nullable=True)  # JSON string of available colors
    available_sizes = db.Column(db.Text, nullable=True)   # JSON string of available sizes
    category = db.Column(db.String(100), nullable=True)
    price = db.Column(db.Numeric(10, 2), nullable=True)  # For admin tracking only
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    # Relationships
    creator = db.relationship('User', backref=db.backref('created_store_items', lazy='dynamic'))
    orders = db.relationship('StoreOrder', back_populates='item', cascade='all, delete-orphan')
    
    @property
    def color_options(self):
        """Declared colours as a list. The ONE way to read this column."""
        return parse_option_list(self.available_colors)

    @property
    def size_options(self):
        """Declared sizes as a list. The ONE way to read this column."""
        return parse_option_list(self.available_sizes)

    def to_dict(self):
        colors = self.color_options
        sizes = self.size_options

        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'image_url': self.image_url,
            'available_colors': colors,
            'available_sizes': sizes,
            'category': self.category,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
    
    def __repr__(self):
        return f'<StoreItem {self.name}>'


class StoreOrder(db.Model):
    """Model representing an order placed in the mock store."""
    __tablename__ = 'store_orders'
    
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('store_items.id', ondelete='CASCADE'), nullable=False)
    ordered_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    quantity = db.Column(db.Integer, default=1, nullable=False)
    selected_color = db.Column(db.String(100), nullable=True)
    selected_size = db.Column(db.String(50), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(50), default='PENDING', nullable=False)  # PENDING, PROCESSING, ORDERED, DELIVERED, CANCELLED
    order_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    processed_date = db.Column(db.DateTime, nullable=True)
    delivered_date = db.Column(db.DateTime, nullable=True)
    processed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    season_id = db.Column(db.Integer, db.ForeignKey('season.id'), nullable=True)  # Track which season this order is for

    # Set when an admin grants a re-order. The order KEEPS its season_id -- so it
    # stays in season reporting and in the coach's history -- it just stops
    # counting against the one-order-per-season rule. The old reset achieved the
    # same unblocking by nulling season_id, which destroyed the attribution
    # permanently despite the code comment claiming it was temporary.
    eligibility_reset_at = db.Column(db.DateTime, nullable=True)
    eligibility_reset_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)

    # A coach may hold any number of historical orders for a season, but only one
    # LIVE one. This is the backstop for the check-then-insert in
    # app/store_helpers.check_order_eligibility, which cannot cover a web POST
    # racing a mobile POST. Name must match sql_store_season_ordering.sql exactly.
    # sqlite_where is declared alongside postgresql_where on purpose: the test
    # suite runs on SQLite, and a dialect that ignores the predicate would build a
    # FULL unique index instead -- silently forbidding the very re-orders this
    # column exists to allow, and only in tests.
    __table_args__ = (
        db.Index(
            'uq_store_orders_live_per_season',
            'ordered_by', 'season_id',
            unique=True,
            postgresql_where=db.text('season_id IS NOT NULL AND eligibility_reset_at IS NULL'),
            sqlite_where=db.text('season_id IS NOT NULL AND eligibility_reset_at IS NULL'),
        ),
    )

    # Relationships - passive_deletes=True trusts DB's ON DELETE CASCADE
    item = db.relationship('StoreItem', back_populates='orders', passive_deletes=True)
    orderer = db.relationship('User', foreign_keys=[ordered_by], backref=db.backref('store_orders', lazy='dynamic', passive_deletes=True), passive_deletes=True)
    processor = db.relationship('User', foreign_keys=[processed_by], backref=db.backref('processed_orders', lazy='dynamic'))
    season = db.relationship('Season', backref=db.backref('store_orders', lazy='dynamic'))
    
    def to_dict(self):
        return {
            'id': self.id,
            'item_id': self.item_id,
            'item_name': self.item.name if self.item else 'Unknown Item',
            'ordered_by': self.ordered_by,
            'orderer_name': self.orderer.username if self.orderer else 'Unknown User',
            'quantity': self.quantity,
            'selected_color': self.selected_color,
            'selected_size': self.selected_size,
            'notes': self.notes,
            'status': self.status,
            'order_date': self.order_date.isoformat() if self.order_date else None,
            'processed_date': self.processed_date.isoformat() if self.processed_date else None,
            'delivered_date': self.delivered_date.isoformat() if self.delivered_date else None,
            'eligibility_reset_at': self.eligibility_reset_at.isoformat() if self.eligibility_reset_at else None
        }
    
    def __repr__(self):
        return f'<StoreOrder {self.id}: {self.item.name if self.item else "Unknown"} by {self.orderer.username if self.orderer else "Unknown"}>'