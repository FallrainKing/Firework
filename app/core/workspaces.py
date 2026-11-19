"""Trusted execution context, set by authentication or workspace lifecycle."""
from contextvars import ContextVar
import re
from pathlib import Path

workspace_context: ContextVar[str] = ContextVar('workspace', default='legacy')


def valid_workspace(key: str) -> bool:
    return key == 'legacy' or bool(re.fullmatch(r'[a-f0-9]{32}', key))


def workspace_path(root: Path, key: str) -> Path:
    if not valid_workspace(key):
        raise ValueError('Invalid workspace')
    if key == 'legacy':
        return root.resolve()
    path = root.resolve() / 'accounts' / key
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('Workspace links are forbidden')
    return path
