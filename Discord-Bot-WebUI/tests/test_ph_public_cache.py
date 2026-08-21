"""Pins the public-site render-cache INVALIDATION MECHANISM (Phase 4,
criterion 4 — "editing and publishing a page changes what the public site
serves within seconds, because the render cache invalidates after commit").

WHAT THIS FILE PROVES
---------------------
1. The bump is queued during the request but fires only AFTER the writing
   transaction commits, so a concurrent reader can never refill the cache with
   pre-commit rows under the post-write version key.
2. Because the design is versioned-key (nothing is ever deleted), "invalidated"
   means "the cache key changed". Both bump scopes are checked: a page bump
   moves only that page's key, a global bump moves every page's key.
3. A real publish through a real route moves the key, and a publish the server
   REFUSES moves nothing. Without that second half, the first would pass just
   as well if every request bumped unconditionally.

WHAT THIS FILE DOES *NOT* PROVE — read this before trusting criterion 4
----------------------------------------------------------------------
It does NOT prove that `/preview` uses this mechanism, because `/preview` does
not use it. The cache read/write path in `app/public_site.py` (lines 313-354
and 369-418) is hard-gated on the `PUBLIC_ONLY` environment variable, which
`docker-compose.yml` sets ONLY on the `publicweb` service. `/preview` is served
by `webui`, which never sets it — so `/preview` renders live from the database
on every request and never touches Redis. An edit is visible on the very next
request because there is no cache in the loop, NOT because a cache invalidated.

`TestPreviewIsUncachedToday` pins exactly that, so the difference is a checked
fact rather than an inherited assumption. See
`.planning/phases/04-live-on-the-portal/04-DEPLOY-VERIFICATION.md` Section 4.

WHY THERE IS A HAND-WRITTEN FAKE REDIS HERE
-------------------------------------------
`tests/conftest.py:37-57` installs a `MagicMock` as the process-wide Redis
client. Its `incr` ALWAYS returns 1 and its `get` ALWAYS returns `None`,
whatever was written. A test that asserted against that mock's return values
would pass with the entire invalidation mechanism deleted. So every test below
runs against a real in-memory dict installed over the cache module's OWN
`_redis()` accessor, and asserts on the observed contents of that dict.
`TestTheFakeItselfRecordsWrites` is the instrument check: it proves the fake
records a store, so "no key was written" in
`TestPreviewIsUncachedToday` means something.
"""
import pytest

from app.models import SitePage
from app.services import public_cache as pc


# --------------------------------------------------------------------------- #
# A real in-memory Redis stand-in - NOT a mock.
#
# It must implement every method the cache module actually calls (get, incr,
# setex, set, delete). If it did not, `store_html`'s own `except Exception`
# would swallow the AttributeError and the "nothing was cached" assertion in
# TestPreviewIsUncachedToday would pass for the wrong reason.
# --------------------------------------------------------------------------- #
class _FakeRedis:
    def __init__(self, store):
        self.store = store

    def get(self, key):
        return self.store.get(key)

    def incr(self, key, amount=1):
        new = int(self.store.get(key) or 0) + amount
        self.store[key] = str(new)
        return new

    def setex(self, key, ttl, value):
        self.store[key] = value
        return True

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def delete(self, key):
        return 1 if self.store.pop(key, None) is not None else 0


@pytest.fixture
def cache_store(app, monkeypatch):
    """Yields the backing dict of an in-memory Redis installed over
    `public_cache._redis`, so bump / key-build / store all see one real store.

    Also scrubs the two `g` keys the after-commit queue uses. The test suite
    pushes ONE session-scoped app context (conftest.py:100-105) and Flask does
    not push a second one for a test request, so `g` — and therefore
    `_public_cache_bumps` / `_public_cache_listener` — is shared by every test
    in the run. Without this scrub a bump queued by an earlier test could drain
    into this test's store.
    """
    from flask import g, has_app_context

    def _scrub():
        if has_app_context():
            stale = g.__dict__.pop('_public_cache_bumps', None)
            if stale is not None:
                # Clear the object itself: an already-registered after_commit
                # listener still holds a reference to this exact set.
                stale.clear()
            g.__dict__.pop('_public_cache_listener', None)

    _scrub()
    store = {}
    monkeypatch.setattr(pc, '_redis', lambda: _FakeRedis(store))
    yield store
    _scrub()


