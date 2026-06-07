# Measure agentic workload repetition before speculative decoding

- **Type:** Candidate Experiment
- **Source/project/paper:** SuffixDecoding, SAM Decoding, AdaEDL, AdaSpec, SpecDec++
- **Relevance to Enoch:** Measure agentic workload repetition before speculative decoding
- **What Enoch currently does or likely does:** Enoch produces repeated agent prompts, logs, callbacks, and paper templates but has not quantified token reuse.
- **Proposed change or experiment:** Add offline repetition/entropy profiler over recent worker outputs.
- **Expected upside:** High if repetition exists; could become inference paper.
- **Risk/downside:** Low if profiler only reads artifacts; high only if moving to inference implementation.
- **Rough effort:** Low
- **Paper potential:** High
- **Suggested next action:** Compute suffix entropy and prompt-lookup hit rate on 100 outputs.
- **Candidate implementation:** Yes
