#!/usr/bin/env python
import sys
import subprocess
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

def get_pid(filename):
    pid = read_int_file(filename)
    if pid and check_pid(pid):
        return pid

def get_port(directory, pid):
    portfile = os.path.join(directory, "%s.port" % pid)
    return read_int_file(portfile)

def get_port_from_pidfile(filename):
    pid = get_pid(filename)
    if pid:
        return get_port(os.path.dirname(filename), pid)

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

    def start(self):
        run_cmd(self.options['start_script'])

    def stop(self, pid):
        run_cmd(self.options['stop_script'], pid)

    def get_pid(self):
        return get_pid(self.options['pid_file'])

    def read_port(self):
        return get_port_from_pidfile(self.options['pid_file'])

def template_replace(template, replacements):
    for key, value in sorted(replacements.items()):
        template = template.replace(key, value)
    return template

def deploy(config_file):
    config = SafeConfigParser()
    config.read(config_file)

    services = [Service(config, section) for section in config.sections() if section.startswith(SERVICE_PREFIX)]

    old_pids = []

    for service in services:
        pid = service.get_pid()
        old_pids.append((service, pid))

    for service in services:
        print "Starting new", service.name
        service.start()

    nginx_template = config.get('global', 'nginx_template')
    assert nginx_template.endswith(NGINX_TEMPLATE_SUFFIX), "nginx template name must end with " + NGINX_TEMPLATE_SUFFIX

    with file(nginx_template, 'r') as template_file:
        template_content = template_file.read()

    replacements = {}
    for service in services:
        port = wait_for(service.read_port)
        if not port:
            print >>sys.stderr, "Unable to start %s, timeout while waiting for port file." % service.name
            sys.exit(1)
        replacements["{%s}" % service.name] = str(port)

    nginx_conf_content = template_replace(template_content, replacements)

    conf_dir = os.path.dirname(nginx_template)
    conf_filename = os.path.basename(nginx_template)[:-len(NGINX_TEMPLATE_SUFFIX)]
    conf_path = os.path.join(conf_dir, conf_filename)

    with file(conf_path, 'w') as nginx_conf:
        nginx_conf.write(nginx_conf_content)


def main():
    if len(sys.argv) != 2:
        print >> sys.stderr, "Usage: deploy.py [config file]"
        sys.exit(1)

    deploy(sys.argv[1])

if __name__ == "__main__":
    main()