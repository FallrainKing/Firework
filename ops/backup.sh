#!/bin/sh
# Daily backup job (run by the backup container's cron at 02:00):
#   1. SQLite online backup (sqlite3 .backup) -> /backups/app-YYYYMMDD.db
#   2. Qdrant per-collection snapshot, downloaded -> /backups/qdrant-<coll>-YYYYMMDD.snap
#   3. Retention, local: keep the newest $KEEP backup files of each kind
#   4. Retention, qdrant server: keep the newest $KEEP snapshots per collection
#      (otherwise daily POSTs accumulate unboundedly inside ./data/qdrant)
# NOTE: busybox crond starts jobs with a minimal environment, so the defaults
# below are baked in; override via env when invoking manually (docker exec).
set -eu

DATA_DIR="${DATA_DIR:-/data}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
QDRANT_URL="${QDRANT_URL:-http://qdrant:6333}"
KEEP="${KEEP:-14}"

DB="${DATA_DIR}/app.db"
DATE="$(date +%Y%m%d)"

mkdir -p "$BACKUP_DIR"

# --- 1) SQLite online backup (safe while the app is writing) ---
if [ -f "$DB" ]; then
    sqlite3 "$DB" ".backup '${BACKUP_DIR}/app-${DATE}.db'"
    echo "backup.sh: sqlite -> ${BACKUP_DIR}/app-${DATE}.db"
else
    echo "backup.sh: no database at $DB, skipping sqlite backup" >&2
fi

# --- 2) Qdrant snapshots ---
if curl -fsS "$QDRANT_URL/readyz" >/dev/null 2>&1; then
    for coll in $(curl -fsS "$QDRANT_URL/collections" | jq -r '.result.collections[].name'); do
        # create today's snapshot, then list (oldest -> newest)
        curl -fsS -X POST "$QDRANT_URL/collections/$coll/snapshots" >/dev/null
        snap_list="$(curl -fsS "$QDRANT_URL/collections/$coll/snapshots")"

        # download the newest snapshot for local archival
        snap="$(printf '%s' "$snap_list" \
                 | jq -r '.result | max_by(.creation_time_sec) | .name')"
        if [ -n "$snap" ] && [ "$snap" != "null" ]; then
            curl -fsS -o "${BACKUP_DIR}/qdrant-${coll}-${DATE}.snap" \
                "$QDRANT_URL/collections/$coll/snapshots/${snap}"
            echo "backup.sh: qdrant/$coll -> qdrant-${coll}-${DATE}.snap"
        fi

        # prune server-side: keep only the newest $KEEP snapshots
        # (names arrive via jq stdout, one per line -> no glob involved)
        printf '%s' "$snap_list" \
            | jq -r --argjson keep "$KEEP" \
                '.result | sort_by(.creation_time_sec) | .[: -$keep] | .[].name' \
            | while IFS= read -r old_snap; do
                [ -n "$old_snap" ] || continue
                curl -fsS -X DELETE \
                    "$QDRANT_URL/collections/$coll/snapshots/$old_snap" >/dev/null
                echo "backup.sh: pruned qdrant server snapshot $coll/$old_snap"
            done
    done
else
    echo "backup.sh: qdrant not ready at $QDRANT_URL, skipping snapshot backup" >&2
fi

# --- 3) Retention (local): keep newest $KEEP of each kind, prune by mtime ---
# NOTE: the glob must stay OUTSIDE the quotes: `"$BACKUP_DIR"/$1` lets the
# shell expand the pattern; quoting it makes ls see a literal name, list 0
# files, and prune nothing (verified empirically).
prune() {
    ls -1t "$BACKUP_DIR"/$1 2>/dev/null | tail -n "+$((KEEP + 1))" | while IFS= read -r f; do
        rm -f -- "$f"
        echo "backup.sh: pruned $f"
    done
}
prune 'app-*.db'
prune 'qdrant-*.snap'

echo "backup.sh: done at $(date '+%Y-%m-%d %H:%M:%S %Z')"
