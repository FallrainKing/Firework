"""Local user profile and preference services."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from ..core.config import Settings
from . import repository as repo

MAX_AVATAR_BYTES = 2 * 1024 * 1024
AVATAR_SUFFIXES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp'}


def profile_view(db) -> dict:
    row = repo.profile(db)
    return {
        'display_name': row['display_name'],
        'auth_mode': row['auth_mode'],
        'avatar_url': f"/api/me/avatar/{row['avatar_storage_key']}" if row['avatar_storage_key'] else None,
        'revision': row['revision'],
        'updated_at': row['updated_at'],
        'capabilities': {
            'auth': False,
            'avatar_upload': True,
            'preferences': True,
            'skills': True,
        },
    }


def update_profile(db, body) -> dict:
    name = body.display_name.strip()
    if not name:
        raise ValueError('Display name cannot be empty')
    repo.update_profile(db, display_name=name)
    db.commit()
    return profile_view(db)


def avatar_path(settings: Settings, storage_key: str) -> Path:
    return Path(settings.data_dir) / 'avatars' / storage_key


def save_avatar(db, settings: Settings, data: bytes, filename: str) -> dict:
    suffix = Path(filename).suffix.lower()
    content_type = AVATAR_SUFFIXES.get(suffix)
    if content_type is None:
        raise ValueError('Only PNG, JPEG, or WebP avatars are supported')
    if not data:
        raise ValueError('Avatar file is empty')
    if len(data) > MAX_AVATAR_BYTES:
        raise ValueError('Avatar exceeds the 2MB limit')
    if not (
        (suffix == '.png' and data.startswith(b'\x89PNG\r\n\x1a\n'))
        or (suffix in {'.jpg', '.jpeg'} and data.startswith(b'\xff\xd8\xff'))
        or (suffix == '.webp' and len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP')
    ):
        raise ValueError('Avatar content does not match its file type')

    digest = hashlib.sha256(data).hexdigest()
    storage_key = digest + suffix
    target = avatar_path(settings, storage_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(data)
    repo.update_profile(db, avatar_storage_key=storage_key)
    db.commit()
    return profile_view(db)


def preferences_view(db) -> dict:
    row = repo.preference(db)
    value = json.loads(row['value_json'] or '{}') if row else {}
    return {'preferences': value, 'revision': row['revision'] if row else 0}


def update_preferences(db, body) -> dict:
    try:
        repo.upsert_preference(db, json.dumps(body.preferences, ensure_ascii=False), body.expected_revision)
    except ValueError as exc:
        db.rollback()
        if str(exc) == 'revision':
            raise ValueError('Preference revision mismatch; please refresh and retry') from exc
        raise
    except sqlite3.IntegrityError:
        db.rollback()
        raise ValueError('Preference revision mismatch; please refresh and retry') from None
    db.commit()
    return preferences_view(db)