# Key formats are imported from the module, never retyped as literals, so a
# key-format change fails these tests loudly instead of silently asserting
# nothing.
def _page_ver_key(slug):
    return pc._P_KEY.format(scope='page', slug=slug)


_HOST = 'ecspubleague.test'


def _html_prefix():
    """Derive the HTML cache key prefix from cache_key() itself rather than
    hard-coding 'public:html:' — if the key format changes, this moves with
    it instead of quietly matching nothing."""
    built = pc.cache_key(_HOST, '/probe', 'page', 'probe-slug')
    assert built, 'cache_key returned falsy — the fake Redis is not installed'
    return built.split(_HOST)[0]


_DOC = {'v': 1, 'sections': [
    {'id': 's1', 'type': 'content', 'theme': 'inherit', 'settings': {},
     'blocks': [{'id': 'b1', 'type': 'heading', 'level': 2, 'html': 'Cache proof'}]}]}


def _make_page(db, slug, **kwargs):
    defaults = dict(title='Cache Test Page', status='draft', sections_draft=_DOC)
    defaults.update(kwargs)
    p = SitePage(slug=slug, **defaults)
    db.session.add(p)
    db.session.commit()
    return p


@pytest.fixture
def gadmin_client(client, db):
    """Global Admin session on the shared test client (shape copied from
    tests/test_ph_pages_list.py:33-52)."""
    from app.models import User, Role
    role = db.session.query(Role).filter_by(name='Global Admin').first()
    if not role:
        role = Role(name='Global Admin', description='Global Admin')
        db.session.add(role)
        db.session.flush()
    u = db.session.query(User).filter_by(username='cache-gadmin').first()
    if not u:
        u = User(username='cache-gadmin', email='cache-gadmin@example.com',
                 is_approved=True, approval_status='approved')
        u.set_password('x')
        u.roles.append(role)
        db.session.add(u)
        db.session.flush()
    db.session.commit()
    with client.session_transaction() as sess:
        sess['_user_id'] = u.id
        sess['_fresh'] = True
    return client


# --------------------------------------------------------------------------- #
# Test 1 - the ordering guarantee. This is the whole point of the mechanism.
# --------------------------------------------------------------------------- #

class TestAfterCommitOrdering:
    def test_bump_is_queued_before_commit_and_fires_only_after(self, app, db, cache_store):
        """Both halves are load-bearing:

        * Delete the after-commit deferral (bump immediately, as
          `bump_public_cache` does) and the FIRST assertion fails — the key
          would already exist before the transaction committed.
        * Delete the bump entirely and the SECOND assertion fails — the key
          would never appear at all.

        A test that only checked the post-commit value would still pass with
        the deferral removed, which is exactly the race the module's own
        docstring warns about (a reader refilling the cache with pre-commit
        rows under the new version).
        """
        from flask import g
        slug = 'after-commit-ordering'
        key = _page_ver_key(slug)

        with app.test_request_context('/admin-panel/public-site/pages'):
            # A real request has g.db_session assigned by the before_request
            # handler (app/init/request_handlers.py:198). Mirror that.
            g.db_session = db.session

            # A real write inside the request, so this is a genuine transaction
            # and not an empty commit.
            page = SitePage(slug=slug, title='Ordering Proof', status='draft',
                            sections_draft=_DOC)
            db.session.add(page)

            pc.bump_public_cache_after_commit('page', slug)

            # BEFORE the commit: nothing may have reached Redis yet. Not just
            # "the key is absent" — the whole store must still be untouched.
            assert key not in cache_store, (
                'version key was bumped BEFORE commit — the after_commit '
                f'deferral is not in play (store={cache_store!r})')
            assert cache_store == {}, (
                f'something reached Redis before commit: {cache_store!r}')

            db.session.commit()

            # AFTER the commit: the drain has run.
            assert cache_store.get(key) == '1', (
                'version key was not bumped after commit — the after_commit '
                f'listener never drained (store={cache_store!r})')

    def test_repeated_queued_bumps_for_one_page_drain_once(self, app, db, cache_store):
        """The module promises bumps are de-duped per request ("Safe to call
        many times per request"). Three queued bumps for the same page must
        produce ONE increment, not three — otherwise every multi-write handler
        would inflate the version counter without bound."""
        from flask import g
        slug = 'dedupe-proof'
        key = _page_ver_key(slug)

        with app.test_request_context('/admin-panel/public-site/pages'):
            g.db_session = db.session
            db.session.add(SitePage(slug=slug, title='Dedupe Proof',
                                    status='draft', sections_draft=_DOC))
            pc.bump_public_cache_after_commit('page', slug)
            pc.bump_public_cache_after_commit('page', slug)
            pc.bump_public_cache_after_commit('page', slug)
            db.session.commit()

        assert cache_store.get(key) == '1', (
            f'expected a single de-duped increment, got {cache_store.get(key)!r}')


