#!/bin/sh

set -e

docker build -t mopsalarm/pr0gramm-updates .
docker push mopsalarm/pr0gramm-updates
