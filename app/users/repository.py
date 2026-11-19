"""SQLite access for the local user profile."""
from __future__ import annotations


def profile(db):
    return db.execute('SELECT * FROM user_profile WHERE singleton_id=1').fetchone()


def update_profile(db, *, display_name=None, avatar_storage_key=None):
    fields = []
    args = []
    if display_name is not None:
        fields.append('display_name=?')
        args.append(display_name)
    if avatar_storage_key is not None:
        fields.append('avatar_storage_key=?')
        args.append(avatar_storage_key)
    if not fields:
        return
    fields.append('revision=revision+1')
    fields.append('updated_at=CURRENT_TIMESTAMP')
    db.execute(f"UPDATE user_profile SET {','.join(fields)} WHERE singleton_id=1", args)


def preference(db):
    return db.execute("SELECT * FROM user_preferences WHERE key='preferences'").fetchone()


def upsert_preference(db, value_json: str, expected_revision: int | None):
    row = preference(db)
    if row is None:
        db.execute("INSERT INTO user_preferences(key,value_json) VALUES ('preferences',?)", (value_json,))
        return
    if expected_revision is not None and row['revision'] != expected_revision:
        raise ValueError('revision')
    db.execute(
        "UPDATE user_preferences SET value_json=?,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE key='preferences'",
        (value_json,),
    )
