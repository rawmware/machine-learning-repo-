"""Deterministic offline fixture: retrieval coverage and character reduction, not model quality/speed."""
from __future__ import annotations
import tempfile,time
from pathlib import Path
from .index import index_project,search,context_pack

def offline_benchmark():
    corpus={"src/indexing.py":"def index_project(root):\n    # skip credentials and hash source safely\n    return sha256(root)\n","docs/guide.md":"# Local retrieval\nSearch returns cited source lines and stale hashes are checked.\n","docs/other.md":"A sample unrelated note about gardening, soil, and watering plants.\n"}
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        for name,text in corpus.items(): p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding="utf-8")
        t=time.perf_counter(); index_project(root); hits=search(root,"credentials hash source",limit=8); pack=context_pack(hits,2000); elapsed=time.perf_counter()-t
        relevant=any(h["path"]=="src/indexing.py" for h in hits)
        full=sum(len(x) for x in corpus.values())
        return {"kind":"offline retrieval fixture only; not model quality or inference speed","fixture_files":len(corpus),"relevant_hit":relevant,"hits":len(hits),"full_corpus_characters":full,"selected_evidence_characters":pack["selected_characters"],"fixture_retrieval_elapsed_seconds":round(elapsed,6),"latency_is_environment_dependent":True}
