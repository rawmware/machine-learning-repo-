import json, os, socket, subprocess, sys, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workflow_foundry.index import index_project, search, context_pack, database
from workflow_foundry.ollama import OllamaClient, OllamaError
from workflow_foundry.workflows import run_workflow, stats
from workflow_foundry.mcp import dispatch

class IndexTests(unittest.TestCase):
    def setUp(self): self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def put(self,name,text):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf8');return p
    def test_incremental_delete_and_fts_query_escape(self):
        self.put('src/a.py','def greeting():\n    return "hello world"\n')
        first=index_project(self.root); second=index_project(self.root)
        self.assertEqual(first['indexed'],1);self.assertEqual(second['unchanged'],1)
        self.assertEqual(search(self.root,'hello " OR *')[0]['start_line'],1)
        (self.root/'src/a.py').unlink();self.assertEqual(index_project(self.root)['removed'],1)
        self.assertEqual(search(self.root,'hello'),[])
    def test_secrets_binary_and_symlink_excluded(self):
        self.put('.env','SECRET=abc');self.put('.env.prod','secret');self.put('config/app-local.toml','secret');self.put('id_rsa','key');self.put('ok.py','safe');self.put('bin.py','x\0y')
        outside=Path(self.tmp.name).parent/'outside_workflow_foundry.py';outside.write_text('outside secret')
        try:
            try:(self.root/'escape.py').symlink_to(outside)
            except (OSError,NotImplementedError):pass
            index_project(self.root);db=database(self.root)
            names={r[0] for r in db.execute('select path from files')};db.close()
            self.assertEqual(names,{'ok.py'})
        finally: outside.unlink(missing_ok=True)
    def test_stale_hash_suppressed_and_context_budget(self):
        p=self.put('a.md','keyword material\nsecond line');index_project(self.root)
        hits=search(self.root,'keyword');self.assertEqual(hits[0]['start_line'],1)
        p.write_text('changed content',encoding='utf8');self.assertEqual(search(self.root,'keyword'),[])
        pack=context_pack(hits,128);self.assertLessEqual(pack['selected_characters'],128);self.assertIn('sha256:',pack['text'])

class FakeHandler(BaseHTTPRequestHandler):
    routes={}; calls=[]
    def do_GET(self): self.respond()
    def do_POST(self):
        body=self.rfile.read(int(self.headers.get('Content-Length','0')));self.__class__.calls.append((self.path,json.loads(body) if body else {}));self.respond()
    def respond(self):
        status,body=self.routes.get(self.path,(200,{}));raw=json.dumps(body).encode();self.send_response(status);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def log_message(self,*a): pass
class ServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=HTTPServer(('127.0.0.1',0),FakeHandler);cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start();cls.url=f'http://127.0.0.1:{cls.server.server_port}'
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close()
    def test_transport_and_restrictions(self):
        FakeHandler.routes['/bad']=(500,{'error':'oops'});c=OllamaClient(self.url)
        with self.assertRaises(OllamaError):c._request('/bad')
        with self.assertRaises(ValueError):OllamaClient('http://example.com')
        with self.assertRaises(ValueError):OllamaClient('http://127.0.0.1:8@127.0.0.1')
    def test_run_cache_digest_and_invalid_citation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'demo.md').write_text('The widgets are blue.','utf8');index_project(root)
            quant={'details':{'quantization_level':'Q4_K_M'},'digest':'digest-a'}
            FakeHandler.routes['/api/show']=(200,quant)
            FakeHandler.routes['/api/chat']=(200,{'message':{'content':json.dumps({'answer':'It is blue.','evidence':['bogus'],'caveats':[]})},'eval_count':12})
            # replace endpoint with test server, retaining loopback-only constraint
            import workflow_foundry.workflows as wf
            from unittest.mock import patch
            with patch.object(wf,'OllamaClient',lambda timeout:OllamaClient(self.url)):
                a=run_workflow(root,'analyze','widgets blue',model='small');self.assertEqual(a['status'],'ok');self.assertEqual(a['evidence'],[]);self.assertFalse(a['verified'])
                b=run_workflow(root,'analyze','widgets blue',model='small');self.assertTrue(b['cache_hit'])
                FakeHandler.routes['/api/show']=(200,{'details':{'quantization_level':'Q5_K_M'},'digest':'digest-b'})
                d=run_workflow(root,'analyze','widgets blue',model='small');self.assertFalse(d['cache_hit'])
                FakeHandler.routes['/api/chat']=(200,{'message':{'content':'{}'}})
                e=run_workflow(root,'review','widgets blue',model='small');self.assertEqual(e['status'],'error')
            self.assertEqual(stats(root)['receipts']['total'],4)
            db=database(root);row=db.execute('select * from receipts').fetchone();db.close();self.assertNotIn('widgets',str(dict(row)))

class MCPPipelineTests(unittest.TestCase):
    def test_protocol_tools_call_errors(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'x.py').write_text('answer=42','utf8')
            out=dispatch({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26'}},root,'m',1)
            self.assertEqual(out['result']['protocolVersion'],'2025-03-26')
            self.assertEqual(len(dispatch({'jsonrpc':'2.0','id':2,'method':'tools/list'},root,'m',1)['result']['tools']),6)
            call=dispatch({'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'foundry_index','arguments':{}}},root,'m',1)
            self.assertFalse(call['result']['isError'])
            bad=dispatch({'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'foundry_search','arguments':{'query':'x','root':'/tmp'}}},root,'m',1)
            self.assertTrue(bad['result']['isError'])
            err=dispatch({'jsonrpc':'2.0','id':5,'method':'nonsense'},root,'m',1);self.assertEqual(err['error']['code'],-32601)
    def test_cli_smoke_and_mcp_subprocess_handshake(self):
        repo=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'hello.md').write_text('workflow evidence','utf8')
            p=subprocess.run([sys.executable,'-m','workflow_foundry','--root',str(root),'index'],cwd=repo,capture_output=True,text=True,timeout=10);self.assertEqual(p.returncode,0,p.stderr)
            p=subprocess.run([sys.executable,'-m','workflow_foundry','--root',str(root),'mcp'],cwd=repo,input='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05"}}\n{"jsonrpc":"2.0","method":"notifications/initialized"}\n{"jsonrpc":"2.0","id":2,"method":"ping"}\n',capture_output=True,text=True,timeout=10)
            lines=p.stdout.splitlines();self.assertEqual(len(lines),2);self.assertEqual(json.loads(lines[1])['id'],2)

if __name__=='__main__':unittest.main()
