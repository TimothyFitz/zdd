from twisted.internet import defer

# http://blogs.fluidinfo.com/terry/2011/06/10/graceful-shutdown-of-a-twisted-service-with-outstanding-deferreds/
class DeferredPool(object):
    """Maintains a pool of not-yet-fired deferreds and gives a mechanism to
    request a deferred that fires when the pool size goes to zero."""

    def __init__(self):
        self._pool = set()
        self._waiting = []

    def _fired(self, result, d):
        """Callback/errback each pooled deferred runs when it fires. The
        deferred first removes itself from the pool. If the pool is then
        empty, fire all the waiting deferreds (which were returned by
        notifyWhenEmpty)."""
        self._pool.remove(d)
        if not self._pool:
            waiting, self._waiting = self._waiting, []
            for waiter in waiting:
                waiter.callback(None)
        return result

    def add(self, d):
        """Add a deferred to the pool."""
        d.addBoth(self._fired, d)
        self._pool.add(d)

    def notifyWhenEmpty(self, testImmediately=True):
        """Return a deferred that fires (with None) when the pool empties.
        If testImmediately is True and the pool is empty, return an already
        fired deferred (via succeed)."""
        if testImmediately and not self._pool:
            return defer.succeed(None)
        else:
            d = defer.Deferred()
            self._waiting.append(d)
            return d