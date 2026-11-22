"""Portable client's actual HTTP behavior, with an in-process local fixture."""
import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('firework_client',ROOT/'plugins/agent-skill/firework-paper-ops/scripts/firework.py')
fw=importlib.util.module_from_spec(spec);spec.loader.exec_module(fw)

def test_client_auth_requests_and_redirect_refusal(monkeypatch,tmp_path):
    seen=[]
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path,self.headers.get('Authorization')))
            if self.path.endswith('/redirect'):
                self.send_response(302);self.send_header('Location','https://example.com/steal');self.end_headers();return
            self.send_response(200);self.end_headers();self.wfile.write(b'{"ok":true}')
        def do_POST(self):
            seen.append((self.path,self.headers.get('Idempotency-Key'),json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
            self.send_response(201);self.end_headers();self.wfile.write(b'{"id":1}')
        def log_message(self,*args):pass
    server=HTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    token='fw_fixture_not_a_real_credential_12345';secret=tmp_path/'token';secret.write_text(token);secret.chmod(0o600)
    monkeypatch.setenv('FIREWORK_URL',f'http://127.0.0.1:{server.server_port}');monkeypatch.setenv('FIREWORK_ALLOW_LOCAL_HTTP','1');monkeypatch.setenv('FIREWORK_TOKEN_FILE',str(secret))
    try:
        assert fw.call('GET','/capabilities')=={'ok':True}
        assert fw.call('POST','/papers',{'title':'Example'},'same-key')=={'id':1}
        assert seen[0][1]=='Bearer '+token and seen[1][1]=='same-key'
        with pytest.raises(ValueError):fw.call('GET','/redirect')
        assert len(seen)==3
        secret.chmod(0o644)
        with pytest.raises(ValueError):fw.configuration()
        monkeypatch.setenv('FIREWORK_URL','https://name:secret@example.com')
        with pytest.raises(ValueError):fw.configuration()
    finally:server.shutdown();server.server_close();thread.join()

def test_archive_is_deterministic_and_contains_only_source(tmp_path):
    spec=importlib.util.spec_from_file_location('skill_build',ROOT/'scripts/build_agent_skill.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    a=m.build(tmp_path/'a.zip');b=m.build(tmp_path/'b.zip');assert a.read_bytes()==b.read_bytes()
    import zipfile
    with zipfile.ZipFile(a) as z:assert set(z.namelist())=={'firework-paper-ops/SKILL.md','firework-paper-ops/scripts/firework.py','firework-paper-ops/references/api.md','firework-paper-ops/references/frontier.md'}


def test_client_conflict_codes_are_safe_and_specific(monkeypatch):
    import io
    from urllib.error import HTTPError
    class Opener:
        def __init__(self,raw):self.raw=raw
        def open(self,*args,**kwargs):raise HTTPError('https://example.invalid',409,'conflict',{},io.BytesIO(self.raw))
    monkeypatch.setattr(fw,'configuration',lambda:('https://example.invalid','fw_fixture_secret_not_real_123'))
    for code,expected in [('idempotency_conflict','Do not bypass'),('annotation_conflict','current ETag'),('metadata_conflict','current paper version'),('evidence_conflict','current document')]:
        raw=json.dumps({'code':code,'detail':'fw_secret_must_not_be_echoed'}).encode()
        monkeypatch.setattr(fw.request,'build_opener',lambda *args:Opener(raw))
        with pytest.raises(fw.ClientError) as e:fw.call('GET','/capabilities')
        assert expected in str(e.value) and 'fw_secret' not in str(e.value)


def test_cli_frontier_and_recovery_routes(monkeypatch,tmp_path,capsys):
    seen=[]
    monkeypatch.setattr(fw,'call',lambda method,path,body=None,key=None:seen.append((method,path,body,key)) or {'ok':True})
    for args,path in [(['annotations','--paper','1','--include-deleted'],'/papers/1/annotations?include_deleted=true'),(['note','--paper','1','--annotation','id1'],'/papers/1/annotations/id1'),(['frontier-topics'],'/frontier/topics'),(['frontier-reports','--topic','3'],'/frontier/reports?limit=20&topic_id=3'),(['frontier-report','--report','a'*32],'/frontier/reports/'+'a'*32)]:
        assert fw.main(args)==0;assert seen[-1][0:2]==('GET',path)
    report=tmp_path/'report.json';report.write_text('{"topic_revision":1}')
    md=tmp_path/'review.md';md.write_text('# Local review',encoding='utf-8')
    assert fw.main(['submit-frontier-report','--topic','3','--json-file',str(report),'--markdown-file',str(md),'--request-key','stable-key'])==0
    assert seen[-1]==('POST','/frontier/topics/3/reports',{'topic_revision':1,'markdown':'# Local review'},'stable-key')
