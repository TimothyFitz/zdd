#!/usr/bin/env python
import sys
import subprocess
import signal
import os
import time
from ConfigParser import SafeConfigParser, Error as ConfigParserError

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

    def read_pid(self):
        return read_pid(self.pid_file)

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
        return os.path.join(self.config_dir, relpath)

def move_old_pidfiles(services):
    """Save old pid files and then delete them"""
    for service in services:
        pid = service.read_pid()
        if not pid:
            continue

        service.previous_pid = pid

        with file(service.name + ".previous.pid", 'w') as prev_pid_file: 
            prev_pid_file.write(str(pid))

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

    # Deal with templating
    nginx = Nginx(config)

    with file(nginx.template, 'r') as template_file:
        template_content = template_file.read()

    # Wait for new services to spin up, and save their pids
    replacements = {}
    for service in services:
        rs = wait_for(service.read_port)
        if not rs:
            print >>sys.stderr, "Unable to start %s, timeout while waiting for port file." % service.name
            sys.exit(1)

        print "%s succesfully started, process %s listening on port %s." % (service.name, rs.pid, rs.port)

        replacements[service.name] = str(rs.port)

        with file(service.name + ".current.pid", 'w') as current_pid_file:
            current_pid_file.write(str(rs.pid))

    # Write out nginx template

    conf_dir = os.path.abspath(os.path.dirname(nginx.template))
    conf_filename = os.path.basename(nginx.template)[:-len(NGINX_TEMPLATE_SUFFIX)]
    conf_path = os.path.abspath(os.path.join(conf_dir, conf_filename))

    replacements['conf_dir'] = conf_dir

    nginx_conf_content = template_replace(template_content, replacements)

    with file(conf_path, 'w') as nginx_conf:
        nginx_conf.write(nginx_conf_content)

    # SIGHUP or spawn nginx
    nginx_pid = nginx.read_pid()
    if nginx_pid:
        print "Sending SIGHUP to existing nginx process %s." % nginx_pid
        os.kill(nginx_pid, signal.SIGHUP)
    else:
        print "Spawning new nginx."
        subprocess.Popen(["nginx", "-c", conf_path])


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
    def usage():
        print >> sys.stderr, "Usage: deploy.py [config file]"
        sys.exit(1)

    if len(argv) == 1:
        conf_file = settings.DEFAULT_CONF_FILE
    elif len(argv) == 2:
        conf_file = argv[1]
    else:
        usage()

    if not os.path.exists(conf_file):
        print >> sys.stderr, "%s not found." % conf_file
        usage()

    deploy(conf_file)