# --------------------------------------------------------------------------- #
# Test 2 + 3 - the invalidation is OBSERVABLE, in both scopes.
#
# In a versioned-key cache nothing is deleted. "Invalidated" means the key the
# renderer will look under has changed, so the old entry is unaddressable and
# ages out on TTL. That is what these assert.
# --------------------------------------------------------------------------- #

class TestVersionedKeyInvalidation:
    def test_page_bump_changes_that_pages_cache_key(self, app, cache_store):
        slug = 'key-change-proof'
        before = pc.cache_key(_HOST, '/key-change-proof', 'page', slug)

        pc.bump_public_cache('page', slug)

        after = pc.cache_key(_HOST, '/key-change-proof', 'page', slug)

        assert before != after, (
            'the cache key did not move after a page bump — the render cache '
            f'would keep serving the stale entry (key={before!r})')
        assert before.endswith(':g0:p0'), before
        assert after.endswith(':g0:p1'), after
        assert cache_store.get(_page_ver_key(slug)) == '1'

    def test_page_bump_does_not_move_a_different_pages_key(self, app, cache_store):
        """Scoping control: a targeted bump must not invalidate the whole
        site. Without this, a `bump_public_cache` that always bumped the global
        counter would still pass the test above."""
        mine = pc.cache_key(_HOST, '/mine', 'page', 'scoped-mine')
        theirs_before = pc.cache_key(_HOST, '/theirs', 'page', 'scoped-theirs')

        pc.bump_public_cache('page', 'scoped-mine')

        assert pc.cache_key(_HOST, '/mine', 'page', 'scoped-mine') != mine
        assert pc.cache_key(_HOST, '/theirs', 'page', 'scoped-theirs') == theirs_before
        assert _page_ver_key('scoped-theirs') not in cache_store
        assert pc._G_KEY not in cache_store, (
            'a page-scoped bump touched the GLOBAL version counter')

    def test_global_bump_changes_the_key_of_a_page_it_was_not_named_against(
            self, app, cache_store):
        """Appearance / menu / theme-class writes bump `global`. That must
        invalidate every page, including ones never named in the bump —
        otherwise a logo change would leave stale headers cached site-wide."""
        slug = 'unrelated-page'
        before = pc.cache_key(_HOST, '/unrelated-page', 'page', slug)

        pc.bump_public_cache('global')

        after = pc.cache_key(_HOST, '/unrelated-page', 'page', slug)

        assert before != after, (
            'a global bump left an unrelated page addressable at its old key')
        assert ':g0:' in before and ':g1:' in after
        assert cache_store.get(pc._G_KEY) == '1'
        assert _page_ver_key(slug) not in cache_store, (
            'a global bump created a per-page version key it should not touch')


# --------------------------------------------------------------------------- #
# Test 4 + 5 - criterion 4's sentence, executed through a real route, with its
# own non-vacuity control.
# --------------------------------------------------------------------------- #

