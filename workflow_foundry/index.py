"""Safe incremental SQLite/FTS5 project index."""
from __future__ import annotations
import fnmatch, hashlib, os, re, sqlite3
from pathlib import Path
from typing import Iterable

EXTENSIONS = {".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".go", ".rs", ".c", ".h", ".cpp", ".hpp", ".cs", ".php", ".rb", ".swift", ".scala", ".sh", ".ps1", ".sql", ".html", ".css", ".scss", ".json", ".toml", ".yaml", ".yml", ".xml", ".md", ".rst", ".txt", ".ini", ".cfg", ".dockerfile", ".makefile"}
SKIP_DIRS = {".git", ".foundry", ".venv", "venv", "env", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "build", "dist", "target", "coverage", ".tox"}
SECRET_NAMES = {".env", "id_rsa", "id_ed25519", "credentials", "secrets", "secrets.json", "private.key"}
DEFAULT_MAX_FILE = 1_000_000
DEFAULT_CHUNK = 1800

def sha256(data: bytes) -> str: return hashlib.sha256(data).hexdigest()

def state_dir(root: Path) -> Path:
    root = root.resolve()
    d = (root / ".foundry").resolve()
    if not d.is_relative_to(root): raise ValueError("state directory must be inside root")
    d.mkdir(parents=True, exist_ok=True)
    return d

def database(root: Path) -> sqlite3.Connection:
    db = sqlite3.connect(state_dir(root) / "foundry.sqlite3")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, hash TEXT NOT NULL, size INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, path TEXT NOT NULL REFERENCES files(path) ON DELETE CASCADE, start_line INTEGER NOT NULL, end_line INTEGER NOT NULL, hash TEXT NOT NULL, text TEXT NOT NULL);
      CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, content='chunks', content_rowid='id', tokenize='unicode61');
      CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN INSERT INTO chunks_fts(rowid,text) VALUES(new.id,new.text); END;
      CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN INSERT INTO chunks_fts(chunks_fts,rowid,text) VALUES('delete',old.id,old.text); END;
      CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN INSERT INTO chunks_fts(chunks_fts,rowid,text) VALUES('delete',old.id,old.text); INSERT INTO chunks_fts(rowid,text) VALUES(new.id,new.text); END;
      CREATE TABLE IF NOT EXISTS cache(cache_key TEXT PRIMARY KEY, response TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
      CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY, status TEXT NOT NULL, model TEXT NOT NULL, workflow TEXT NOT NULL, cache_hit INTEGER NOT NULL, wall_seconds REAL NOT NULL, usage_json TEXT, error_code TEXT, verified INTEGER NOT NULL DEFAULT 0, schema_valid INTEGER);
      """)
    return db

def _secret(rel: str) -> bool:
    parts = rel.replace("\\", "/").split("/")
    name = parts[-1].lower()
    return name in SECRET_NAMES or name.startswith(".env.") or name.endswith((".pem", ".key", ".p12", ".pfx")) or ("config" in [p.lower() for p in parts[:-1]] and "local" in name)

def _walk(root: Path, excludes: Iterable[str]):
    for base, dirs, files in os.walk(root, topdown=True, followlinks=False):
        bp = Path(base)
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not (bp / d).is_symlink())
        for name in sorted(files):
            p = bp / name
            try:
                if p.is_symlink(): continue
                resolved = p.resolve(strict=True)
                if not resolved.is_relative_to(root): continue
                rel = p.relative_to(root).as_posix()
            except (OSError, ValueError): continue
            if _secret(rel) or Path(name).suffix.lower() not in EXTENSIONS: continue
            if any(fnmatch.fnmatch(rel, pat) for pat in excludes): continue
            yield p, rel

def _chunks(text: str, limit: int):
    lines = text.splitlines()
    if not lines: return
    start, buf, used = 1, [], 0
    for n, line in enumerate(lines, 1):
        # Split very long lines while maintaining source line provenance.
        pieces = [line[i:i+limit] for i in range(0, len(line), limit)] or [""]
        for piece in pieces:
            if buf and used + len(piece) + 1 > limit:
                yield start, n, "\n".join(buf)
                buf, used, start = [], 0, n
            buf.append(piece); used += len(piece) + 1
    if buf: yield start, len(lines), "\n".join(buf)

def index_project(root: Path, *, max_file_size=DEFAULT_MAX_FILE, chunk_size=DEFAULT_CHUNK, excludes=()):
    root = root.resolve(strict=True)
    if not root.is_dir(): raise ValueError("root must be a directory")
    if not 1 <= max_file_size <= 20_000_000 or not 128 <= chunk_size <= 100_000: raise ValueError("invalid size limit")
    db = database(root); seen = set(); counts = {"scanned":0,"indexed":0,"unchanged":0,"skipped":0,"removed":0}
    try:
        db.execute("BEGIN IMMEDIATE")
        for path, rel in _walk(root, excludes):
            counts["scanned"] += 1
            try:
                size = path.stat().st_size
                if size > max_file_size: counts["skipped"] += 1; continue
                raw = path.read_bytes()
                if b"\0" in raw: counts["skipped"] += 1; continue
                text = raw.decode("utf-8")
            except (OSError, UnicodeError): counts["skipped"] += 1; continue
            digest = sha256(raw); seen.add(rel)
            old = db.execute("SELECT hash FROM files WHERE path=?", (rel,)).fetchone()
            if old and old["hash"] == digest: counts["unchanged"] += 1; continue
            db.execute("DELETE FROM files WHERE path=?", (rel,))
            db.execute("INSERT INTO files(path,hash,size) VALUES(?,?,?)", (rel,digest,len(raw)))
            for first,last,chunk in _chunks(text, chunk_size):
                db.execute("INSERT INTO chunks(path,start_line,end_line,hash,text) VALUES(?,?,?,?,?)", (rel,first,last,sha256(chunk.encode()),chunk))
            counts["indexed"] += 1
        paths = [r[0] for r in db.execute("SELECT path FROM files")]
        stale = [p for p in paths if p not in seen]
        db.executemany("DELETE FROM files WHERE path=?", ((p,) for p in stale)); counts["removed"] = len(stale)
        db.commit()
    except Exception:
        db.rollback(); raise
    finally: db.close()
    return counts

def sanitize_query(query: str) -> str:
    terms = re.findall(r"[\w./-]+", query, flags=re.UNICODE)[:24]
    return " AND ".join('"' + t.replace('"','""') + '"' for t in terms)

def search(root: Path, query: str, limit=10):
    if not 1 <= limit <= 100: raise ValueError("limit must be 1..100")
    q = sanitize_query(query)
    if not q: return []
    root = root.resolve(strict=True); db = database(root)
    try:
        rows = db.execute("SELECT c.id,c.path,c.start_line,c.end_line,c.hash,c.text,bm25(chunks_fts) score,f.hash file_hash FROM chunks_fts JOIN chunks c ON c.id=chunks_fts.rowid JOIN files f ON f.path=c.path WHERE chunks_fts MATCH ? ORDER BY score,c.path,c.start_line LIMIT ?", (q,limit)).fetchall()
    finally: db.close()
    results=[]
    for r in rows:
        p=(root/r["path"])
        try:
            if p.is_symlink() or not p.resolve(strict=True).is_relative_to(root) or sha256(p.read_bytes()) != r["file_hash"]: continue
        except OSError: continue
        results.append({"citation":f"{r['path']}:{r['start_line']}-{r['end_line']}","path":r["path"],"start_line":r["start_line"],"end_line":r["end_line"],"chunk_hash":r["hash"],"file_hash":r["file_hash"],"text":r["text"],"score":r["score"]})
    return results

def context_pack(hits, budget=6000):
    if not 128 <= budget <= 100_000: raise ValueError("budget must be 128..100000 characters")
    blocks=[]; used=0; original=0
    for h in hits:
        label=f"[{h['citation']} sha256:{h['chunk_hash']}]\n"
        body=h["text"]; original += len(label)+len(body)
        remaining=budget-used-len(label)
        if remaining <= 0: continue
        selected=body[:remaining]
        if not selected.strip(): continue
        blocks.append(label+selected); used+=len(label)+len(selected)
    return {"text":"\n\n".join(blocks),"citations":[h["citation"] for h in hits if any((f"[{h['citation']} sha256:{h['chunk_hash']}]\n") in b for b in blocks)],"original_characters":original,"selected_characters":used,"budget_characters":budget,"token_estimate":f"~{(used+3)//4} tokens (rough character estimate; not measured)"}
