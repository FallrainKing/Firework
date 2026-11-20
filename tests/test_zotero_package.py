"""The real Zotero 10 manifest requirements must be enforced at build time."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('zotero_package', ROOT / 'scripts/build_zotero_plugin.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PackageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(ROOT / 'plugins/zotero', self.root / 'plugins/zotero')

    def test_required_update_url_prevents_invalid_install_package(self):
        p = self.root / 'plugins/zotero/manifest.json'
        manifest = json.loads(p.read_text())
        del manifest['applications']['zotero']['update_url']
        p.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'update_url'):
            module.build(self.root)
        self.assertFalse((self.root / 'app/web/downloads').exists())

    def test_feed_version_hash_and_download_match_package(self):
        package = module.build(self.root)
        data = package.read_bytes()
        self.assertEqual(module.build(self.root).read_bytes(), data)
        with zipfile.ZipFile(package) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(sorted(archive.namelist()), ['bootstrap.js', 'firework.js', 'manifest.json'])
            manifest = json.loads(archive.read('manifest.json'))
        app = manifest['applications']['zotero']
        feed = json.loads((package.parent / 'firework-zotero-updates.json').read_text())
        update = feed['addons'][app['id']]['updates'][0]
        self.assertEqual(update['version'], manifest['version'])
        self.assertTrue(update['update_link'].endswith('/' + package.name))
        self.assertEqual(update['update_hash'], 'sha256:' + hashlib.sha256(data).hexdigest())
        self.assertEqual((package.parent / 'firework-zotero-0.1.0.xpi').read_bytes(), data)


if __name__ == '__main__':
    unittest.main()
