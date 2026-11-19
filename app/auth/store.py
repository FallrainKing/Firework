"""Identity DB: salted password hashes, opaque sessions, throttling and audit."""
from __future__ import annotations
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
import uuid

ITERATIONS = 600_000
COOKIE = '__Host-research_session'


def password_hash(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), ITERATIONS)
    return f'pbkdf2_sha256${ITERATIONS}${salt}${digest.hex()}'


def verify_password(password: str, encoded: str) -> bool:
    try:
        kind, rounds, salt, expected = encoded.split('$')
        if kind != 'pbkdf2_sha256' or int(rounds) != ITERATIONS:
            return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def username(value: str) -> str:
    value = value.strip().casefold()
    if not re.fullmatch(r'[a-z0-9][a-z0-9_.@-]{2,79}', value):
        raise ValueError('账号使用 3–80 位字母、数字或 _ . @ -')
    return value


def new_password(value: str):
    if not 12 <= len(value) <= 256:
        raise ValueError('新密码需为 12–256 个字符')
    return value


class AuthStore:
    def __init__(self, root: Path, *, admin_only=True, secure_cookie=True, public_origin='https://paper.matchesai.vip'):
        self.root = root.resolve()
        folder = self.root / 'auth'
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        folder.chmod(0o700)
        self.db = sqlite3.connect(folder / 'accounts.db', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA busy_timeout=5000')
        self.db.executescript(Path(__file__).with_name('schema.sql').read_text())
        (folder / 'accounts.db').chmod(0o600)
        self.admin_only = admin_only
        self.secure_cookie = secure_cookie
        self.public_origin = public_origin.rstrip('/')
        self.dummy_hash = password_hash(secrets.token_urlsafe(32))

    @property
    def cookie_name(self):
        return COOKIE if self.secure_cookie else 'research_session_dev'

    @classmethod
    def from_env(cls, root):
        return cls(root, admin_only=os.getenv('RESEARCH_AUTH_ADMIN_ONLY', '1') != '0',
                   secure_cookie=os.getenv('RESEARCH_AUTH_COOKIE_SECURE', '1') != '0',
                   public_origin=os.getenv('RESEARCH_PUBLIC_ORIGIN', 'https://paper.matchesai.vip'))

    def close(self):
        self.db.close()

    def audit(self, actor, action, target=None):
        self.db.execute('INSERT INTO auth_audit(actor_id,action,target_id,created_at) VALUES (?,?,?,?)',
                        (actor, action, target, int(time.time())))

    def account(self, ident):
        r = self.db.execute('SELECT * FROM accounts WHERE id=?', (ident,)).fetchone()
        return dict(r) if r else None

    def by_username(self, name):
        r = self.db.execute('SELECT * FROM accounts WHERE username=? COLLATE NOCASE', (name,)).fetchone()
        return dict(r) if r else None

    def by_workspace(self, key):
        r = self.db.execute('SELECT * FROM accounts WHERE workspace_key=?', (key,)).fetchone()
        return dict(r) if r else None

    def primary_id(self):
        r = self.db.execute("SELECT value FROM auth_meta WHERE key='primary_admin'").fetchone()
        return r[0] if r else None

    def login_allowed(self, a):
        return bool(a and a['enabled'] and (not self.admin_only or a['id'] == self.primary_id()))

    def bootstrap(self, name, password):
        if self.primary_id():
            raise ValueError('管理员已初始化，未覆盖原账号')
        name = username(name)
        if not password or len(password) > 256:
            raise ValueError('现有密码不可为空或超过 256 字符')
        ident = uuid.uuid4().hex
        encoded = password_hash(password)
        try:
            self.db.execute('BEGIN IMMEDIATE')
            if self.primary_id():
                raise ValueError('管理员已初始化，未覆盖原账号')
            self.db.execute('INSERT INTO accounts(id,username,password_hash,role,enabled,workspace_key,created_at) VALUES (?,?,?,\'admin\',1,\'legacy\',?)',
                            (ident,name,encoded,int(time.time())))
            self.db.execute("INSERT INTO auth_meta VALUES ('primary_admin',?)",(ident,))
            self.audit(ident,'bootstrap-admin',ident)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self.public(self.account(ident))

    @staticmethod
    def public(a):
        return {k:a[k] for k in ('id','username','role','enabled','created_at','last_login_at')}

    def issue_session(self, account, *, minutes=720):
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        now = int(time.time())
        self.db.execute('INSERT INTO auth_sessions VALUES (?,?,?,?,?,?,0)',
                        (token_hash(token),account['id'],csrf,account['session_version'],now,now+minutes*60))
        self.db.execute('UPDATE accounts SET last_login_at=? WHERE id=?',(now,account['id']))
        self.audit(account['id'],'login',account['id'])
        # Expired/revoked bearer hashes no longer need indefinite retention.
        self.db.execute('DELETE FROM auth_sessions WHERE expires_at<?',(now-86400,))
        self.db.commit()
        return token,csrf

    def session(self, token):
        if not token or len(token) > 128:
            return None
        r = self.db.execute('''SELECT a.*,s.csrf,s.token_hash,s.expires_at FROM auth_sessions s JOIN accounts a ON a.id=s.account_id
            WHERE s.token_hash=? AND s.revoked=0 AND s.expires_at>? AND s.session_version=a.session_version''',
            (token_hash(token),int(time.time()))).fetchone()
        return dict(r) if r and self.login_allowed(r) else None

    def revoke(self, token):
        self.db.execute('UPDATE auth_sessions SET revoked=1 WHERE token_hash=?',(token_hash(token),))
        self.db.commit()

    def throttle(self, name, address):
        now = int(time.time())
        keys=[('name:'+name.casefold(),10),('ip:'+address,40)]
        for raw,limit in keys:
            key=token_hash(raw)
            r=self.db.execute('SELECT * FROM auth_attempts WHERE key=?',(key,)).fetchone()
            if r and now-r['window_start']<900 and r['attempts']>=limit:
                return False
        for raw,_ in keys:
            key=token_hash(raw)
            self.db.execute('''INSERT INTO auth_attempts VALUES (?,?,1) ON CONFLICT(key) DO UPDATE SET
                attempts=CASE WHEN window_start<? THEN 1 ELSE attempts+1 END,
                window_start=CASE WHEN window_start<? THEN excluded.window_start ELSE window_start END''',
                (key,now,now-900,now-900))
        self.db.execute('DELETE FROM auth_attempts WHERE window_start<?',(now-86400,))
        self.db.commit()
        return True

    def clear_name_throttle(self,name):
        self.db.execute('DELETE FROM auth_attempts WHERE key=?',(token_hash('name:'+name.casefold()),))
        self.db.commit()
