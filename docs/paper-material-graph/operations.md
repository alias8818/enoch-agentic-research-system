# Paper Material Graph Operations

Runtime context: see [current-runtime-snapshot.md](../current-runtime-snapshot.md) for the live topology and host-layout assumptions referenced below.


The paper material graph is a read-only export that turns Enoch's public paper corpus and promising-signal backlog into an inspectable graph for paper synthesis and negative-result mining.

## Live host layout

On the control-plane host:

- Script: `/opt/enoch-control-plane/scripts/build_paper_material_graph.py`
- Wrapper: `/opt/enoch-control-plane/deploy/enoch_paper_material_graph.sh`
- Service: `enoch-paper-material-graph.service`
- Timer: `enoch-paper-material-graph.timer`
- JSON graph: `/opt/enoch-control-plane/docs/paper-material-graph/paper-material-graph.json`
- Markdown summary: `/opt/enoch-control-plane/docs/paper-material-graph/README.md`

## What it reads

- Public corpus checkout: `/opt/enoch-release/enoch-ai-research-corpus`
- Promising signals checkout: `/opt/enoch-release/enoch-promising-signals`

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
p = pathlib.Path('/opt/enoch-control-plane/docs/paper-material-graph/paper-material-graph.json')
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
# The graph export should not change these flags or dispatch counts.
curl -sS -H "Authorization: Bearer $ENOCH_CONTROL_TOKEN" \
  http://127.0.0.1:8787/control/api/v1/overview \
  | jq '{flags, counts, top_actions: .top_actions[:2]}'
```

## Reading the outputs

- **Top synthesis candidates**: positive/useful signals with nearby public paper material. These are candidates for stronger follow-up papers.
- **Negative / blocked result candidates**: scale-blocked or failed-ish signals that should not be discarded. These are candidates for negative-result reports, bounded re-runs, or paper sections explaining what did not work.
- **Graph JSON**: full machine-readable node/edge export for later clustering, visualization, or graph database import.

## Known current behavior

The public corpus is thematically dense, so connected components are not yet the best operator surface. The useful surfaces today are ranked synthesis candidates and ranked negative/blocked candidates. Future work should add richer communities using embeddings or source-lineage features instead of only lexical overlap.
