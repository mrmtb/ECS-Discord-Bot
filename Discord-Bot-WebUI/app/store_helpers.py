# app/store_helpers.py

"""
Store Eligibility Helpers

ONE definition of "which season does the store order against" and "may this
person order". Before this module the rule lived in five places -- three in
app/store.py and two in app/mobile_api/store.py -- and they had already drifted:
the web form demanded a colour and a size for every item and posted the
sentinels 'N/A' / 'One Size' when an item declared none, while mobile wrote
NULL. The same item ordered from a browser and from the phone produced
different rows.

This module imports models only -- no blueprint -- so app/mobile_api/store.py
can import it without the circular import that pulling in app.store would cause.
"""

import logging

from app.models import Season, StoreOrder
from app.models.store import parse_option_list

logger = logging.getLogger(__name__)

# The store orders against the Pub League season. Summer ('PL Third') and
# ECS FC seasons do not carry a gear order cycle.
STORE_LEAGUE_TYPE = 'Pub League'


def get_current_store_season(session):
    """
    Resolve the season the store is currently ordering against.

    This is the only place that query lives. Returns None when no Pub League
    season is flagged current, which every caller must handle -- ordering is
    blocked rather than silently attributed to the wrong season.
    """
    return session.query(Season).filter_by(
        league_type=STORE_LEAGUE_TYPE,
        is_current=True
    ).first()


def get_blocking_order(session, user_id, season):
    """
    Return the order preventing user_id from ordering in `season`, or None.

    An order with eligibility_reset_at set keeps its season_id -- and therefore
    stays in season reporting and in the coach's history -- but no longer
    blocks. That is the entire point of the column: the old reset achieved the
    same unblocking by nulling season_id, which destroyed the attribution.
    """
    if not season:
        return None

    return session.query(StoreOrder).filter(
        StoreOrder.ordered_by == user_id,
        StoreOrder.season_id == season.id,
        StoreOrder.eligibility_reset_at.is_(None)
    ).first()


def check_order_eligibility(session, user_id, season=None):
    """
    Decide whether user_id may place an order.

    Returns (eligible, reason, season, blocking_order). `reason` is the
    user-facing message and is None when eligible. The wording is preserved
    verbatim from the previous inline copies so the Flutter app's existing
    strings keep matching.
    """
    season = season or get_current_store_season(session)

    if not season:
        return False, 'No current season found. Cannot place order.', None, None

    blocking = get_blocking_order(session, user_id, season)
    if blocking:
        return (
            False,
            f'You have already placed an order this season ({season.name}). '
            f'Only one order per season is allowed.',
            season,
            blocking
        )

    return True, None, season, None


def parse_item_options(raw):
    """Decode a store item's declared options. Delegates to the one parser.

    Kept as a thin alias so callers here read naturally; the real implementation
    (and the explanation of why the column comes back as a list) lives on the
    model in app/models/store.py.
    """
    return parse_option_list(raw)


def validate_order_options(item, color, size):
    """
    Validate a colour/size selection against what the item actually offers.

    Returns (ok, message, color, size). A choice is required only when the item
    declares options, and must be one of them. Items with no options yield None
    for that field, so a browser order and a phone order write identical rows --
    no more 'N/A' / 'One Size' sentinels.
    """
    color = (color or '').strip()
    size = (size or '').strip()

    colors = parse_item_options(item.available_colors)
    if colors:
        if not color:
            return False, 'Color selection is required for this item.', None, None
        if color not in colors:
            return False, f"Invalid color. Available: {', '.join(colors)}", None, None
    else:
        color = ''

    sizes = parse_item_options(item.available_sizes)
    if sizes:
        if not size:
            return False, 'Size selection is required for this item.', None, None
        if size not in sizes:
            return False, f"Invalid size. Available: {', '.join(sizes)}", None, None
    else:
        size = ''

    return True, None, (color or None), (size or None)
