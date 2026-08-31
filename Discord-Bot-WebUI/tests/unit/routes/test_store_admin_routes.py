"""
Store admin route tests.

The bug these exist to prevent: on the page these routes replace, every button
was wired to JavaScript that never ran, so "Reset Season Ordering" and the item
menu did nothing at all -- silently, with an empty console. Nothing in the suite
noticed, because nothing exercised the endpoints.

So these drive the real routes through the test client and assert on what
actually changed in the database, not just on a 200.
"""
import pytest
from datetime import datetime

from app.models import Role, Season, StoreItem, StoreOrder, User


@pytest.fixture
def global_admin(db):
    role = db.session.query(Role).filter_by(name='Global Admin').first()
    if not role:
        role = Role(name='Global Admin', description='Global Administrator')
        db.session.add(role)
        db.session.flush()

    admin = User(username='store_admin', email='store_admin@example.com',
                 is_approved=True)
    admin.set_password('password123')
    admin.roles.append(role)
    db.session.add(admin)
    db.session.flush()
    return admin


@pytest.fixture
def admin_session(client, global_admin, db):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(global_admin.id)
        sess['_fresh'] = True
    return client


@pytest.fixture
def pub_league_season(db):
    season = Season(name='2026 Fall', league_type='Pub League', is_current=True)
    db.session.add(season)
    db.session.flush()
    return season


@pytest.fixture
def coach_order(db, global_admin, pub_league_season):
    item = StoreItem(name='Coach Pullover', is_active=True, created_by=global_admin.id)
    db.session.add(item)
    db.session.flush()

    coach = User(username='a_coach', email='a_coach@example.com', is_approved=True)
    coach.set_password('password123')
    db.session.add(coach)
    db.session.flush()

    order = StoreOrder(item_id=item.id, ordered_by=coach.id, quantity=1,
                       season_id=pub_league_season.id, status='PENDING')
    db.session.add(order)
    db.session.commit()
    return order


# =============================================================================
# Per-coach re-order grant -- the lever that unblocks ONE person
# =============================================================================

def test_allow_reorder_stamps_the_order_and_keeps_its_season(admin_session, db, coach_order):
    season_id, order_id = coach_order.season_id, coach_order.id

    resp = admin_session.post(f'/admin-panel/store/orders/{order_id}/reorder-grant',
                              json={'allow': True})

    assert resp.status_code == 200, resp.data[:400]
    assert resp.get_json()['success'] is True

    db.session.expire_all()
    order = db.session.get(StoreOrder, order_id)
    assert order is not None, 'the order must be KEPT, not deleted'
    assert order.eligibility_reset_at is not None
    assert order.eligibility_reset_by is not None
    assert order.season_id == season_id, 'season attribution must survive the grant'
    assert order.status == 'PENDING', 'granting a re-order must not alter the order'


def test_allow_reorder_twice_is_rejected(admin_session, db, coach_order):
    order_id = coach_order.id
    admin_session.post(f'/admin-panel/store/orders/{order_id}/reorder-grant',
                       json={'allow': True})

    resp = admin_session.post(f'/admin-panel/store/orders/{order_id}/reorder-grant',
                              json={'allow': True})

    assert resp.status_code == 409
    assert resp.get_json()['success'] is False


def test_revoke_is_refused_once_the_grant_has_been_used(admin_session, db, coach_order):
    """Otherwise revoking would leave two live orders and trip the unique index
    as an opaque IntegrityError."""
    order_id, coach_id, season_id, item_id = (
        coach_order.id, coach_order.ordered_by, coach_order.season_id, coach_order.item_id)

    admin_session.post(f'/admin-panel/store/orders/{order_id}/reorder-grant',
                       json={'allow': True})
    db.session.add(StoreOrder(item_id=item_id, ordered_by=coach_id, quantity=1,
                              season_id=season_id, status='PENDING'))
    db.session.commit()

    resp = admin_session.post(f'/admin-panel/store/orders/{order_id}/reorder-grant',
                              json={'allow': False})

    assert resp.status_code == 409
    assert 'already placed order' in resp.get_json()['message']


# =============================================================================
# Season-wide reset -- must never destroy anything
# =============================================================================

