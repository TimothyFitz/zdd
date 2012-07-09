import atexit
import os
import signal
import logging

from twisted.application import internet, service
from twisted.web import server, resource

class HelloWorldResource(resource.Resource):
    isLeaf = True

    def render_GET(self, request):
        return "<html>Hello, world!</html>"

class GracefulTCPServer(internet.TCPServer):
    def __init__(self, *args):
        internet.TCPServer.__init__(self, 0, *args)

    def startService(self):
        internet.TCPServer.startService(self)
        self.save_portfile()
        signal.signal(signal.SIGUSR1, lambda signum, frame: reactor.callFromThread(self.on_SIGUSR1))

    def on_SIGUSR1(self):
        log.msg("SIGUSR1 received, gracefully stopping.", logLevel=logging.CRITICAL)
        d = self.stopService()
        d.addCallback(self.on_stopped_listening)

    def on_stopped_listening(self):
        # TODO: Implement graceful stopping
        reactor.stop()

    def save_portfile(self):
        port_filename = "./%s.port" % os.getpid()
        port = self._port.getHost().port
        with file(port_filename, 'w') as portfile:
            portfile.write(str(port))

        @atexit.register
        def remove_portfile():
            os.unlink(port_filename)

def HelloWorldApp():
    application = service.Application("HelloWorld")

    site = server.Site(HelloWorldResource())

    web_server = GracefulTCPServer(site)
    web_server.setServiceParent(application)

    return application