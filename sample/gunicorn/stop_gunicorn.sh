#!/usr/bin/env bash
kill -WINCH `cat ./gunicorn.pid`