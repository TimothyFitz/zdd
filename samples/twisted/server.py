import atexit
import os
import signal
import logging

from twisted.application import internet, service
from twisted.internet import defer, reactor
from twisted.python import log
from twisted.web import server, resource, http

from deferred_pool import DeferredPool

class HelloWorldResource(resource.Resource):
    isLeaf = True

    def render_GET(self, request):
        return "<html>Hello, world!</html>"

class GracefulHTTPServer(internet.TCPServer):
    def __init__(self, site, *args, **kwargs):
        internet.TCPServer.__init__(self, 0, site, *args, **kwargs)
        self.connections = DeferredPool()
        self.site = site

    def startService(self):
        internet.TCPServer.startService(self)
        self.save_portfile()
        signal.signal(signal.SIGUSR1, lambda signum, frame: reactor.callFromThread(self.on_SIGUSR1))

    def on_SIGUSR1(self):
        log.msg("SIGUSR1 received, gracefully stopping.", logLevel=logging.CRITICAL)
        d = self.stopService()
        d.addCallback(self.on_stopped_listening)

    def on_stopped_listening(self):
        self.site.waitForOutstandingConnections(on_all_connections_finished)

    def on_all_connections_finish(self):
        reactor.stop()

    def save_portfile(self):
        port_filename = "./%s.port" % os.getpid()
        port = self._port.getHost().port
        with file(port_filename, 'w') as portfile:
            portfile.write(str(port))

        @atexit.register
        def remove_portfile():
            os.unlink(port_filename)

class GracefulHTTPChannel(http.HTTPChannel):
    def connectionMade(self):
        http.HTTPChannel.connectionMade(self)
        self.connection_tracker = self.factory.trackConnection()

    def connectionLost(self, reason):
        http.HTTPChannel.connectionLost(self, reason)
        self.connection_tracker.callback(None)

class GracefulSite(server.Site):
    protocol = GracefulHTTPChannel

    def __init__(self, *args, **kwargs):
        server.Site.__init__(self, *args, **kwargs)
        self.connection_pool = DeferredPool()

    def trackConnection(self):
        d = Deferred()
        self.connection_pool.add(d)
        return d

    def waitForOutstandingConnections(self):
        return self.connection_pool.notifyWhenEmpty()


def HelloWorldApp():
    application = service.Application("HelloWorld")

    site = GracefulSite(HelloWorldResource())

    web_server = GracefulHTTPServer(site)
    web_server.setServiceParent(application)

    return application