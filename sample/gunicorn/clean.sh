#!/usr/bin/env bash
pkill -f gunicorn
pkill -f nginx
rm *.pid

