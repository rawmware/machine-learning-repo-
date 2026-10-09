# Workflow Foundry

Workflow Foundry is a small, local-first Python toolkit for retrieving relevant project code and documentation, assembling cited context, and asking an existing Ollama model for structured workflow assistance. It is designed to be useful and inspectable—not a benchmark claim or an autonomous coding agent.

## Requirements and quick start

- Python 3.10+; standard library only.
- An Ollama server listening on loopback for `run` and model details. Workflow Foundry never downloads models. Its default is `qwen3:4b-instruct-2507-q4_K_M`; select another model explicitly with `--model`.

From the repository directory in PowerShell:

```powershell
python -m workflow_foundry --root . doctor
python -m workflow_foundry --root . index
python -m workflow_foundry --root . search "context pack"
python -m workflow_foundry --root . context "index exclusions" --budget 5000
python -m workflow_foundry --root . run review "Review the indexing safety choices"
python -m unittest discover -s tests -v
```

`--root`, `--model`, and `--timeout` are global options and must appear before the subcommand. The index and SQLite state are stored under `<root>/.foundry`; use `--root` explicitly to select a project. `run` checks Ollama `/api/show` for an actual quantization level before inference; model names alone are not considered proof of quantization. It does not automatically choose a larger model or fall back to a cloud service.

Useful commands: `doctor`, `index`, `search`, `context`, `run` (`analyze`, `review`, `plan`, `extract`), `stats`, `benchmark` (offline retrieval fixture only), and `mcp` (stdio JSON-RPC server). Run `python -m workflow_foundry --help` or `... run --help` for options. MCP configuration example: `examples/mcp.json`.

## Safety, privacy, and limits

The indexer scans only a caller-selected root, skips common generated/build/dependency directories, secret-like filenames and symlinks, enforces file and chunk limits, and stores text chunks and content hashes in a local SQLite database. Query input is treated as literal terms, not FTS syntax. Hits are checked against the current file hash before display; reindex after changes to refresh results. `.foundry` contains indexed source text, inference cache content, and metadata-only run receipts. Keep it private; it is ignored by Git. No task, prompt, evidence, or generated answer is persisted in receipts, but successful cached inference content is persisted locally and can contain sensitive text. Delete `.foundry` to remove the local state.

Context citations identify indexed source paths and line ranges. A model's citations are checked for membership in the supplied evidence, not factual entailment; model responses are always labelled unverified. Results can be incomplete, incorrect, or stale; inspect cited files yourself. No shell commands are executed, no edits are automatically applied, no arbitrary network tools are exposed, and no model-provided instructions are treated as trusted. MCP binds a fixed root/model at launch; it opens no listening port.

This uses existing quantized Ollama weights when their `/api/show` response reports a quantization level. It does **not** quantize weights, train a model, or make a model more capable. `num_ctx`, `num_predict`, timeout and prompt character limits are explicit resource controls; token estimates are estimates, not measured token counts. Ollama usage and timing are reported only when the server supplies them.

## Development

```powershell
python -m unittest discover -s tests -v
```

The package has no third-party runtime or test dependencies. See `AGENT_HANDOFF.md` for implementation notes and measured-vs-expected benefits.