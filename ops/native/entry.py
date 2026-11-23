"""Container-local loopback HTTP -> dedicated model-only Unix socket."""
import http.client
import http.server
import os
import socket
import subprocess
import threading

class UnixConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        self.sock.connect('/bridge/model.sock')

class Relay(http.server.BaseHTTPRequestHandler):
    protocol_version='HTTP/1.0'
    def log_message(self,*args):pass
    def request(self):
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size<0 or size>16*1024*1024:self.send_error(413);return
            if self.headers.get('Transfer-Encoding'):self.send_error(400);return
            c=UnixConnection('localhost',timeout=900)
            c.request(self.command,self.path,body=self.rfile.read(size),headers={k:v for k,v in self.headers.items() if k.lower() in ('content-type','x-api-key','authorization','anthropic-version','anthropic-beta','accept')})
            r=c.getresponse();self.send_response(r.status)
            for k,v in r.getheaders():
                if k.lower() in ('content-type','content-length'):self.send_header(k,v)
            self.send_header('Connection','close');self.end_headers()
            while block:=r.read1(32768):self.wfile.write(block);self.wfile.flush()
            c.close()
        except (OSError,http.client.HTTPException):self.close_connection=True
    do_POST=request
    do_GET=request

if __name__=='__main__':
    server=http.server.ThreadingHTTPServer(('127.0.0.1',8999),Relay)
    server.daemon_threads=True
    threading.Thread(target=server.serve_forever,daemon=True).start()
    argv=['/usr/local/bin/claude','--bare','--strict-mcp-config','--mcp-config','{"mcpServers":{}}','--no-chrome','--permission-mode','default','--append-system-prompt','Linked paper snapshots are read-only under /papers; /papers/manifest.json lists their identities. Save generated artifacts only in /workspace. Do not claim to have read a file without opening it.','--model',os.environ['ANTHROPIC_MODEL']]
    argv+=['--resume' if os.environ.get('FIREWORK_RESUME')=='1' else '--session-id',os.environ['FIREWORK_SESSION_ID']]
    child=subprocess.Popen(argv)
    raise SystemExit(child.wait())
