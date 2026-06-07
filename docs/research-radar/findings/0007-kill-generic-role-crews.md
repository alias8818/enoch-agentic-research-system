# Do not add generic CrewAI/MetaGPT role crews without eval proof

- **Type:** Removal/Simplification Candidate
- **Source/project/paper:** CrewAI/MetaGPT/AutoGen comparisons
- **Relevance to Enoch:** Do not add generic CrewAI/MetaGPT role crews without eval proof
- **What Enoch currently does or likely does:** Enoch’s workflow is already bounded and stateful; role crews risk vague delegation.
- **Proposed change or experiment:** Defer role-based multi-agent orchestration unless it beats baseline on a named benchmark.
- **Expected upside:** High: preserves focus.
- **Risk/downside:** Low.
- **Rough effort:** Low
- **Paper potential:** Low
- **Suggested next action:** Mark role-crew work as kill/defer until eval exists.
- **Candidate implementation:** No
