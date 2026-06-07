# Temporal graph memory is useful only for facts that change

- **Type:** Architecture Concern
- **Source/project/paper:** Zep/Graphiti temporal KG
- **Relevance to Enoch:** Temporal graph memory is useful only for facts that change
- **What Enoch currently does or likely does:** Many Enoch facts are static docs; some facts change: provider health, issue status, worker state.
- **Proposed change or experiment:** Use simple validity windows first; consider Graphiti only for temporal queries that SQLite cannot answer.
- **Expected upside:** Medium: avoids overengineering.
- **Risk/downside:** Low-medium.
- **Rough effort:** Low
- **Paper potential:** Medium
- **Suggested next action:** List temporal queries and test SQLite validity-window baseline.
- **Candidate implementation:** No
