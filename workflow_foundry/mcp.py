"""MCP-compatible line-delimited JSON-RPC stdio server."""
from __future__ import annotations
import json,sys
from pathlib import Path
from .index import index_project,search,context_pack
from .ollama import OllamaClient
from .workflows import run_workflow,stats
MAX_LINE=100_000
PROTOCOLS={"2024-11-05","2025-03-26","2025-06-18"}
TOOLS=[
 {"name":"foundry_index","description":"Index the fixed project root (writes local .foundry state).","inputSchema":{"type":"object","properties":{"max_file_size":{"type":"integer","minimum":1,"maximum":20000000},"chunk_size":{"type":"integer","minimum":128,"maximum":100000}},"additionalProperties":False},"annotations":{"readOnlyHint":False,"destructiveHint":False,"openWorldHint":False}},
 {"name":"foundry_search","description":"Search indexed local project text; stale hits are suppressed.","inputSchema":{"type":"object","properties":{"query":{"type":"string","maxLength":4000},"limit":{"type":"integer","minimum":1,"maximum":100}},"required":["query"],"additionalProperties":False},"annotations":{"readOnlyHint":True,"openWorldHint":False}},
 {"name":"foundry_context","description":"Build a bounded cited context pack.","inputSchema":{"type":"object","properties":{"query":{"type":"string","maxLength":4000},"budget":{"type":"integer","minimum":128,"maximum":100000}},"required":["query"],"additionalProperties":False},"annotations":{"readOnlyHint":True,"openWorldHint":False}},
 {"name":"foundry_run","description":"Run a structured local Ollama workflow; successful output may be cached locally.","inputSchema":{"type":"object","properties":{"workflow":{"type":"string","enum":["analyze","review","plan","extract"]},"task":{"type":"string","maxLength":8000},"input_text":{"type":"string","maxLength":12000},"budget":{"type":"integer","minimum":128,"maximum":20000}},"required":["workflow","task"],"additionalProperties":False},"annotations":{"readOnlyHint":False,"destructiveHint":False,"openWorldHint":False}},
 {"name":"foundry_stats","description":"Show local index/cache/receipt counters.","inputSchema":{"type":"object","properties":{},"additionalProperties":False},"annotations":{"readOnlyHint":True,"openWorldHint":False}},
 {"name":"foundry_doctor","description":"Check loopback Ollama tags and optionally model quantization.","inputSchema":{"type":"object","properties":{"show_model":{"type":"boolean"}},"additionalProperties":False},"annotations":{"readOnlyHint":True,"openWorldHint":False}}
]

def _text(obj): return json.dumps(obj,ensure_ascii=False,indent=2)
def dispatch(msg,root,model,timeout):
    if not isinstance(msg,dict): return {"jsonrpc":"2.0","id":None,"error":{"code":-32600,"message":"Invalid Request"}}
    method=msg.get("method"); ident=msg.get("id"); hasid="id" in msg
    if msg.get("jsonrpc")!="2.0" or not isinstance(method,str): return {"jsonrpc":"2.0","id":ident,"error":{"code":-32600,"message":"Invalid Request"}}
    if method=="notifications/initialized" or method.startswith("notifications/"): return None
    if method=="initialize":
        p=msg.get("params",{}); proto=p.get("protocolVersion") if isinstance(p,dict) else None
        if proto not in PROTOCOLS: return {"jsonrpc":"2.0","id":ident,"error":{"code":-32602,"message":"Unsupported protocol version"}}
        return {"jsonrpc":"2.0","id":ident,"result":{"protocolVersion":proto,"capabilities":{"tools":{"listChanged":False}},"serverInfo":{"name":"workflow-foundry","version":"0.1.0"}}}
    if method=="ping": return {"jsonrpc":"2.0","id":ident,"result":{}}
    if method=="tools/list": return {"jsonrpc":"2.0","id":ident,"result":{"tools":TOOLS}}
    if method=="tools/call":
        p=msg.get("params")
        if not isinstance(p,dict) or set(p)-{"name","arguments"} or not isinstance(p.get("name"),str): return {"jsonrpc":"2.0","id":ident,"error":{"code":-32602,"message":"Invalid tool call parameters"}}
        args=p.get("arguments",{})
        if not isinstance(args,dict): return {"jsonrpc":"2.0","id":ident,"error":{"code":-32602,"message":"Tool arguments must be an object"}}
        try:
            name=p["name"]
            if name=="foundry_index":
                if set(args)-{"max_file_size","chunk_size"}: raise ValueError("unknown argument")
                result=index_project(root,**args)
            elif name=="foundry_search":
                if set(args)-{"query","limit"} or "query" not in args: raise ValueError("invalid search arguments")
                result=search(root,args["query"],args.get("limit",10))
            elif name=="foundry_context":
                if set(args)-{"query","budget"} or "query" not in args: raise ValueError("invalid context arguments")
                result=context_pack(search(root,args["query"],12),args.get("budget",6000))
            elif name=="foundry_run":
                if set(args)-{"workflow","task","input_text","budget"} or not {"workflow","task"}<=set(args): raise ValueError("invalid run arguments")
                result=run_workflow(root,args["workflow"],args["task"],model=model,timeout=timeout,input_text=args.get("input_text",""),budget=args.get("budget",6000))
            elif name=="foundry_stats":
                if args: raise ValueError("no arguments accepted")
                result=stats(root)
            elif name=="foundry_doctor":
                if set(args)-{"show_model"}: raise ValueError("unknown argument")
                client=OllamaClient(timeout=timeout); result={"tags":client.tags()}
                if args.get("show_model"):
                    data=client.show(model); result["model"]={"name":model,"quantization_level":data.get("details",{}).get("quantization_level"),"digest":data.get("digest")}
            else: raise ValueError("unknown tool")
            return {"jsonrpc":"2.0","id":ident,"result":{"content":[{"type":"text","text":_text(result)}],"isError":False}}
        except Exception as e: return {"jsonrpc":"2.0","id":ident,"result":{"content":[{"type":"text","text":_text({"error":str(e)})}],"isError":True}}
    if not hasid: return None
    return {"jsonrpc":"2.0","id":ident,"error":{"code":-32601,"message":"Method not found"}}

def serve(root:Path,model:str,timeout:float):
    for raw in sys.stdin.buffer:
        if len(raw)>MAX_LINE:
            sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":None,"error":{"code":-32700,"message":"Message too large"}})+"\n");sys.stdout.flush();continue
        try: msg=json.loads(raw)
        except (UnicodeError,json.JSONDecodeError):
            sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":None,"error":{"code":-32700,"message":"Parse error"}})+"\n");sys.stdout.flush();continue
        try: out=dispatch(msg,root,model,timeout)
        except Exception as e: out={"jsonrpc":"2.0","id":msg.get("id") if isinstance(msg,dict) else None,"error":{"code":-32603,"message":str(e)}}
        if out is not None: sys.stdout.write(json.dumps(out,ensure_ascii=False,separators=(",",":"))+"\n");sys.stdout.flush()
