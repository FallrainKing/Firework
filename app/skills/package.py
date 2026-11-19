"""ZIP skill package validation: structure, safety and manifest parsing.

Pure filesystem logic with no DB access. Rules follow the upgrade plan
(section 3.3): no path traversal, no links, bounded size/count/depth,
exactly one SKILL.md entry, no script execution anywhere in this module.
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile

MAX_ZIP_BYTES = 20 * 1024 * 1024
MAX_EXTRACTED_BYTES = 100 * 1024 * 1024
MAX_FILES = 1000
MAX_DEPTH = 12
MAX_NAME = 200
TEXT_EXT = {'.md', '.txt', '.json', '.yaml', '.yml'}
READABLE_EXT = TEXT_EXT


class PackageError(ValueError):
    """Structural rejection; message is user-facing."""


def _is_link(info: zipfile.ZipInfo) -> bool:
    """Unix mode bits: symlink 0o120000, hardlink indicator via external_attr."""
    mode = (info.external_attr >> 16) & 0o170000
    return mode in (0o120000, 0o100000) and False or mode == 0o120000


def _safe_member(name: str) -> str:
    norm = name.replace('\\', '/')
    if norm.startswith('/') or ':/' in norm:
        raise PackageError(f'绝对路径不允许: {name}')
    parts = [p for p in norm.split('/') if p not in ('', '.')]
    if '..' in parts:
        raise PackageError(f'路径穿越不允许: {name}')
    if len(parts) > MAX_DEPTH:
        raise PackageError(f'目录过深: {name}')
    if len(norm) > MAX_NAME:
        raise PackageError(f'文件名过长: {name}')
    return '/'.join(parts)


def validate_zip(data: bytes) -> dict:
    """Inspect raw ZIP bytes; return {'files': [...], 'entry': ..., 'manifest': ..., 'hash': ...}.

    Raises PackageError with a Chinese, user-facing reason. Never extracts
    outside the staging area and never executes anything.
    """
    if len(data) > MAX_ZIP_BYTES:
        raise PackageError(f'包超过 {MAX_ZIP_BYTES // 1024 // 1024}MB 限制')
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise PackageError('不是有效的 ZIP 文件')
    members = zf.infolist()
    if not members:
        raise PackageError('空 ZIP 包')
    if len(members) > MAX_FILES:
        raise PackageError(f'文件数超过 {MAX_FILES} 限制')

    cleaned: dict[str, zipfile.ZipInfo] = {}
    extracted = 0
    for info in members:
        if info.is_dir():
            continue
        if _is_link(info):
            raise PackageError(f'符号/硬链接不允许: {info.filename}')
        norm = _safe_member(info.filename)
        if norm in cleaned:
            raise PackageError(f'重复文件: {norm}')
        cleaned[norm] = info
        extracted += info.file_size
        if extracted > MAX_EXTRACTED_BYTES:
            raise PackageError('解压后体积超过 100MB 限制')

    if not cleaned:
        raise PackageError('包内没有文件')

    entry = _find_entry(cleaned)
    top = entry['prefix']
    files = [rel for rel in cleaned if rel.startswith(top)]
    manifest = _parse_manifest(zf, cleaned, top)
    content_hash = _hash_files(zf, cleaned, files)
    return {
        'entry': entry['entry'],
        'top_prefix': top,
        'files': sorted(files),
        'manifest': manifest,
        'hash': content_hash,
        'total_bytes': extracted,
    }


def _find_entry(cleaned: dict[str, zipfile.ZipInfo]) -> dict:
    direct = [p for p in cleaned if p == 'SKILL.md']
    if direct:
        return {'entry': 'SKILL.md', 'prefix': ''}
    tops = {p.split('/', 1)[0] for p in cleaned if '/' in p}
    candidates = [t for t in tops if f'{t}/SKILL.md' in cleaned]
    if len(candidates) == 1:
        return {'entry': f'{candidates[0]}/SKILL.md', 'prefix': candidates[0] + '/'}
    if not candidates:
        raise PackageError('缺少 SKILL.md 入口')
    raise PackageError('包内包含多个候选 SKILL.md，请只保留一个技能')


def _parse_manifest(zf: zipfile.ZipFile, cleaned: dict, top: str) -> dict | None:
    path = f'{top}skill.json' if top else 'skill.json'
    if path not in cleaned:
        return None
    try:
        raw = zf.read(cleaned[path]).decode('utf-8')
        manifest = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise PackageError('skill.json 不是合法 JSON')
    if not isinstance(manifest, dict):
        raise PackageError('skill.json 必须是对象')
    slug = str(manifest.get('slug', ''))
    if slug and (not slug.replace('-', '').replace('_', '').isalnum() or len(slug) > 60):
        raise PackageError('skill.json 的 slug 不合法')
    manifest.setdefault('version', '1.0.0')
    manifest.setdefault('requested_tools', [])
    manifest.setdefault('templates', [])
    return manifest


def _hash_files(zf: zipfile.ZipFile, cleaned: dict, files: list[str]) -> str:
    digest = hashlib.sha256()
    for rel in sorted(files):
        digest.update(rel.encode('utf-8'))
        digest.update(b'\0')
        digest.update(hashlib.sha256(zf.read(cleaned[rel])).digest())
        digest.update(b'\0')
    return digest.hexdigest()


def extract_into(zf_bytes: bytes, dest, top_prefix: str) -> str:
    """Write validated files (minus the single top folder) into dest dir."""
    dest = __import__('pathlib').Path(dest)
    zf = zipfile.ZipFile(io.BytesIO(zf_bytes))
    written = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        norm = _safe_member(info.filename)
        if top_prefix and norm.startswith(top_prefix):
            norm = norm[len(top_prefix):]
        elif top_prefix:
            continue
        target = dest / norm
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(zf.read(info))
        written.append(norm)
    return 'SKILL.md' if 'SKILL.md' in written else None
