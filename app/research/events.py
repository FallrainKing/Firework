"""Append-only structured run events; no credentials or raw tool arguments."""
import json
from ..core.errors import ServiceError

def append(db,run_id,kind,payload):
    db.execute('INSERT INTO run_events(run_id,kind,payload_json) VALUES (?,?,?)',(run_id,kind,json.dumps(payload,ensure_ascii=False)))

def listing(db,run_id,after=0,limit=100):
    if not db.execute('SELECT 1 FROM agent_runs WHERE id=?',(run_id,)).fetchone():raise ServiceError(404,'任务不存在')
    rows=db.execute('SELECT * FROM run_events WHERE run_id=? AND id>? ORDER BY id LIMIT ?',(run_id,after,limit+1)).fetchall()
    items=[{'seq':r['id'],'kind':r['kind'],'payload':json.loads(r['payload_json']),'created_at':r['created_at']} for r in rows[:limit]]
    return {'events':items,'has_more':len(rows)>limit,'next_after':items[-1]['seq'] if items else after,'legacy':not bool(rows) and not db.execute('SELECT 1 FROM run_events WHERE run_id=?',(run_id,)).fetchone()}
