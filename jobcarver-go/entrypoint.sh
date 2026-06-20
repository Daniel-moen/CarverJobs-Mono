#!/bin/sh
set -e
# Railway mounts the persistent volume at /app/data owned by root. Fix ownership
# (as root) so the unprivileged runtime user can open the SQLite DB, then drop
# privileges and exec the server.
chown -R carver:carver /app/data 2>/dev/null || true
exec su-exec carver:carver /app/server
