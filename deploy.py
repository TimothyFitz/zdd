#!/usr/bin/env python
import sys
import subprocess
import signal
import os
import time
from ConfigParser import SafeConfigParser

SERVICE_PREFIX = "service:"
NGINX_TEMPLATE_SUFFIX = ".template"

def check_pid(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        print pid, "not running"
        return False
    else:
        return True

def read_int_file(filename):
    try:
        with file(filename, 'r') as pidfile:
            return int(pidfile.read())
    except (IOError, OSError, ValueError):
        print "Unable to read", filename
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
        else:
            print "polling", fun
        time.sleep(0.1)

def run_cmd(command, *args):
    print "Running",command.split(' ') + list(args)
    return subprocess.Popen(command.split(' ') + list(args))

class Service(object):
    def __init__(self, config, section):
        assert section.startswith(SERVICE_PREFIX)
        self.name = section[len(SERVICE_PREFIX):]
        self.options = dict([(option, config.get(section, option)) for option in config.options(section)])
        print self.name, self.options

    @property
    def pid_file(self):
        return self.options['pid_file']

    def start(self):
        run_cmd(self.options['start_script'])

    def stop(self, pid):
        run_cmd(self.options['stop_script'], str(pid))

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
        self.template = config.get("nginx", "template")
        self.pid_file = config.get("nginx", "pid_file")
        self.log_file = config.get("nginx", "log_file")

        assert self.template.endswith(NGINX_TEMPLATE_SUFFIX), "nginx template name must end with " + NGINX_TEMPLATE_SUFFIX

    def read_pid(self):
        return read_pid(self.pid_file)

class Tail(object):
    def __init__(self, filename):
        self.fp = file(filename, 'r')
        self.fp.seek(0, os.SEEK_END)
        self.tail = self.fp.tell()

    def read_tail(self):
        self.fp.seek(self.tail, os.SEEK_SET)
        return self.fp.read()

def template_replace(template, replacements):
    # Feel free to swap in your own real templating engine
    # str.replace used only to remove a dependency
    for key, value in sorted(replacements.items()):
        template = template.replace("{%s}" % key, value)
    return template

def deploy(config_file):
    config = SafeConfigParser()
    config.read(config_file)

    services = [Service(config, section) for section in config.sections() if section.startswith(SERVICE_PREFIX)]

    old_pids = []

    # Save old pid files and then delete them
    for service in services:
        pid = service.read_pid()
        if not pid:
            continue

        old_pids.append((service, pid))
        with file(service.name + ".previous.pid", 'w') as prev_pid_file: 
            prev_pid_file.write(str(pid))

        try:
            os.unlink(service.pid_file)
        except OSError:
            pass

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
        run_cmd("nginx", "-c", conf_path)


    # wait for nginx to reconfig
    # We could tail the error log set to info, but even then we'd need to know the # of worker processes
    # both before and after the sighup (could change if the conf.template changes)
    # The best option would be to either patch nginx, or write a plugin to get an authoritive answer.
    time.sleep(1)

    # stop old processes
    for service, old_pid in old_pids:
        print "Stopping previous instance of %s, process %s." % (service.name, old_pid)
        service.stop(old_pid)


def main():
    if len(sys.argv) != 2:
        print >> sys.stderr, "Usage: deploy.py [config file]"
        sys.exit(1)

    deploy(sys.argv[1])

if __name__ == "__main__":
    main()