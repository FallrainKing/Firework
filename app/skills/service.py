"""Dynamic skill import, registry, and execution-policy services."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from ..agent.catalog import SKILLS as BUILTIN_SKILLS
from ..core.config import Settings
from . import package, repository as repo


BUILTIN_VERSION = '0.4.0'
DEFAULT_CATEGORIES = ('阅读理解', '方法实验', '审查比较', '检索监控', '写作整理', '未分类')
_BUILTIN_MANIFEST_VERSION = 1
SHORT_PROFILE = {'max_turns': 6, 'max_output_tokens': 1024, 'timeout_s': 120, 'max_budget_usd': 0.10}
READ_PROFILE = {'max_turns': 30, 'max_output_tokens': 8192, 'timeout_s': None, 'max_budget_usd': 1.00}
ALLOWED_TOOLS = {
    'paper_search', 'paper_import', 'library_search', 'arxiv_search',
    'paper_read', 'paper_page', 'skill_resource',
    'frontier_context','frontier_search','frontier_report',
}


def _hash_manifest(manifest: dict[str, Any]) -> str:
    raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _builtin_manifest(skill_id: str) -> dict[str, Any]:
    cfg = BUILTIN_SKILLS[skill_id]
    return {
        'schema_version': _BUILTIN_MANIFEST_VERSION,
        'name': cfg['name'],
        'slug': skill_id,
        'version': BUILTIN_VERSION,
        'description': cfg['name'],
        'entry': 'SKILL.md',
        'task_kind': 'custom',
        'requested_tools': cfg['tools'],
        'capabilities': {'vision_required': False},
        'budget_profile': 'read' if skill_id in {'paper_read', 'paper_review', 'paper_compare'} else 'short',
    }


def ensure_builtin_skills(db) -> None:
    """Idempotently register built-in skills and default categories."""
    if repo.count_skills(db) == 0:
        for name in DEFAULT_CATEGORIES:
            repo.insert_category(db, name, DEFAULT_CATEGORIES.index(name))
    for skill_id, cfg in BUILTIN_SKILLS.items():
        if repo.find_skill(db, skill_id) is None:
            repo.insert_skill(
                db,
                ident=skill_id,
                name=cfg['name'],
                description=cfg['name'],
                source='builtin',
                status='enabled',
            )
        manifest = _builtin_manifest(skill_id)
        content_hash = _hash_manifest(manifest)
        if repo.find_version_by_hash(db, content_hash) is None:
            version_id = repo.insert_version(
                db,
                skill_id=skill_id,
                version=BUILTIN_VERSION,
                content_hash=content_hash,
                storage_key='',
                entry='SKILL.md',
                manifest_json=json.dumps(manifest, ensure_ascii=False),
                validation_status='validated',
            )
            repo.set_default_version(db, skill_id, version_id)
    db.commit()


def _skills_dir(settings: Settings) -> Path:
    root = Path(settings.data_dir) / 'skills'
    root.mkdir(parents=True, exist_ok=True)
    return root


def _archive_path(settings: Settings, archive_hash: str) -> Path:
    path = _skills_dir(settings) / 'archives' / f'{archive_hash}.zip'
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _package_root(settings: Settings, storage_key: str) -> Path:
    return Path(settings.data_dir) / 'skills' / storage_key


def import_skill_archive(db, settings: Settings, data: bytes, filename: str = '') -> dict:
    """Validate and stage a ZIP without calling any model or executing code."""
    ensure_builtin_skills(db)
    result = package.validate_zip(data)
    archive_hash = result['hash']
    archive_path = _archive_path(settings, archive_hash)
    if not archive_path.exists():
        archive_path.write_bytes(data)
    existing = repo.import_by_hash(db, archive_hash)
    if existing is not None:
        return view_import(db, existing['id'])

    ident = uuid.uuid4().hex
    candidate = {
        'entry': result['entry'],
        'top_prefix': result['top_prefix'],
        'files': result['files'],
        'manifest': result['manifest'],
        'total_bytes': result['total_bytes'],
        'archive_hash': archive_hash,
        'filename': filename,
    }
    repo.insert_import(
        db,
        ident=ident,
        status='awaiting_config',
        filename=filename,
        report_json=json.dumps({'ok': True}, ensure_ascii=False),
        candidate_json=json.dumps(candidate, ensure_ascii=False),
        archive_hash=archive_hash,
        request_key=archive_hash,
    )
    db.commit()
    return view_import(db, ident)


def view_import(db, import_id: str) -> dict:
    row = repo.find_import(db, import_id)
    if row is None:
        raise ValueError('Import not found')
    candidate = json.loads(row['candidate_json'] or '{}')
    result_version = repo.find_version(db, row['result_version_id']) if row['result_version_id'] else None
    return {
        'import_id': row['id'],
        'status': row['status'],
        'filename': row['filename'],
        'archive_hash': row['archive_hash'],
        'manifest': candidate.get('manifest'),
        'entry': candidate.get('entry'),
        'files': candidate.get('files', []),
        'total_bytes': candidate.get('total_bytes', 0),
        'skill': view_skill(db, result_version['skill_id']) if result_version else None,
        'version': view_version(result_version) if result_version else None,
    }


def _category_ids_by_names(db, names: list[str]) -> list[int]:
    ids: list[int] = []
    for name in names:
        name = name.strip()
        if not name:
            continue
        row = repo.find_category_by_name(db, name)
        if row is None:
            ids.append(repo.insert_category(db, name))
        else:
            ids.append(row['id'])
    return ids


def install_skill(db, settings: Settings, import_id: str, body) -> dict:
    """Install a validated ZIP as an immutable, initially disabled version."""
    row = repo.find_import(db, import_id)
    package_root = _package_root(settings, f"packages/{row['archive_hash']}") if row else None
    package_existed = package_root is not None and package_root.exists()
    try:
        return _install_skill(db, settings, import_id, body)
    except Exception:
        db.rollback()
        if package_root is not None and not package_existed and package_root.exists():
            shutil.rmtree(package_root, ignore_errors=True)
        raise


def _prepare_package_for_runner(settings: Settings, package_root: Path) -> None:
    """Root container writes; host Runner reads as the shared data owner."""
    skills_root = _skills_dir(settings)
    paths = [skills_root, skills_root / 'packages', package_root, *package_root.rglob('*')]
    owner = Path(settings.data_dir).stat()
    for path in paths:
        if os.geteuid() == 0:
            os.chown(path, owner.st_uid, owner.st_gid)
        path.chmod(0o700 if path.is_dir() else 0o600)


def _install_skill(db, settings: Settings, import_id: str, body) -> dict:
    row = repo.find_import(db, import_id)
    if row is None:
        raise ValueError('Import not found')
    if row['status'] != 'awaiting_config':
        raise ValueError('Import is not awaiting configuration')
    candidate = json.loads(row['candidate_json'] or '{}')
    manifest = candidate.get('manifest') or {}
    requested_tools = list(manifest.get('requested_tools') or [])
    invalid_tools = [tool for tool in requested_tools if tool not in ALLOWED_TOOLS]
    if invalid_tools:
        repo.update_import(
            db,
            import_id,
            status='rejected',
            report_json=json.dumps({'ok': False, 'errors': [f'不支持的工具: {tool}' for tool in invalid_tools]}, ensure_ascii=False),
        )
        db.commit()
        raise ValueError(f'不支持的工具: {", ".join(invalid_tools)}')

    archive_hash = row['archive_hash']
    archive_path = _archive_path(settings, archive_hash)
    if not archive_path.exists():
        raise ValueError('Archive file missing; please upload again')

    version = body.default_version or str(manifest.get('version') or '1.0.0')
    if body.skill_id:
        target = repo.find_skill(db, body.skill_id)
        if target is None or target['source'] != 'zip':
            raise ValueError('Target skill does not exist or is not a custom skill')
        if repo.find_version_by_skill_version(db, body.skill_id, version) is not None:
            raise ValueError('Skill version already exists; use a different version number')
        skill_id = body.skill_id
        created_skill = False
    else:
        skill_id = f'custom:{uuid.uuid4().hex}'
        repo.insert_skill(
            db,
            ident=skill_id,
            name=body.name,
            description=body.description or manifest.get('description', ''),
            source='zip',
            status='disabled',
        )
        created_skill = True
    entry = candidate.get('entry') or 'SKILL.md'
    top_prefix = candidate.get('top_prefix') or ''
    if top_prefix and entry.startswith(top_prefix):
        entry = entry[len(top_prefix):]
    version_id = repo.insert_version(
        db,
        skill_id=skill_id,
        version=version,
        content_hash=archive_hash,
        storage_key=f'packages/{archive_hash}',
        entry=entry,
        manifest_json=json.dumps({**manifest, 'budget_profile': body.budget_profile}, ensure_ascii=False),
        validation_status='validated',
    )
    package_root = _package_root(settings, f'packages/{archive_hash}')
    if package_root.exists():
        raise ValueError('Skill package already exists')
    staging = _skills_dir(settings) / 'staging'
    staging.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f'install-{import_id}-', dir=staging) as temp:
        temp_root = Path(temp)
        package.extract_into(archive_path.read_bytes(), temp_root, candidate.get('top_prefix') or '')
        shutil.move(str(temp_root), str(package_root))
    _prepare_package_for_runner(settings, package_root)
    if created_skill:
        repo.set_default_version(db, skill_id, version_id)

    manifest_templates = manifest.get('templates') or []
    if not manifest_templates:
        manifest_templates = [{'name': body.name, 'description': body.description or manifest.get('description', '')}]
    for item in manifest_templates:
        template_name = str(item.get('name') or body.name)[:80]
        description = str(item.get('description') or body.description or '')[:400]
        template_file = str(item.get('file') or '')
        prompt = ''
        if template_file:
            template_path = package_root / template_file
            if (template_path.resolve().relative_to(package_root.resolve())
                    and template_path.is_file()
                    and template_path.suffix.lower() in package.TEXT_EXT):
                prompt = template_path.read_text(encoding='utf-8')[:3000]
        repo.insert_dynamic_template(
            db,
            ident='custom_' + uuid.uuid4().hex,
            name=template_name,
            description=description,
            kind='custom',
            skill=skill_id,
            prompt=prompt,
            skill_version_id=version_id,
            source_template_key=template_file,
        )

    if created_skill:
        category_names = body.category_names or ['未分类']
        repo.set_categories(db, skill_id, _category_ids_by_names(db, category_names))
    repo.update_import(
        db,
        import_id,
        status='installed',
        result_version_id=version_id,
        report_json=json.dumps({'ok': True, 'installed': True}, ensure_ascii=False),
    )
    repo.audit(
        db,
        skill_id=skill_id,
        version_id=version_id,
        action='install',
        detail_json=json.dumps({'import_id': import_id, 'archive_hash': archive_hash}, ensure_ascii=False),
    )
    db.commit()
    return {
        'status': 'installed',
        'skill': view_skill(db, skill_id),
        'version': view_version(repo.find_version(db, version_id)),
    }


def view_skill(db, skill_id: str) -> dict:
    row = repo.find_skill(db, skill_id)
    if row is None:
        raise ValueError('Skill not found')
    versions = repo.versions_for_skill(db, skill_id)
    category_ids = set(repo.skill_category_ids(db, skill_id))
    default_version = repo.find_version(db, row['default_version_id']) if row['default_version_id'] else None
    return {
        'id': row['id'],
        'name': row['name'],
        'description': row['description'],
        'source': row['source'],
        'status': row['status'],
        'default_version_id': row['default_version_id'],
        'default_version': view_version(default_version) if default_version else None,
        'revision': row['revision'],
        'created_at': row['created_at'],
        'categories': [dict(c) for c in repo.list_categories(db) if c['id'] in category_ids],
        'versions': [view_version(v) for v in versions],
    }


def view_version(row) -> dict:
    if row is None:
        raise ValueError('Version not found')
    manifest = json.loads(row['manifest_json'] or '{}')
    return {
        'id': row['id'],
        'skill_id': row['skill_id'],
        'version': row['version'],
        'content_hash': row['content_hash'],
        'storage_key': row['storage_key'],
        'entry': row['entry'],
        'manifest': manifest,
        'validation_status': row['validation_status'],
        'created_at': row['created_at'],
    }


def list_skills_view(db, **filters) -> dict:
    ensure_builtin_skills(db)
    rows = repo.list_skills(db, **filters)
    return {'skills': [view_skill(db, r['id']) for r in rows], 'registry_revision': repo.latest_revision(db)}


def skill_detail(db, skill_id: str) -> dict:
    ensure_builtin_skills(db)
    return view_skill(db, skill_id)


def versions_view(db, skill_id: str) -> dict:
    ensure_builtin_skills(db)
    row = repo.find_skill(db, skill_id)
    if row is None:
        raise ValueError('Skill not found')
    return {
        'skill_id': skill_id,
        'default_version_id': row['default_version_id'],
        'registry_revision': repo.latest_revision(db),
        'versions': [
            {
                **view_version(version),
                'is_default': version['id'] == row['default_version_id'],
                'references': repo.version_usage_counts(db, version['id']),
            }
            for version in repo.versions_for_skill(db, skill_id)
        ],
    }


def set_default_version(db, skill_id: str, body) -> dict:
    ensure_builtin_skills(db)
    skill = repo.find_skill(db, skill_id)
    if skill is None:
        raise ValueError('Skill not found')
    if body.expected_revision is not None and skill['revision'] != body.expected_revision:
        raise ValueError('Skill revision mismatch; please refresh and retry')

    version = repo.find_version(db, body.version_id)
    if version is None or version['skill_id'] != skill_id:
        raise ValueError('Version does not belong to this skill')
    if version['validation_status'] != 'validated':
        raise ValueError('Only validated versions can become default')

    previous_version_id = skill['default_version_id']
    if previous_version_id != version['id']:
        repo.set_default_version(db, skill_id, version['id'])
        repo.audit(
            db,
            skill_id=skill_id,
            version_id=version['id'],
            action='default-version',
            detail_json=json.dumps(
                {'previous_version_id': previous_version_id, 'new_version_id': version['id']},
                ensure_ascii=False,
            ),
        )
        db.commit()
    return view_skill(db, skill_id)


def enable_skill(db, skill_id: str) -> dict:
    row = repo.find_skill(db, skill_id)
    if row is None:
        raise ValueError('Skill not found')
    version = repo.default_version(db, skill_id)
    if version is None or version['validation_status'] != 'validated':
        raise ValueError('Skill has no compatible default version')
    repo.set_skill_status(db, skill_id, 'enabled')
    repo.audit(db, skill_id=skill_id, version_id=version['id'], action='enable')
    db.commit()
    return view_skill(db, skill_id)


def disable_skill(db, skill_id: str) -> dict:
    row = repo.find_skill(db, skill_id)
    if row is None:
        raise ValueError('Skill not found')
    repo.set_skill_status(db, skill_id, 'disabled')
    repo.audit(db, skill_id=skill_id, action='disable')
    db.commit()
    return view_skill(db, skill_id)


def update_skill(db, skill_id: str, body) -> dict:
    row = repo.find_skill(db, skill_id)
    if row is None:
        raise ValueError('Skill not found')
    repo.update_skill_meta(
        db,
        skill_id,
        name=body.name,
        description=body.description,
    )
    if body.category_ids is not None:
        repo.set_categories(db, skill_id, body.category_ids)
    if body.status is not None:
        repo.set_skill_status(db, skill_id, body.status)
    repo.audit(db, skill_id=skill_id, action='update')
    db.commit()
    return view_skill(db, skill_id)


def list_categories_view(db) -> list[dict]:
    ensure_builtin_skills(db)
    return [dict(row) for row in repo.list_categories(db)]


def create_category(db, body) -> dict:
    row = repo.find_category_by_name(db, body.name)
    if row is not None:
        raise ValueError('Category already exists')
    category_id = repo.insert_category(db, body.name, body.sort_order)
    db.commit()
    row = next(c for c in repo.list_categories(db) if c['id'] == category_id)
    return dict(row)


def update_category(db, category_id: int, body) -> dict:
    row = next((c for c in repo.list_categories(db) if c['id'] == category_id), None)
    if row is None:
        raise ValueError('Category not found')
    repo.rename_category(db, category_id, body.name)
    db.commit()
    return dict(next(c for c in repo.list_categories(db) if c['id'] == category_id))


def delete_category(db, category_id: int) -> None:
    row = next((c for c in repo.list_categories(db) if c['id'] == category_id), None)
    if row is None:
        raise ValueError('Category not found')
    repo.delete_category(db, category_id)
    db.commit()


def registry_view(db) -> dict:
    ensure_builtin_skills(db)
    return {
        'registry_revision': repo.latest_revision(db),
        'skills': [
            {'id': r['id'], 'name': r['name'], 'source': r['source'], 'status': r['status']}
            for r in repo.list_skills(db)
        ],
    }


def execution_policy(db, skill_id: str, version_id: int | None = None) -> dict:
    """Return the policy used by the runner for a concrete skill version."""
    row = repo.find_skill(db, skill_id)
    if row is None or row['status'] != 'enabled':
        raise ValueError('Skill unavailable')
    version = repo.find_version(db, version_id) if version_id else repo.default_version(db, skill_id)
    if version is None or version['validation_status'] != 'validated':
        raise ValueError('Skill version unavailable')
    if row['source'] == 'builtin':
        cfg = BUILTIN_SKILLS[skill_id]
        return {
            **cfg,
            'id': skill_id,
            'name': row['name'],
            'version_id': version['id'],
            'version': version['version'],
            'skill_hash': version['content_hash'],
            'storage_key': version['storage_key'],
            'entry': version['entry'],
            'budget_profile': 'read' if skill_id in {'paper_read', 'paper_review', 'paper_compare'} else 'short',
        }
    manifest = json.loads(version['manifest_json'] or '{}')
    profile = READ_PROFILE if manifest.get('budget_profile') == 'read' else SHORT_PROFILE
    requested_tools = [tool for tool in (manifest.get('requested_tools') or []) if tool in ALLOWED_TOOLS]
    return {
        'id': skill_id,
        'name': row['name'],
        'tools': requested_tools,
        'max_calls': 4,
        'version_id': version['id'],
        'version': version['version'],
        'skill_hash': version['content_hash'],
        'storage_key': version['storage_key'],
        'entry': version['entry'],
        'budget_profile': manifest.get('budget_profile', 'short'),
        **profile,
    }


def skill_markdown_path(settings: Settings, policy: dict[str, Any]) -> Path:
    if not policy.get('storage_key'):
        return Path(__file__).resolve().parents[2] / 'skills' / policy['id'] / policy.get('entry', 'SKILL.md')
    return Path(settings.data_dir) / 'skills' / policy['storage_key'] / policy.get('entry', 'SKILL.md')


def _version_root(settings: Settings, version) -> Path:
    if version['storage_key']:
        return Path(settings.data_dir) / 'skills' / version['storage_key']
    return Path(__file__).resolve().parents[2] / 'skills' / version['skill_id']


def _version_for_skill(db, skill_id: str, version_id: int):
    version = repo.find_version(db, version_id)
    if version is None or version['skill_id'] != skill_id:
        raise ValueError('Version does not belong to this skill')
    return version


def version_resources_view(db, settings: Settings, skill_id: str, version_id: int) -> dict:
    ensure_builtin_skills(db)
    if repo.find_skill(db, skill_id) is None:
        raise ValueError('Skill not found')
    version = _version_for_skill(db, skill_id, version_id)
    root = _version_root(settings, version).resolve()
    resources = []
    for path in root.rglob('*'):
        if len(resources) >= 1000:
            raise ValueError('Skill package contains too many previewable resources')
        if path.is_symlink() or not path.is_file():
            continue
        if path.suffix.lower() not in package.TEXT_EXT:
            continue
        rel = path.relative_to(root).as_posix()
        resources.append({
            'path': rel,
            'size_bytes': path.stat().st_size,
            'is_entry': rel == version['entry'],
            'readable': path.stat().st_size <= 1024 * 1024,
        })
    return {
        'skill_id': skill_id,
        'version_id': version_id,
        'resources': sorted(resources, key=lambda item: (not item['is_entry'], item['path'])),
    }


def version_resource_content_view(db, settings: Settings, skill_id: str, version_id: int, path: str) -> dict:
    ensure_builtin_skills(db)
    if repo.find_skill(db, skill_id) is None:
        raise ValueError('Skill not found')
    version = _version_for_skill(db, skill_id, version_id)
    rel = Path(path)
    if rel.is_absolute() or '..' in rel.parts:
        raise ValueError('Only relative paths inside the skill package are allowed')
    root = _version_root(settings, version).resolve()
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise ValueError('Path escapes the skill package') from None
    if target.is_symlink() or target.suffix.lower() not in package.TEXT_EXT:
        raise ValueError('Resource type is not allowed')
    if not target.is_file():
        raise ValueError('Resource not found')
    if target.stat().st_size > 1024 * 1024:
        raise ValueError('Resource exceeds the 1MB limit')
    try:
        content = target.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        raise ValueError('Resource is not valid UTF-8 text') from None
    return {
        'skill_id': skill_id,
        'version_id': version_id,
        'path': rel.as_posix(),
        'size_bytes': target.stat().st_size,
        'content': content[:200_000],
        'truncated': len(content) > 200_000,
    }


def record_validate_run(db, skill_id: str, version_id: int | None, run_id: str) -> None:
    repo.audit(
        db,
        skill_id=skill_id,
        version_id=version_id,
        action='validate-run',
        detail_json=json.dumps({'run_id': run_id, 'explicit_model_invocation': True}, ensure_ascii=False),
    )
    db.commit()


def skill_audit_view(db, skill_id: str, limit: int = 100, offset: int = 0) -> dict:
    ensure_builtin_skills(db)
    if repo.find_skill(db, skill_id) is None:
        raise ValueError('Skill not found')
    rows = repo.audits_for_skill(db, skill_id, limit=limit, offset=offset)
    return {
        'skill_id': skill_id,
        'audit': [
            {
                'id': row['id'],
                'skill_id': row['skill_id'],
                'version_id': row['version_id'],
                'action': row['action'],
                'detail': json.loads(row['detail_json'] or '{}'),
                'created_at': row['created_at'],
            }
            for row in rows
        ],
    }
