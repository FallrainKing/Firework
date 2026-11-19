#!/bin/sh
# Explicit restore entrypoint for the local backup bundle.
#
# Usage:
#   docker compose stop app backup
#   sh ops/restore.sh ./backups 20261119 --confirm
#
# Safety rules:
#   * --confirm is mandatory; this script never auto-runs from backup.
#   * It stages and validates every archive before touching DATA_DIR.
#   * Dynamic skill storage keys and archive hashes are checked against the
#     SQLite registry, so a partial bundle fails before restore.
#   * Existing database and folders are moved to a rollback directory first.
#   * Qdrant snapshots are uploaded after local state is restored.
set -eu
umask 077

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    sed -n '2,15p' "$0"
    exit 0
fi
if [ "$#" -lt 2 ] || [ "$3" != "--confirm" ]; then
    echo "usage: $0 BACKUP_DIR YYYYMMDD --confirm" >&2
    exit 2
fi

BACKUP_DIR=$1
DATE=$2
DATA_DIR="${DATA_DIR:-./data}"
QDRANT_URL="${QDRANT_URL:-http://qdrant:6333}"
DB_BACKUP="${BACKUP_DIR}/app-${DATE}.db"
SKILLS_BACKUP="${BACKUP_DIR}/skills-${DATE}.tar.gz"
AVATARS_BACKUP="${BACKUP_DIR}/avatars-${DATE}.tar.gz"
ROLLBACK="${DATA_DIR}/restore-rollback-$(date +%Y%m%d%H%M%S)"
STAGE=$(mktemp -d)
RESTORE_STARTED=0

cleanup() {
    rm -rf -- "$STAGE"
}
trap cleanup EXIT HUP INT TERM

require_file() {
    if [ ! -f "$1" ]; then
        echo "restore.sh: required backup file missing: $1" >&2
        exit 1
    fi
}

echo "restore.sh: staging and validating backup ${DATE}"
require_file "$DB_BACKUP"
require_file "$SKILLS_BACKUP"

tar -xzf "$DB_BACKUP" -C "$STAGE" --strip-components 0 2>/dev/null || true
# The database archive is the SQLite file itself, not a tarball.
if [ ! -f "$STAGE/app-${DATE}.db" ]; then
    cp "$DB_BACKUP" "$STAGE/app-${DATE}.db"
fi
DB="$STAGE/app-${DATE}.db"

integrity=$(sqlite3 "$DB" 'PRAGMA integrity_check;' 2>/dev/null || true)
if [ "$integrity" != "ok" ]; then
    echo "restore.sh: SQLite integrity check failed" >&2
    exit 1
fi

mkdir -p "$STAGE/skills"
tar -xzf "$SKILLS_BACKUP" -C "$STAGE/skills" --strip-components 1
if [ -f "$AVATARS_BACKUP" ]; then
    mkdir -p "$STAGE/avatars"
    tar -xzf "$AVATARS_BACKUP" -C "$STAGE/avatars" --strip-components 1
fi

# Every expanded package referenced by skill_versions must exist.
for storage_key in $(sqlite3 "$DB" "SELECT storage_key FROM skill_versions WHERE storage_key<>''"); do
    if [ ! -d "$STAGE/skills/$storage_key" ]; then
        echo "restore.sh: missing expanded skill package: $storage_key" >&2
        exit 1
    fi
done

# Every immutable archive referenced by skill_imports must exist.
for archive_hash in $(sqlite3 "$DB" "SELECT archive_hash FROM skill_imports WHERE archive_hash<>''"); do
    if [ ! -f "$STAGE/skills/archives/$archive_hash.zip" ]; then
        echo "restore.sh: missing skill archive: $archive_hash.zip" >&2
        exit 1
    fi
done

# A referenced avatar must exist in the paired avatar archive.
for avatar in $(sqlite3 "$DB" "SELECT avatar_storage_key FROM user_profile WHERE avatar_storage_key<>''"); do
    if [ ! -f "$STAGE/avatars/$avatar" ]; then
        echo "restore.sh: missing avatar: $avatar" >&2
        exit 1
    fi
done

# Optional reader and native-session folders are restored when present.
for folder in papers imports attachments; do
    archive="${BACKUP_DIR}/${folder}-${DATE}.tar.gz"
    if [ -f "$archive" ]; then
        mkdir -p "$STAGE/$folder"
        tar -xzf "$archive" -C "$STAGE/$folder" --strip-components 1
    fi
done
if [ -f "${BACKUP_DIR}/agent-sessions-${DATE}.tar.gz" ]; then
    mkdir -p "$STAGE/agent"
    tar -xzf "${BACKUP_DIR}/agent-sessions-${DATE}.tar.gz" -C "$STAGE/agent" --strip-components 2
fi

mkdir -p "$DATA_DIR" "$ROLLBACK"
RESTORE_STARTED=1
for item in app.db app.db-wal app.db-shm skills avatars papers imports attachments agent; do
    if [ -e "$DATA_DIR/$item" ]; then
        mv -- "$DATA_DIR/$item" "$ROLLBACK/$item"
    fi
done
cp -- "$DB" "$DATA_DIR/app.db"
for folder in skills avatars papers imports attachments agent; do
    if [ -d "$STAGE/$folder" ]; then
        cp -a -- "$STAGE/$folder" "$DATA_DIR/$folder"
    fi
done

post_check=$(sqlite3 "$DATA_DIR/app.db" 'PRAGMA integrity_check;' 2>/dev/null || true)
if [ "$post_check" != "ok" ]; then
    echo "restore.sh: post-restore database check failed; rollback is at $ROLLBACK" >&2
    exit 1
fi

# Restore Qdrant collections named qdrant-<collection>-<date>.snap.
if [ "${RESTORE_QDRANT:-1}" = "1" ]; then
    for snapshot in "$BACKUP_DIR"/qdrant-*-"$DATE".snap; do
        [ -f "$snapshot" ] || continue
        base=${snapshot##*/}
        collection=${base#qdrant-}
        collection=${collection%-"$DATE".snap}
        echo "restore.sh: uploading Qdrant snapshot for $collection"
        curl -fsS -X PUT \
            "$QDRANT_URL/collections/$collection/snapshots/upload?priority=snapshot" \
            -F "snapshot=@$snapshot" >/dev/null
    done
fi

echo "restore.sh: restore complete. Restart app and backup services."
echo "restore.sh: previous state retained at $ROLLBACK"
echo "restore.sh: verify skills, sessions, and runs before deleting the rollback."
