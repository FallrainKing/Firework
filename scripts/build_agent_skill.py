"""Build a deterministic, credential-free portable Skill archive."""
from pathlib import Path
import zipfile
ROOT=Path(__file__).resolve().parents[1]
def build(destination=None):
    source=ROOT/'plugins/agent-skill/firework-paper-ops'
    target=Path(destination) if destination else ROOT/'app/web/downloads/firework-paper-ops.zip'
    target.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(source.rglob('*')):
            if p.is_file() and p.suffix in ('.md','.py') and '__pycache__' not in p.parts:
                info=zipfile.ZipInfo(str(Path(source.name)/p.relative_to(source)),(2026,11,22,0,0,0));info.external_attr=0o644<<16;info.compress_type=zipfile.ZIP_DEFLATED
                z.writestr(info,p.read_bytes())
    return target
if __name__=='__main__':print(build())
