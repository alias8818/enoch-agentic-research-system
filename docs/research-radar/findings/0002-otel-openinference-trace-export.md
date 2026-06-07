# Portable OTel/OpenInference trace export beats vendor lock-in

- **Type:** Instrumentation Gap
- **Source/project/paper:** Phoenix, LangSmith, Weave, Braintrust observability patterns
- **Relevance to Enoch:** Portable OTel/OpenInference trace export beats vendor lock-in
- **What Enoch currently does or likely does:** Enoch traces are local/redacted but Enoch-specific.
- **Proposed change or experiment:** Add OTel-like export while keeping local ledgers authoritative.
- **Expected upside:** High: enables standard tools and source-linked evaluation.
- **Risk/downside:** Medium: potential loss of Enoch-specific semantics.
- **Rough effort:** Medium
- **Paper potential:** High
- **Suggested next action:** Map one research cycle to span tree.
- **Candidate implementation:** Yes
