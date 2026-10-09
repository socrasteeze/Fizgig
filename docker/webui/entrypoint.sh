#!/bin/sh
set -eu

STATE_DIR=${TS_STATE_DIR:-/var/lib/tailscale}
mkdir -p "$STATE_DIR"

if [ -z "${TS_AUTHKEY:-}" ] && [ ! -s "$STATE_DIR/tailscaled.state" ]; then
  echo "TS_AUTHKEY is required when there is no saved Tailscale state." >&2
  exit 1
fi

tailscaled --tun=userspace-networking --statedir="$STATE_DIR" &
TS_PID=$!

cleanup() {
  if [ -n "${TS_PID:-}" ] && kill -0 "$TS_PID" 2>/dev/null; then
    kill "$TS_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

i=0
while [ "$i" -lt 50 ]; do
  if tailscale status >/dev/null 2>&1; then
    i=0
    break
  fi
  i=$((i + 1))
  sleep 0.1
done
if [ "$i" -ne 0 ]; then
  echo "tailscale status did not succeed" >&2
  exit 1
fi

if [ -n "${TS_AUTHKEY:-}" ]; then
  tailscale up --auth-key="$TS_AUTHKEY"
else
  tailscale up
fi

tailscale serve --bg 8081

echo "web server is listening on 127.0.0.1:8081"
if [ -d /opt/fizgig ]; then
  cd /opt/fizgig
fi
set +e
python3 -m fizgig.web
status=$?
set -e
exit "$status"
