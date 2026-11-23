"""Freeze authorized file identities; successful tool evidence records actual reads."""
import hashlib
import json
from pathlib import Path
from ..core.errors import ServiceError

def snapshot(db,settings,conversation_id):
    out=[]
    for row in db.execute('SELECT p.* FROM papers p JOIN conversation_papers cp ON cp.paper_id=p.id WHERE cp.conversation_id=?',(conversation_id,)):
        version=db.execute('SELECT v.*,f.storage_key FROM document_versions v JOIN file_objects f ON f.hash=v.file_hash WHERE v.id=?',(row['default_version_id'],)).fetchone()
        if version:
            out.append({'paper_id':row['id'],'document_version_id':version['id'],'file_version':version['file_hash'],'storage_key':'papers/'+version['storage_key']})
        elif row['pdf_path']:
            path=Path(row['pdf_path'])
            try:relative=path.resolve().relative_to(settings.data_dir.resolve())
            except ValueError:raise ServiceError(409,'原文不在当前账号资料目录中') from None
            if path.is_symlink() or not path.is_file():raise ServiceError(409,'原文不可读取')
            with path.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
            out.append({'paper_id':row['id'],'document_version_id':None,'file_version':digest,'storage_key':str(relative)})
        else:out.append({'paper_id':row['id'],'document_version_id':None,'file_version':None,'storage_key':None})
    return out

def frozen(db,run_id):
    r=db.execute('SELECT * FROM material_manifests WHERE run_id=?',(run_id,)).fetchone()
    return {'authorized':json.loads(r['authorized_json']),'actual':json.loads(r['actual_json'])} if r else {'authorized':[],'actual':[],'legacy':True}

def record_actual(db,run_id,calls):
    manifest=frozen(db,run_id);allowed={(r['paper_id'],r.get('file_version')) for r in manifest['authorized']};actual=[]
    for call in calls:
        if not call.get('ok'):continue
        for item in call.get('materials',[]):
            if (item.get('paper_id'),item.get('file_version')) not in allowed:continue
            safe={'paper_id':item['paper_id'],'file_version':item['file_version'],'pages':[p for p in item.get('pages',[]) if isinstance(p,int) and 1<=p<=300],'tool':call.get('tool')}
            if safe not in actual:actual.append(safe)
    db.execute('UPDATE material_manifests SET actual_json=? WHERE run_id=?',(json.dumps(actual),run_id))
    return actual
