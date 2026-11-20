"""Build a deterministic XPI from first-party plugin source only."""
from pathlib import Path
import zipfile
root=Path(__file__).resolve().parents[1]
source=root/'plugins/zotero'
target=root/'app/web/downloads/firework-zotero-0.1.0.xpi'
target.parent.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
    for name in ('manifest.json','bootstrap.js','firework.js'):
        info=zipfile.ZipInfo(name,(2026,11,20,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
        info.external_attr=0o644<<16;z.writestr(info,(source/name).read_bytes())
print(target)
