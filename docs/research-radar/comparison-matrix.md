# Enoch Research Radar Comparison Matrix

Runtime context: see [current-runtime-snapshot.md](../current-runtime-snapshot.md) for the current GB10/control-plane topology referenced by this radar.


| Project/paper | Category | Key idea | What Enoch can borrow | What Enoch should avoid | Difficulty | Research value | Paper potential | Source |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SWE-agent | Coding-agent research harness | Agent-Computer Interface; minimal hackable config; SWE-bench focus | Adopt narrow ACI and benchmark-first discipline | Avoid overfitting to SWE-bench only | Medium | High | High | https://github.com/swe-agent/swe-agent |
| OpenHands | Generalist software-agent platform | Event stream, sandbox, browser, multi-agent, eval suite | Borrow event-stream/replay concepts and benchmark menu | Avoid copying platform breadth/UI sprawl | High | Medium | Medium | https://arxiv.org/pdf/2407.16741 |
| SWE-smith | SWE agent data/benchmark generation | Turn repos into SWE gyms; trajectory datasets | Treat Enoch traces as training/eval assets | Avoid massive training ambitions on local hardware | Medium | High | High | https://github.com/SWE-bench/swe-smith |
| LangSmith | Agent observability/evals | Trajectory tracing, online evals, cost/tool monitoring | Borrow trace UX/eval-loop concepts | Avoid lock-in to LangChain-specific assumptions | Medium | Medium | Medium | https://www.langchain.com/langsmith/observability |
| Arize Phoenix / OpenInference | OTel-native LLM observability | Tracing, datasets, experiments, replay, OpenTelemetry | Map Enoch traces to portable span schema | Avoid storing secrets/raw prompts without redaction | Medium | High | High | https://github.com/Arize-ai/phoenix |
| LangMem | LangGraph memory primitives | Hot-path and background memory management | Borrow namespace/store patterns if Enoch stays LangGraph-ish | Avoid framework-coupled memory before benchmark | Medium | Medium | Medium | https://github.com/langchain-ai/langmem |
| ByteRover | Agent-native file memory | Hierarchical Markdown context tree with provenance/lifecycle | Borrow repo-local inspectable memory and progressive retrieval | Paper is new; validate claims before adopting wholesale | Low-Med | High | High | https://arxiv.org/html/2604.01599v1 |
| Zep / Graphiti | Temporal graph memory | Bitemporal knowledge graph; hybrid BM25/vector/graph search | Borrow temporal validity for changing facts and stale evidence | Avoid high LLM ingestion cost unless temporal queries need it | Medium-High | Medium | Medium | https://arxiv.org/pdf/2501.13956 |
| AdaEDL / SVIP | Entropy-adaptive speculation | Training-free entropy-based dynamic draft stopping | Instrument entropy/acceptance first; cheap local benchmark | Avoid assuming entropy equals alignment in all settings | Medium | High | High | https://arxiv.org/html/2410.18351v1 |
| SpecDec++ / BanditSpec / AdaSpec | Adaptive speculation controllers | Prediction heads, bandits, SLO-aware per-request lengths | Borrow controller/eval framing for GB10 inference experiments | Avoid production complexity before offline evidence | High | High | High | https://arxiv.org/pdf/2405.19715 |
| SAM / SuffixDecoding | Retrieval/suffix speculation | Exploit repeated agentic outputs and suffix trees | Measure Enoch output repetition; prototype cache off-path | Avoid open-ended chat claims; target repetitive workflows | Medium | Very High | Very High | https://suffix-decoding.github.io/ |
