"""Command-line interface."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
from . import DEFAULT_MODEL,__version__
from .index import index_project,search,context_pack
from .ollama import OllamaClient
from .workflows import run_workflow,stats
from .benchmark import offline_benchmark

def _json(value): print(json.dumps(value,ensure_ascii=False,indent=2))
def parser():
    p=argparse.ArgumentParser(prog="workflow-foundry",description="Local project retrieval and structured Ollama workflows (stdlib only). Global options precede command.")
    p.add_argument("--root",type=Path,default=Path.cwd(),help="Explicit project root; local state is <root>/.foundry (default: current directory)")
    p.add_argument("--model",default=DEFAULT_MODEL,help=f"Ollama model; no automatic model selection (default: {DEFAULT_MODEL})")
    p.add_argument("--timeout",type=float,default=90,help="Ollama request timeout seconds (default 90)")
    p.add_argument("--version",action="version",version=__version__)
    s=p.add_subparsers(dest="command",required=True)
    s.add_parser("doctor",help="check loopback Ollama tags and configured model details")
    ix=s.add_parser("index",help="incrementally index safe project source files");ix.add_argument("--max-file-size",type=int,default=1_000_000);ix.add_argument("--chunk-size",type=int,default=1800);ix.add_argument("--exclude",action="append",default=[],help="glob exclude (repeatable)")
    se=s.add_parser("search",help="search indexed project files");se.add_argument("query");se.add_argument("--limit",type=int,default=10)
    co=s.add_parser("context",help="build bounded evidence context pack");co.add_argument("query");co.add_argument("--budget",type=int,default=6000);co.add_argument("--limit",type=int,default=12)
    ru=s.add_parser("run",help="run analyze/review/plan/extract against retrieved context");ru.add_argument("workflow",choices=["analyze","review","plan","extract"]);ru.add_argument("task");ru.add_argument("--input",default="",help="additional untrusted input (bounded)");ru.add_argument("--budget",type=int,default=6000);ru.add_argument("--max-output",type=int,default=768);ru.add_argument("--num-ctx",type=int,default=8192);ru.add_argument("--no-cache",action="store_true")
    s.add_parser("stats",help="show local index and receipt/cache counters")
    s.add_parser("benchmark",help="offline retrieval fixture (not model quality/speed)")
    s.add_parser("mcp",help="serve MCP JSON-RPC over stdio only")
    return p

def main(argv=None):
    args=parser().parse_args(argv)
    try:
        root=args.root.expanduser().resolve(strict=True)
        if not root.is_dir(): raise ValueError("--root must be an existing directory")
        if args.command=="doctor":
            c=OllamaClient(timeout=args.timeout); tags=c.tags(); out={"reachable":True,"tags":tags,"selected_model":args.model}
            try:
                details=c.show(args.model); out["model_details"]={"quantization_level":details.get("details",{}).get("quantization_level"),"digest":details.get("digest"),"details":details.get("details",{})}
            except Exception as e: out["model_error"]={"error":str(e),"code":getattr(e,"code","error")}
            _json(out);return 0
        if args.command=="index": _json(index_project(root,max_file_size=args.max_file_size,chunk_size=args.chunk_size,excludes=args.exclude));return 0
        if args.command=="search": _json(search(root,args.query,args.limit));return 0
        if args.command=="context": _json(context_pack(search(root,args.query,args.limit),args.budget));return 0
        if args.command=="run":
            result=run_workflow(root,args.workflow,args.task,model=args.model,timeout=args.timeout,budget=args.budget,max_output=args.max_output,num_ctx=args.num_ctx,input_text=args.input,bypass_cache=args.no_cache);_json(result);return 0 if result["status"]=="ok" else 2
        if args.command=="stats": _json(stats(root));return 0
        if args.command=="benchmark": _json(offline_benchmark());return 0
        if args.command=="mcp":
            from .mcp import serve
            serve(root,args.model,args.timeout);return 0
    except Exception as e:
        print(json.dumps({"error":str(e),"type":type(e).__name__},ensure_ascii=False),file=sys.stderr);return 2
    return 1
