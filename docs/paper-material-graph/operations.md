# Paper Material Graph Operations

Runtime context: see [current-runtime-snapshot.md](../current-runtime-snapshot.md) for the public role-level runtime snapshot referenced below.


The paper material graph is a read-only export that turns Enoch's public paper corpus and promising-signal backlog into an inspectable graph for paper synthesis and negative-result mining.

## Runtime role layout

On the control-plane runtime role:

- Script: `scripts/build_paper_material_graph.py`
- Wrapper: `deploy/enoch_paper_material_graph.sh`
- Service: `enoch-paper-material-graph.service`
- Timer: `enoch-paper-material-graph.timer`
- JSON graph: `docs/paper-material-graph/paper-material-graph.json`
- Markdown summary: `docs/paper-material-graph/README.md`
- Candidate packets: `docs/paper-material-graph/candidates/{synthesis,negative}/*.md`

## What it reads

- Public corpus checkout: `enoch-ai-research-corpus`
- Promising signals checkout: `enoch-promising-signals`

The export does not dispatch research jobs, resume queues, mutate control-plane state, or write to the public corpus. It only reads the two checkouts and writes graph artifacts under the control-plane docs directory.

## Runtime controls

The service is disabled-by-default in the checked-in unit and enabled intentionally on the live host with a systemd drop-in:

```ini
[Service]
Environment=ENOCH_ENABLE_PAPER_MATERIAL_GRAPH=1
```

Tuning knobs:

- `ENOCH_PAPER_MATERIAL_GRAPH_MIN_SHARED_TERMS` — default `2`
- `ENOCH_PAPER_MATERIAL_GRAPH_MAX_SIMILAR_PER_NODE` — default `8`
- `ENOCH_PAPER_MATERIAL_GRAPH_DIR` — output directory override
- `ENOCH_CORPUS_REPO` — corpus input override
- `ENOCH_PROMISING_REPO` — promising-signals input override

## Operator checks

```bash
systemctl status enoch-paper-material-graph.timer enoch-paper-material-graph.service --no-pager
systemctl list-timers enoch-paper-material-graph.timer --no-pager
journalctl -u enoch-paper-material-graph.service -n 80 --no-pager
```

Quick artifact check:

```bash
python3 - <<'PY'
import json, pathlib
p = pathlib.Path('docs/paper-material-graph/paper-material-graph.json')
g = json.loads(p.read_text())
s = g['summary']
print({
    'papers': s['paper_count'],
    'signals': s['signal_count'],
    'sources': s['source_count'],
    'edges': s['edge_count'],
    'synthesis_candidates': len(s['synthesis_candidates']),
    'negative_result_candidates': len(s['negative_result_candidates']),
})
PY
```

Queue safety check after running the graph export:

```bash
# The graph export should not change operator flags or dispatch counts.
# Query the control-plane overview endpoint through the deployment's configured
# authenticated API route, then inspect flags/counts/top actions.
```

## Reading the outputs

- **Top synthesis candidates**: positive/useful signals with nearby public paper material. These are candidates for stronger follow-up papers.
- **Negative / blocked result candidates**: scale-blocked or failed-ish signals that should not be discarded. These are candidates for negative-result reports, bounded re-runs, or paper sections explaining what did not work.
- **Candidate packets**: one Markdown packet per ranked candidate with signal id, score/status, next action, related papers, source lineage, and scope/limit notes. Packet paths are also surfaced in the dashboard panel so an operator can jump from counts to concrete paper material.
- **Graph JSON**: full machine-readable node/edge export for later clustering, visualization, or graph database import.

## Known current behavior

The public corpus is thematically dense, so connected components are not yet the best operator surface. The useful surfaces today are ranked synthesis candidates and ranked negative/blocked candidates. Future work should add richer communities using embeddings or source-lineage features instead of only lexical overlap.
