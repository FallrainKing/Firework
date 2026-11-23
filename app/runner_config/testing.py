import asyncio,json,uuid
from pydantic import BaseModel,Field
from ..agent import runner_client
from ..core.errors import ServiceError
from . import connections

class TestRequest(BaseModel):
    expected_revision:int=Field(ge=1)
    kind:str=Field(pattern='^(network|model)$')
    confirmed:bool=False

async def start(state,ident,body):
    if body.kind=='model' and not body.confirmed:raise ServiceError(422,'请确认发送固定测试消息，可能产生少量模型费用')
    from .connection_schemas import ConnectionRef
    snap=connections.snapshot(state.db,state.settings,ConnectionRef(id=ident,revision=body.expected_revision))
    secret=connections.materialize(state.db,state.settings,snap);tid=uuid.uuid4().hex
    state.db.execute("INSERT INTO connection_tests(id,connection_id,connection_revision,kind) VALUES (?,?,?,?)",(tid,ident,body.expected_revision,body.kind));state.db.commit()
    async def execute():
        result={'status':'failed','reason':'runner_unavailable','model_called':False}
        try:
            current=state.db.execute('SELECT status FROM connection_tests WHERE id=?',(tid,)).fetchone()
            if not current or current[0]!='running':return
            async with runner_client.client() as client:
                r=await client.post('/connection-tests',json={'id':tid,'kind':body.kind,'connection_snapshot':{k:v for k,v in snap.items() if k!='mode'},'connection_secret':secret},timeout=35)
                if r.status_code==200:result=r.json()
        except Exception:pass
        # A later cancellation must not be overwritten by a delayed response.
        state.db.execute("UPDATE connection_tests SET status=?,result_json=?,finished_at=CURRENT_TIMESTAMP WHERE id=? AND status='running'",(result['status'],json.dumps(result),tid));state.db.commit()
    task=asyncio.create_task(execute())
    # Retain task references until done; no credentials in persisted data.
    tasks=getattr(state,'connection_test_tasks',None)
    if tasks is None:state.connection_test_tasks=set();tasks=state.connection_test_tasks
    tasks.add(task);task.add_done_callback(tasks.discard)
    return view(state,tid)

def view(state,tid):
    row=state.db.execute('SELECT t.*,c.revision AS current_revision FROM connection_tests t JOIN runner_connections c ON c.id=t.connection_id WHERE t.id=?',(tid,)).fetchone()
    if not row:raise ServiceError(404,'测试不存在')
    return {k:row[k] for k in ('id','connection_id','connection_revision','kind','status','created_at','finished_at')}|{'result':json.loads(row['result_json']),'stale':row['current_revision']!=row['connection_revision']}

async def cancel(state,tid):
    item=view(state,tid)
    if item['status']!='running':return item
    state.db.execute("UPDATE connection_tests SET status='cancelled',finished_at=CURRENT_TIMESTAMP WHERE id=?",(tid,));state.db.commit()
    try:
        async with runner_client.client() as client:await client.post(f'/connection-tests/{tid}/cancel',timeout=5)
    except Exception:
        # Persist cancellation even when the runner is unreachable; its probe has a hard deadline.
        pass
    return view(state,tid)
