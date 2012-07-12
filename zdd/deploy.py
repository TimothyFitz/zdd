from __future__ import with_statement

from ConfigParser import SafeConfigParser, Error as ConfigParserError
from optparse import OptionParser
import os
import signal
import subprocess
import sys
import time

SERVICE_PREFIX = "service:"
NGINX_TEMPLATE_SUFFIX = ".template"

class _Settings(object):
    VERBOSE = False
    DEFAULT_CONF_FILE = "./deploy.conf"

settings = _Settings()

def check_pid(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    else:
        return True

def read_int_file(filename):
    try:
        with file(filename, 'r') as pidfile:
            return int(pidfile.read())
    except (IOError, OSError, ValueError):
        return None

def write_int_file(filename, number):
    with file(filename, 'w') as pidfile:
        pidfile.write(str(number))

def read_pid(filename):
    pid = read_int_file(filename)
    if pid and check_pid(pid):
        return pid

def read_port(directory, pid):
    portfile = os.path.join(directory, "%s.port" % pid)
    return read_int_file(portfile)

def wait_for(fun, timeout=30.0):
    start = time.time()
    while time.time() < start + timeout:
        result = fun()
        if result is not None:
            return result
        time.sleep(0.1)

    raise Exception("Timed out waiting %ss for %r" % (timeout, fun))

class Service(object):
    def __init__(self, config, section):
        assert section.startswith(SERVICE_PREFIX)
        self.name = section[len(SERVICE_PREFIX):]
        self.pid_file = config.get_path(section, "pid_file")
        self.start_cmd = config.get(section, "start")
        self.stop_cmd = config.get(section, "stop")
        try:
            self.cwd = config.get_path(section, "cwd")
        except ConfigParserError:
            self.cwd = config.config_dir

        self.previous_pid = None
        self.current_pid = None

    def run_cmd(self, command, *args, **kwargs):
        kwargs['cwd'] = self.cwd
        if settings.VERBOSE:
            print "Running:", " ".join(command), "in directory", self.cwd
        return subprocess.Popen(command, *args, **kwargs)

    def start(self):
        self.run_cmd(self.start_cmd.split(' '))

    def stop(self, pid):
        self.run_cmd(self.stop_cmd.split(' ') + [str(pid)])

    def read_pid(self):
        return read_pid(self.pid_file)

    def read_port(self):
        pid = self.read_pid()
        if not pid:
            return

        port = read_port(os.path.dirname(self.pid_file), pid)
        if not port:
            return

        return RunningService(self, pid, port)

    def _named_pid_file(self, name):
        """Generates foo.name.pid paths, for example gunicorn.current.pid."""
        dirname, filename = os.path.split(self.pid_file)
        root, ext = os.path.splitext(filename)
        return os.path.join(dirname, root + "." + name + ext)

    @property
    def current_pid_filename(self):
        return self._named_pid_file("current")

    @property
    def previous_pid_filename(self):
        return self._named_pid_file("previous")


class RunningService(object):
    def __init__(self, service, pid, port):
        self.service = service
        self.pid = pid
        self.port = port

class Nginx(object):
    def __init__(self, config):
        self.template = config.get_path("nginx", "template")
        self.pid_file = config.get_path("nginx", "pid_file")

        assert self.template.endswith(NGINX_TEMPLATE_SUFFIX), "nginx template name must end with " + NGINX_TEMPLATE_SUFFIX

    @property
    def rendered_config_filename(self):
        conf_filename = os.path.basename(self.template)[:-len(NGINX_TEMPLATE_SUFFIX)]
        return os.path.abspath(os.path.join(os.path.dirname(self.template), conf_filename))

    def read_pid(self):
        return read_pid(self.pid_file)

    def render_config(self, replacements):
        """Render nginx.conf template into nginx.conf"""

        replacements['nginx_pid_filename'] = self.pid_file

        with file(self.template, 'r') as template_file:
            template_content = template_file.read()

        nginx_conf_content = template_replace(template_content, replacements)

        with file(self.rendered_config_filename, 'w') as nginx_conf:
            nginx_conf.write(nginx_conf_content)

    def reconfig(self):
        """SIGHUP or spawn a new nginx."""
        nginx_pid = self.read_pid()
        if nginx_pid:
            print "Sending SIGHUP to existing nginx process %s." % nginx_pid
            os.kill(nginx_pid, signal.SIGHUP)
        else:
            print "Spawning new nginx."
            subprocess.Popen(["nginx", "-c", self.rendered_config_filename])

def template_replace(template, replacements):
    # Feel free to swap in your own real templating engine
    # str.replace used only to remove a dependency
    for key, value in sorted(replacements.items()):
        template = template.replace("{%s}" % key, value)
    return template

class DeployConfigParser(SafeConfigParser):
    def read(self, filename):
        self.config_dir = os.path.dirname(os.path.abspath(filename))
        return SafeConfigParser.read(self, filename)

    def get_path(self, *args, **kwargs):
        relpath = self.get(*args, **kwargs)
        return os.path.abspath(os.path.join(self.config_dir, relpath))

def move_old_pidfiles(services):
    """Save old pid files and then delete them"""
    for service in services:
        pid = service.read_pid() or read_pid(service.current_pid_filename)
        if not pid:
            continue

        service.previous_pid = pid

        write_int_file(service.previous_pid_filename, pid)

        try:
            os.unlink(service.pid_file)
        except OSError:
            pass

def deploy(config_file):
    config = DeployConfigParser()
    config.read(config_file)

    services = [Service(config, section) for section in config.sections() if section.startswith(SERVICE_PREFIX)]

    move_old_pidfiles(services)

    # Spawn new services
    for service in services:
        print "Starting new", service.name
        service.start()

    # Wait for new services to spin up, and save their pids
    replacements = {}
    for service in services:
        rs = wait_for(service.read_port)
        if not rs:
            print >>sys.stderr, "Unable to start %s, timeout while waiting for port file." % service.name
            sys.exit(1)

        print "%s succesfully started, process %s listening on port %s." % (service.name, rs.pid, rs.port)

        replacements[service.name] = str(rs.port)
        write_int_file(service.current_pid_filename, rs.pid)

    nginx = Nginx(config)
    nginx.render_config(replacements)
    nginx.reconfig()

    # wait for nginx to reconfig
    # We could tail the error log set to info, but even then we'd need to know the # of worker processes
    # both before and after the sighup (could change if the conf.template changes)
    # The best option would be to either patch nginx, or write a plugin to get an authoritive answer.
    time.sleep(1)

    # stop old processes
    for service in services:
        if service.previous_pid is not None:
            print "Stopping previous instance of %s, process %s." % (service.name, service.previous_pid)
            service.stop(service.previous_pid)

def cli_deploy(argv):
    parser = OptionParser()

    parser.add_option(
        "-c",
        "--conf",
        dest="deploy_conf",
        help="FILENAME of zdd configuration. [default %default]",
        default="deploy.conf",
        metavar="FILENAME",
    )

    parser.add_option(
        "-v",
        "--verbose",
        dest="verbose",
        action="store_true",
        default=False,
        help="Enable verbose logging of the actions zdd takes.",
    )

    options, args = parser.parse_args(argv)

    settings.VERBOSE = options.verbose

    if not os.path.exists(options.deploy_conf):
        print "ERROR: Unable to read zdd configuration file: %s" % options.deploy_conf
        print
        parser.print_help()
        parser.exit()

    deploy(options.deploy_conf)
