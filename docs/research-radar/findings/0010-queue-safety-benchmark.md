# Queue/worker safety deserves its own benchmark

- **Type:** Benchmark Gap
- **Source/project/paper:** Enoch incidents + state model + queue alert logic
- **Relevance to Enoch:** Queue/worker safety deserves its own benchmark
- **What Enoch currently does or likely does:** Recent operations surfaced pause/resume, settling, stale active-lane, and alert dedupe patterns.
- **Proposed change or experiment:** Create Queue SafetyBench with seeded states and expected alerts/actions.
- **Expected upside:** High: unique systems reliability angle.
- **Risk/downside:** Low.
- **Rough effort:** Medium
- **Paper potential:** High
- **Suggested next action:** Build fixtures from recent ALI incidents and assert false-positive/missed-alert rates.
- **Candidate implementation:** Yes
