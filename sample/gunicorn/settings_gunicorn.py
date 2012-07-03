import atexit
import os

bind = "127.0.0.1:0"
pidfile = "gunicorn.pid"

def get_port_filename():
    pid = os.getpid()
    return os.path.join(os.path.dirname(pidfile), "%s.port" % pid)

def when_ready(server):
    host, port = server.LISTENER.sock.getsockname()
    port_filename = get_port_filename()
    with file(port_filename, 'w') as portfile:
        print >>portfile, port

    def remove_portfile():
        os.unlink(port_filename)

    atexit.register(remove_portfile)


