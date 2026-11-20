"""Build a deterministic XPI and its Zotero update feed; validate before packaging."""
from pathlib import Path
import hashlib
import json
import re
from urllib.parse import urlparse
import zipfile


def build(root: Path) -> Path:
    source = root / 'plugins/zotero'
    manifest = json.loads((source / 'manifest.json').read_text())
    app = manifest.get('applications', {}).get('zotero', {})
    for field in ('id', 'update_url', 'strict_min_version', 'strict_max_version'):
        if not isinstance(app.get(field), str) or not app[field].strip():
            raise ValueError('Missing required Zotero manifest field: ' + field)
    version = manifest.get('version', '')
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Invalid plugin version')
    url = urlparse(app['update_url'])
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment or url.path != '/downloads/firework-zotero-updates.json':
        raise ValueError('Invalid HTTPS update feed URL')
    target = root / 'app/web/downloads' / f'firework-zotero-{version}.xpi'
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in ('manifest.json', 'bootstrap.js', 'firework.js'):
            info = zipfile.ZipInfo(name, (2026, 11, 20, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, (source / name).read_bytes())
    payload = target.read_bytes()
    update = {'version': version, 'update_link': app['update_url'].rsplit('/', 1)[0] + '/' + target.name,
              'update_hash': 'sha256:' + hashlib.sha256(payload).hexdigest(),
              'applications': {'zotero': {key: app[key] for key in ('strict_min_version', 'strict_max_version')}}}
    feed = {'addons': {app['id']: {'updates': [update]}}}
    (target.parent / 'firework-zotero-updates.json').write_text(json.dumps(feed, indent=2) + '\n')
    # Cached v0.1.0 download pages must also receive the corrected manifest.
    for old in ('0.1.0','0.1.1'):
        if target.name != f'firework-zotero-{old}.xpi':
            (target.parent / f'firework-zotero-{old}.xpi').write_bytes(payload)
    return target


if __name__ == '__main__':
    print(build(Path(__file__).resolve().parents[1]))
