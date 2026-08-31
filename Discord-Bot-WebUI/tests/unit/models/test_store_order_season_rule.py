"""
Store order / season-eligibility integration tests.

These run against the real StoreOrder mapping and a real database session, so
they cover the two things unit-level fakes cannot:

  * the partial unique index actually rejects a second LIVE order for the same
    coach and season, and actually PERMITS one once the first is reset -- this
    is the backstop for a browser POST racing a phone POST, which the
    check-then-insert in app/store_helpers.py cannot cover on its own;
  * an eligibility reset unblocks ordering while KEEPING season_id. The
    implementation this replaced unblocked by setting season_id = NULL, which
    dropped the order out of every season-scoped query permanently.
"""
import pytest
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from app.models import Season, StoreItem, StoreOrder
from app.store_helpers import (
    check_order_eligibility,
    get_blocking_order,
    get_current_store_season,
)


@pytest.fixture
def pub_league_season(db):
    """The store orders against the current PUB LEAGUE season specifically."""
    season = Season(name='2026 Fall', league_type='Pub League', is_current=True)
    db.session.add(season)
    db.session.flush()
    return season


@pytest.fixture
def store_item(db, user):
    item = StoreItem(
        name='Coach Pullover',
        category='Apparel',
        is_active=True,
        created_by=user.id,
    )
    db.session.add(item)
    db.session.flush()
    return item


def _order(db, item, user, season, **kwargs):
    order = StoreOrder(
        item_id=item.id,
        ordered_by=user.id,
        quantity=1,
        season_id=season.id if season else None,
        **kwargs
    )
    db.session.add(order)
    db.session.flush()
    return order


# =============================================================================
# Season resolution
# =============================================================================

def test_current_store_season_ignores_other_league_types(db, pub_league_season):
    """A current Summer ('PL Third') or ECS FC season must not be picked up."""
    db.session.add(Season(name='2026 Summer Sprint', league_type='PL Third', is_current=True))
    db.session.add(Season(name='ECS FC', league_type='ECS FC', is_current=True))
    db.session.flush()

    assert get_current_store_season(db.session).id == pub_league_season.id


# =============================================================================
# The rule the coach and the app both see
# =============================================================================

def test_first_order_is_allowed_then_blocks_the_second(db, store_item, user, pub_league_season):
    eligible, reason, season, blocking = check_order_eligibility(db.session, user.id)
    assert eligible is True and blocking is None and season.id == pub_league_season.id

    _order(db, store_item, user, pub_league_season)

    eligible, reason, season, blocking = check_order_eligibility(db.session, user.id)
    assert eligible is False
    assert blocking is not None
    assert '2026 Fall' in reason


def test_reset_unblocks_ordering_and_keeps_the_season(db, store_item, user, pub_league_season):
    """The whole point of eligibility_reset_at: unblock WITHOUT losing history."""
    order = _order(db, store_item, user, pub_league_season)
    assert check_order_eligibility(db.session, user.id)[0] is False

    order.eligibility_reset_at = datetime.utcnow()
    db.session.flush()

    eligible, reason, _season, blocking = check_order_eligibility(db.session, user.id)
    assert eligible is True
    assert reason is None
    assert blocking is None

    # ...and the order is still attributed to its season, still in history.
    db.session.refresh(order)
    assert order.season_id == pub_league_season.id
    assert order.season.name == '2026 Fall'
    assert get_blocking_order(db.session, user.id, pub_league_season) is None


def test_reset_order_does_not_block_a_new_live_order(db, store_item, user, pub_league_season):
    reset = _order(db, store_item, user, pub_league_season,
                   eligibility_reset_at=datetime.utcnow())
    fresh = _order(db, store_item, user, pub_league_season)
    db.session.commit()

    assert reset.season_id == fresh.season_id == pub_league_season.id
    assert get_blocking_order(db.session, user.id, pub_league_season).id == fresh.id


# =============================================================================
# The database backstop
# =============================================================================

def test_two_live_orders_for_one_coach_and_season_are_rejected(
        db, store_item, user, pub_league_season):
    """The race a check-then-insert cannot close: web POST vs mobile POST."""
    _order(db, store_item, user, pub_league_season)
    db.session.commit()

    with pytest.raises(IntegrityError):
        _order(db, store_item, user, pub_league_season)
        db.session.commit()

    db.session.rollback()


def test_orders_without_a_season_are_exempt_from_the_index(
        db, store_item, user, pub_league_season):
    """Legacy rows the old reset orphaned have season_id NULL and must not
    collide with each other -- the index predicate excludes them."""
    _order(db, store_item, user, None)
    _order(db, store_item, user, None)
    db.session.commit()

    assert db.session.query(StoreOrder).filter(
        StoreOrder.season_id.is_(None)
    ).count() == 2
