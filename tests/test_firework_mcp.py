"""Exercise the actual distributed stdio adapter, not a duplicate protocol mock."""
import importlib.util,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'plugins/agent-skill/firework-paper-ops/scripts'

def adapter():
    sys.path.insert(0,str(ROOT))
    spec=importlib.util.spec_from_file_location('firework_mcp',ROOT/'firework_mcp.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def test_stdio_initialize_discovery_and_resources():
    messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25'}},{'jsonrpc':'2.0','method':'notifications/initialized'},{'jsonrpc':'2.0','id':2,'method':'tools/list'},{'jsonrpc':'2.0','id':3,'method':'resources/list'}]
    r=subprocess.run([sys.executable,str(ROOT/'firework_mcp.py')],input='\n'.join(json.dumps(m) for m in messages)+'\n',text=True,capture_output=True,timeout=5)
    assert r.returncode==0,r.stderr
    rows=[json.loads(line) for line in r.stdout.splitlines()];assert len(rows)==3
    assert rows[0]['result']['protocolVersion']=='2025-11-25'
    names={t['name'] for t in rows[1]['result']['tools']};assert {'firework_submit_research','firework_get_context','firework_upload_file'}<=names
    assert rows[2]['result']['resources'][0]['uri']=='firework://contexts'

def test_tools_call_shared_revision_and_submit_contract(monkeypatch):
    m=adapter();seen=[]
    def call(*args):seen.append(args);return {'accepted':True}
    monkeypatch.setattr(m,'call',call)
    m.invoke('firework_read_current_resource',{'context_id':'a'*32,'expected_revision':3})
    assert seen[-1][1].endswith('/resource?expected_revision=3')
    body={'client_job_id':'job','artifact':{'title':'Local result'}}
    m.invoke('firework_submit_research',{'body':body,'request_key':'stable'})
    assert seen[-1]==('POST','/research-submissions',body,'stable')
    r=m.handle({'id':1,'method':'tools/call','params':{'name':'firework_get_paper','arguments':{'paper_id':True}}})
    assert r['result']['isError']
    r=m.handle({'id':2,'method':'resources/read','params':{'uri':'https://evil.invalid'}})
    assert 'error' in r

def test_file_scope_blocks_credentials_and_paths(tmp_path,monkeypatch):
    m=adapter();root=tmp_path/'research';root.mkdir();secret=root/'token.md';secret.write_text('fw_'+'x'*30);secret.chmod(0o600)
    monkeypatch.setenv('FIREWORK_UPLOAD_ROOT',str(root));monkeypatch.setenv('FIREWORK_TOKEN_FILE',str(secret));monkeypatch.setenv('FIREWORK_URL','https://example.org')
    result=m.handle({'id':1,'method':'tools/call','params':{'name':'firework_upload_file','arguments':{'paper_id':1,'file_path':str(secret)}}})
    assert result['result']['isError'] and 'fw_' not in json.dumps(result)
    outside=tmp_path/'outside.md';outside.write_text('private');(root/'link.md').symlink_to(outside)
    for path in [outside,root/'link.md']:
        result=m.handle({'id':2,'method':'tools/call','params':{'name':'firework_upload_file','arguments':{'paper_id':1,'file_path':str(path)}}})
        assert result['result']['isError']