def test_season_reset_keeps_every_order_and_its_season(admin_session, db, coach_order):
    order_id, season_id = coach_order.id, coach_order.season_id

    resp = admin_session.post('/admin-panel/store/orders/reset-season',
                              json={'reset_type': 'eligibility'})

    assert resp.status_code == 200, resp.data[:400]
    body = resp.get_json()
    assert body['success'] is True
    # Shared batch stamp -- this is what makes the reset undoable in one UPDATE.
    assert body['reset_token']

    db.session.expire_all()
    order = db.session.get(StoreOrder, order_id)
    assert order is not None, 'reset must not delete orders'
    assert order.season_id == season_id, 'reset must not null season_id'
    assert order.eligibility_reset_at is not None
    assert order.status == 'PENDING'
    assert '[ELIGIBILITY RESET' not in (order.notes or ''), 'notes must not be scribbled on'


def test_cancel_and_reset_cancels_without_deleting(admin_session, db, coach_order):
    order_id = coach_order.id

    resp = admin_session.post('/admin-panel/store/orders/reset-season',
                              json={'reset_type': 'cancel_and_reset'})

    assert resp.status_code == 200
    db.session.expire_all()
    order = db.session.get(StoreOrder, order_id)
    assert order is not None
    assert order.status == 'CANCELLED'
    assert order.eligibility_reset_at is not None


def test_season_reset_rejects_an_unknown_mode(admin_session, db, pub_league_season):
    resp = admin_session.post('/admin-panel/store/orders/reset-season',
                              json={'reset_type': 'all'})

    assert resp.status_code == 400
    assert resp.get_json()['success'] is False


def test_season_reset_with_no_body_does_not_500(admin_session, db, pub_league_season):
    """request.get_json() raises before a falsy check in Flask 3; the route must
    use silent=True or a bodyless POST becomes an HTML 500 that the front end
    reports as a generic 'error occurred'."""
    resp = admin_session.post('/admin-panel/store/orders/reset-season')

    assert resp.status_code == 400
    assert resp.get_json()['success'] is False


# =============================================================================
# Retired /store/admin surface
# =============================================================================

def test_store_admin_redirects_to_the_admin_panel(admin_session, db):
    resp = admin_session.get('/store/admin')

    assert resp.status_code == 302
    assert '/admin-panel/store' in resp.headers['Location']


def test_retired_mutating_route_answers_gone_instead_of_pretending(admin_session, db):
    """A silent redirect on a POST would look like success and do nothing --
    which is precisely the failure being fixed."""
    resp = admin_session.post('/store/admin/reset-season-ordering',
                              json={'reset_type': 'eligibility'})

    assert resp.status_code == 410
    body = resp.get_json()
    assert body['success'] is False
    assert '/admin-panel/store' in body['moved_to']


def test_delete_order_removes_it(admin_session, db, coach_order):
    """The one route that destroys data had no test at all."""
    order_id = coach_order.id

    resp = admin_session.post(f'/admin-panel/store/orders/{order_id}/delete')

    assert resp.status_code == 200, resp.data[:400]
    assert resp.get_json()['success'] is True
    db.session.expire_all()
    assert db.session.get(StoreOrder, order_id) is None


def test_revoke_succeeds_when_the_grant_was_not_used(admin_session, db, coach_order):
    order_id = coach_order.id
    admin_session.post(f'/admin-panel/store/orders/{order_id}/reorder-grant',
                       json={'allow': True})

    resp = admin_session.post(f'/admin-panel/store/orders/{order_id}/reorder-grant',
                              json={'allow': False})

    assert resp.status_code == 200, resp.data[:400]
    db.session.expire_all()
    order = db.session.get(StoreOrder, order_id)
    assert order.eligibility_reset_at is None
    assert order.eligibility_reset_by is None


def test_cancel_and_reset_also_cancels_an_already_granted_order(admin_session, db, coach_order):
    """A per-coach grant must not exempt an open order from the season cancel --
    otherwise it stays PENDING and gets fulfilled anyway."""
    order_id = coach_order.id
    admin_session.post(f'/admin-panel/store/orders/{order_id}/reorder-grant',
                       json={'allow': True})

    resp = admin_session.post('/admin-panel/store/orders/reset-season',
                              json={'reset_type': 'cancel_and_reset'})

    assert resp.status_code == 200, resp.data[:400]
    db.session.expire_all()
    assert db.session.get(StoreOrder, order_id).status == 'CANCELLED'


