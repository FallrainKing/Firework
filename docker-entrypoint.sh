#!/bin/sh
# Container-side self-heal for the /app/data volume ownership.
#
# When `docker compose up` first creates ./data on the host, the docker
# daemon does so as root — silently locking the host user out of their own
# data directory (e.g. the smoke test's import temp dir, or any manual
# file management). The app container runs as root, so at startup we chown
# the mount point to the configured host uid (HOST_UID, default 1000).
#
# Deliberately non-recursive: container-owned entries (app.db, papers/,
# hf/, qdrant/ — the latter owned by the qdrant service) keep their owners.
# The app itself runs as root and can write anywhere regardless; the host
# user only needs to create/read entries in the top-level directory.
set -e

host_uid="${HOST_UID:-1000}"
host_gid="${HOST_GID:-$host_uid}"
current_uid="$(stat -c %u /app/data)"
if [ "$current_uid" != "$host_uid" ]; then
    echo "entrypoint: chown /app/data $current_uid -> $host_uid:$host_gid (docker creates it root-owned)"
    chown "$host_uid:$host_gid" /app/data
fi

exec "$@"