class TestPublishThroughARealRoute:
    def test_publishing_a_page_bumps_that_pages_version_key(
            self, app, db, gadmin_client, cache_store):
        """A Global Admin publishing an ordinary page increments that page's
        version key — which is criterion 4 in one sentence. Asserting on the
        store (not on the 302) is the point: a redirect tells you nothing about
        whether the cache moved."""
        slug = 'publish-bumps-cache'
        page = _make_page(db, slug)
        key = _page_ver_key(slug)
        assert key not in cache_store, 'precondition: no version key yet'

        r = gadmin_client.post(
            f'/admin-panel/public-site/pages/{page.id}/publish')
        assert r.status_code in (200, 302), r.get_data(as_text=True)

        db.session.expire_all()
        assert db.session.query(SitePage).get(page.id).status == 'published', \
            'the publish itself did not happen, so the cache assertion below ' \
            'would be meaningless'

        assert cache_store.get(key) == '1', (
            'publishing a page did not bump its render-cache version key — '
            f'store={cache_store!r}')
        # The route also takes a global bump (_bump_public), because published
        # pages feed shared chrome (nav/menus). Both are expected.
        assert cache_store.get(pc._G_KEY) == '1'

    def test_a_refused_publish_bumps_nothing(
            self, app, db, gadmin_client, cache_store):
        """THE NON-VACUITY CONTROL for the test above.

        A page with no sections at all is refused by the server's own
        `empty_page` guard (`apply_page_settings`,
        app/admin_panel/routes/public_site.py:1099-1100), which returns BEFORE
        the bump on line 1111. Nothing may reach Redis.

        Without this test, the test above would pass just as well against an
        implementation that bumped on every request regardless of outcome.
        """
        slug = 'refused-publish-no-bump'
        page = _make_page(db, slug, sections_draft={'v': 1, 'sections': []})
        key = _page_ver_key(slug)

        r = gadmin_client.post(
            f'/admin-panel/public-site/pages/{page.id}/publish')
        assert r.status_code in (200, 302), r.get_data(as_text=True)

        db.session.expire_all()
        assert db.session.query(SitePage).get(page.id).status == 'draft', \
            'the server did not refuse the empty publish — this control is ' \
            'not testing what it claims to test'

        assert key not in cache_store, (
            f'a REFUSED publish bumped the page version key: {cache_store!r}')
        assert cache_store == {}, (
            f'a REFUSED publish wrote to Redis at all: {cache_store!r}')


# --------------------------------------------------------------------------- #
# Test 6 - the Phase 5 risk, made executable.
# --------------------------------------------------------------------------- #

class TestPreviewIsUncachedToday:
    def test_preview_home_writes_no_cached_html_entry(
            self, app, db, client, cache_store, monkeypatch):
        """`/preview` renders live from the database and stores NOTHING.

        The cache read/write path in `app/public_site.py` (`_render_page_sections`
        line 327, `_dynamic_page_cache` line 392) is gated on the `PUBLIC_ONLY`
        environment variable, which `docker-compose.yml` sets only on the
        `publicweb` service (:782). `webui` — which serves `/preview` — does not
        set it. So criterion 4 ("an edit shows up on /preview within seconds")
        is true today because there is no cache in the loop, not because a cache
        invalidates correctly.

        The delenv below makes that configuration explicit rather than assumed.

        *** THIS TEST IS EXPECTED TO START FAILING AT PHASE 5 CUTOVER. ***
        The moment `publicweb` serves real traffic with `PUBLIC_ONLY=true`, this
        code path becomes load-bearing for the first time and HTML entries will
        legitimately appear. When that happens, UPDATE this test to assert the
        cached entry lands under the correct versioned key — do not delete it.
        Deleting it would discard the only executable record that `/preview`'s
        freshness never depended on the invalidation mechanism above.
        """
        monkeypatch.delenv('PUBLIC_ONLY', raising=False)
        prefix = _html_prefix()

        r = client.get('/preview/')
        assert r.status_code == 200, r.get_data(as_text=True)[:500]

        html_keys = [k for k in cache_store if k.startswith(prefix)]
        assert html_keys == [], (
            'an anonymous GET of /preview/ wrote a cached HTML entry — the '
            f'PUBLIC_ONLY gate is no longer holding: {html_keys!r}')


class TestTheFakeItselfRecordsWrites:
    """Instrument check. The suite's shared Redis is a MagicMock whose writes
    go nowhere, and `store_html` swallows every exception — so "no HTML key was
    written" is only meaningful if this fake would have recorded one. Prove it
    would."""

    def test_store_html_lands_in_the_fake_store(self, app, cache_store):
        prefix = _html_prefix()
        key = pc.cache_key(_HOST, '/instrument-check', 'page', 'instrument')
        assert key.startswith(prefix)

        pc.store_html(key, '<html>instrument</html>')

        assert cache_store.get(key) == '<html>instrument</html>', (
            'the fake Redis did not record a store — every "nothing was '
            'cached" assertion in this file would be vacuous')
        assert pc.get_cached_html(key) == '<html>instrument</html>'
        assert [k for k in cache_store if k.startswith(prefix)], \
            'prefix derivation is wrong; the /preview assertion would match nothing'