def test_retired_edit_item_post_is_gone_not_redirected(admin_session, db):
    """A 302 would make the browser re-issue the edit as a GET and drop it."""
    resp = admin_session.post('/store/admin/item/1/edit', data={'name': 'X'})

    assert resp.status_code == 410
    assert resp.get_json()['success'] is False


# =============================================================================
# Colour / size repair -- the gap that made phone orders unfulfillable
# =============================================================================

@pytest.fixture
def optioned_order(db, global_admin, pub_league_season):
    """An order with NO colour/size on an item that declares both -- exactly what
    the phone produced while the API served empty option lists."""
    item = StoreItem(name='Maxum Pant', is_active=True, created_by=global_admin.id,
                     available_colors='["Navy", "Black"]',
                     available_sizes='["AS", "AM", "AL"]')
    db.session.add(item); db.session.flush()

    coach = User(username='opt_coach', email='opt_coach@example.com', is_approved=True)
    coach.set_password('password123')
    db.session.add(coach); db.session.flush()

    order = StoreOrder(item_id=item.id, ordered_by=coach.id, quantity=1,
                       season_id=pub_league_season.id, status='PENDING')
    db.session.add(order); db.session.commit()
    return order


def test_admin_can_set_a_missing_colour_and_size(admin_session, db, optioned_order):
    order_id = optioned_order.id

    resp = admin_session.post(f'/admin-panel/store/orders/{order_id}/options',
                              json={'color': 'Navy', 'size': 'AM'})

    assert resp.status_code == 200, resp.data[:400]
    db.session.expire_all()
    order = db.session.get(StoreOrder, order_id)
    assert (order.selected_color, order.selected_size) == ('Navy', 'AM')


def test_admin_cannot_set_an_option_the_item_does_not_offer(admin_session, db, optioned_order):
    resp = admin_session.post(f'/admin-panel/store/orders/{optioned_order.id}/options',
                              json={'color': 'Chartreuse', 'size': 'AM'})

    assert resp.status_code == 400
    assert 'Available: Navy, Black' in resp.get_json()['message']


# =============================================================================
# Bulk operations
# =============================================================================

def test_bulk_status_updates_every_selected_order(admin_session, db, coach_order, optioned_order):
    ids = [coach_order.id, optioned_order.id]

    resp = admin_session.post('/admin-panel/store/orders/bulk-status',
                              json={'order_ids': ids, 'status': 'ORDERED'})

    assert resp.status_code == 200, resp.data[:400]
    assert resp.get_json()['updated'] == 2
    db.session.expire_all()
    assert all(db.session.get(StoreOrder, i).status == 'ORDERED' for i in ids)


def test_bulk_status_reports_ids_that_no_longer_exist(admin_session, db, coach_order):
    """Saying "2 updated" when 1 landed is the failure mode this page exists to fix."""
    resp = admin_session.post('/admin-panel/store/orders/bulk-status',
                              json={'order_ids': [coach_order.id, 999999], 'status': 'DELIVERED'})

    body = resp.get_json()
    assert resp.status_code == 200
    assert body['updated'] == 1
    assert 'no longer exist' in body['message']


def test_bulk_status_rejects_an_invalid_status(admin_session, db, coach_order):
    resp = admin_session.post('/admin-panel/store/orders/bulk-status',
                              json={'order_ids': [coach_order.id], 'status': 'SHIPPED'})
    assert resp.status_code == 400


def test_bulk_status_rejects_an_empty_selection(admin_session, db, pub_league_season):
    resp = admin_session.post('/admin-panel/store/orders/bulk-status',
                              json={'order_ids': [], 'status': 'ORDERED'})
    assert resp.status_code == 400


def test_bulk_delete_removes_every_selected_order(admin_session, db, coach_order, optioned_order):
    ids = [coach_order.id, optioned_order.id]

    resp = admin_session.post('/admin-panel/store/orders/bulk-delete',
                              json={'order_ids': ids})

    assert resp.status_code == 200, resp.data[:400]
    assert resp.get_json()['deleted'] == 2
    db.session.expire_all()
    assert all(db.session.get(StoreOrder, i) is None for i in ids)


def test_bulk_routes_survive_a_bodyless_post(admin_session, db, pub_league_season):
    for path in ('/admin-panel/store/orders/bulk-status',
                 '/admin-panel/store/orders/bulk-delete'):
        resp = admin_session.post(path)
        assert resp.status_code == 400, path
        assert resp.get_json()['success'] is False
