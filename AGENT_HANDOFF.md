# Workflow Foundry implementation handoff

## What is implemented

A Python 3.10+ standard-library runtime package providing a root-confined incremental SQLite/FTS5 index, safe literal-term retrieval, hash-checked citations, character-budgeted context packs, loopback-only Ollama HTTP, schema-checked JSON workflows, successful-result local cache, metadata-only run receipts, offline retrieval fixture, CLI, and MCP stdio JSON-RPC. Tests use `unittest`, a local mock HTTP server, and subprocesses. The package itself has no runtime dependencies. `pyproject.toml` declares setuptools as a packaging/build backend; no installation was performed.

## Expected versus measured benefits

Expected: indexing unchanged files avoids reparsing/rechunking them; source retrieval can reduce the amount of project text sent as context; line/hash citations make source inspection practical; cache hits can avoid repeat inference for identical content/model/settings. These are design expectations, not measured performance claims.

Measured here: no benchmark or test results are recorded in this handoff until the commands below have been run. `benchmark` is intentionally only a deterministic offline fixture reporting corpus/evidence characters, whether a relevant fixture file was retrieved, and environment-dependent fixture elapsed time. It says nothing about model quality or inference speed. Ollama timings/usage are reported only when supplied by Ollama.

## Commands

From repository root (PowerShell):

```powershell
python -m unittest discover -s tests -v
python -m workflow_foundry --root . benchmark
python -m workflow_foundry --root . doctor
python -m workflow_foundry --root . index
python -m workflow_foundry --root . search "citation hashes"
python -m workflow_foundry --root . context "incremental index" --budget 4000
python -m workflow_foundry --root . run review "Review the index safety design"
python -m workflow_foundry --root . stats
```

The workflow run requires a reachable loopback Ollama instance and an already available genuinely quantized model whose `/api/show` details report `quantization_level`. No model is fetched. Run smoke inference only deliberately; it can incur local compute and writes successful response content to `.foundry` cache. Global options (`--root`, `--model`, `--timeout`) must precede the subcommand.

## Security and known boundaries

Indexing skips declared generated/dependency directories, secret-like files, symlinks, files above size limits, binary/NUL, and undecodable content. Paths are resolved under the explicit root. State is confined to `<root>/.foundry`; receipts persist metadata only while cache entries persist generated content. MCP has no listener and fixes root/model at server launch. Ollama is plain HTTP on loopback only; client uses `http.client`, not urllib/proxy handling, and does not follow redirects. Workflow outputs are unverified even when JSON schema-valid; citation membership is not entailment validation. This is not a code executor/editor, trainer, or quantizer.

Potential follow-up work: add stronger stress and fault-injection tests for database corruption, very large directory trees, and unusual Unicode/FTS tokenization; choose a stricter whole-prompt character-budget contract if callers need a cap inclusive of task and JSON framing; add installer/build validation in CI if package distribution becomes a goal.

## References

Design inspiration only, not copied source: [pi-extensions](https://github.com/narumiruna/pi-extensions) for modular context/search/observability ideas and [yfinance-mcp](https://github.com/AgentX-ai/yfinance-mcp) as MCP ecosystem inspiration. Workflow Foundry is implemented independently with only Python standard-library runtime dependencies.
