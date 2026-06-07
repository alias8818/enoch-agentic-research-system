# Trace-derived local memory should be Markdown+SQLite first

- **Type:** Candidate Experiment
- **Source/project/paper:** ByteRover, Zep/Graphiti, LangMem, Letta/MemGPT
- **Relevance to Enoch:** Trace-derived local memory should be Markdown+SQLite first
- **What Enoch currently does or likely does:** Enoch already has docs, ledgers, session history, but not research-memory architecture.
- **Proposed change or experiment:** Prototype inspectable repo-local memory with provenance/TTL and benchmark against no-memory.
- **Expected upside:** High: fits Enoch audit/replay ethos.
- **Risk/downside:** Medium: memory poisoning/stale facts if no invalidation.
- **Rough effort:** Medium
- **Paper potential:** High
- **Suggested next action:** Define memory tasks and stale-fact tests before platform choice.
- **Candidate implementation:** Yes
