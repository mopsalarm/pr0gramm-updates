#!/bin/sh

exec python3 -u -m bottle -s waitress --debug main

