#!/bin/sh
set -eu
cd "$(dirname "$0")/../.."
if [ -z "${BASE_IMAGE+x}" ]; then
  BASE_IMAGE=fizgig:desktop
  docker build -f docker/Dockerfile -t fizgig:desktop .
fi
docker build -f docker/webui/Dockerfile --build-arg BASE_IMAGE="$BASE_IMAGE" -t fizgig-webui .
