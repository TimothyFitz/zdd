#!/usr/bin/env bash
gunicorn -D -c settings_gunicorn.py app:app