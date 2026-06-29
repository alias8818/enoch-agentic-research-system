# Frontier AI scout — Exa/arXiv candidates for possible Research Facility injection

Date: 2026-06-28
Operator: Hermes
Scope: quick Exa + arXiv/web search for additional Enoch Research Facility candidate ideas adjacent to DSpark/speculative decoding, post-training, and dataset-quality scoring.

## Search evidence

Exa was used for targeted web search on:

- `VIA-SD Verification via Intra-Model Routing for Speculative Decoding project page code`
- `Reasoning Quality Emerges Early Data Curation for Reasoning Models code`
- `CuratorKIT Data Curation and Synthetic Data Generation for LLM Post-Training GitHub`
- `Instruction Data Selection via Answer Divergence code appendix ACL 2026`

arXiv direct API attempts hit 429/timeouts, so arXiv discovery was completed through arXiv result pages and extracted arXiv pages.

## Best injection candidates

### 1. VIA-SD slim-verifier tier for speculative decoding

Sources:

- arXiv: https://arxiv.org/abs/2606.12243v1
- Project page: https://zju-xyc.github.io/VIA-SD-Project-Page/

Claim from source: VIA-SD adds a middle verification tier by routing moderately uncertain draft tokens through a slim submodel derived from the full verifier. Reported effect: rejection-rate reduction of 0.10–0.22, 10–20% speedups over strong speculative-decoding baselines, and 2.5–3x acceleration over non-drafting decoding.

Why it fits Enoch: this is directly adjacent to the DSpark/DeepSpec track but sharper than a generic scheduler test. Enoch could test whether a three-way accept/slim-verify/full-verify policy is practical on GB10/local models.

Candidate experiment: implement a local proxy for slim-verifier routing using layer skipping, early-exit logits, or a smaller model in the same family; compare against binary accept/full-verify speculative decoding on Enoch agentic prompts.

Status recommendation: inject as a child/adjacent Research Facility candidate under ALI-206.

### 2. Learning to Draft throughput-objective controller

Source:

- arXiv: https://arxiv.org/abs/2603.01639v1

Claim from source: Learning to Draft (LTD) uses reinforcement learning to co-adapt draft depth and verification size policies, optimizing accepted length over total draft+verify time. Reported speedups: 2.24x–4.32x, up to 36.4% over Eagle3.

Why it fits Enoch: our current DSpark idea already suspects static schedules are suboptimal. LTD gives a concrete falsifiable controller objective: accepted tokens per draft/verify cycle wall-clock time.

Candidate experiment: build an offline controller from recorded Enoch speculative-decoding traces first, before full RL. Compare heuristic static schedule, hand-tuned dynamic schedule, and learned policy on accepted tokens/sec and scheduler overhead.

Status recommendation: inject if ALI-206 needs a second scheduler-specific subcandidate.

### 3. Reasoning Quality Emerges Early — cheap reasoning-trace curation

Source:

- arXiv: https://arxiv.org/abs/2606.26797v1

Claim from source: difficult/diverse reasoning examples can be identified using only early reasoning-token loss signals. The paper reports selecting examples from the first 100 reasoning tokens at a perturbed checkpoint and claims up to 1.7% improvement while being 91% more token efficient.

Why it fits Enoch: strong bridge between dataset-quality scoring and post-training. Enoch can test a low-cost early-token loss scorer on local reasoning traces before expensive fine-tuning.

Candidate experiment: compute early-token loss curves on a small reasoning dataset with a small Qwen/Llama-family model; compare selected examples against random/diversity-only subsets in a tiny SFT or proxy eval.

Status recommendation: high-priority injection under ALI-208/ALI-207 bridge.

### 4. ADG — Answer Divergence-Guided instruction data selection

Sources:

- arXiv: https://arxiv.org/abs/2604.10448v1
- Code: https://github.com/WisdomShell/ADG

Claim from source: ADG samples multiple high-temperature answers per instruction, embeds the responses, and scores dispersion magnitude plus shape anisotropy. Fine-tuning on 10K ADG-selected examples beat strong selectors across six reasoning/knowledge/coding benchmarks. Code exposes Llama/Qwen scoring, generation, embedding/clustering, train, and eval scripts.

Why it fits Enoch: directly operationalizes the dataset-quality theory with runnable code and an anti-trivial-diversity idea: multi-modal answer geometry beats one-reference quality scoring.

Candidate experiment: run ADG scoring on two small instruction pools, then compare ADG-selected vs random vs simple embedding-diversity selection on a tiny downstream eval.

Status recommendation: strongest immediate injection candidate for ALI-208 because code exists.

### 5. CuratorKIT-style auditable curation pipeline

Source:

- arXiv: https://arxiv.org/abs/2606.21631v1

Claim from source: CuratorKIT unifies ingestion, hygiene, synthetic generation, quality gates, provenance-exact hallucination verification, adaptive recovery, and training-ready exports with per-sample provenance chains and structured rejection reasons.

Why it fits Enoch: this is less a single research experiment and more a missing pipeline invariant for Enoch’s dataset-quality/post-training work: every sample selection/rejection should be auditable.

Candidate experiment: prototype an Enoch data-curation ledger schema or fixture scorer that records per-sample source, hygiene checks, quality gates, rejection reasons, and export compatibility, then use it in the ALI-208 scorer.

Status recommendation: inject as infrastructure candidate if we want the dataset-quality track to produce reusable tooling rather than one-off scoring scripts.

## Lower-priority but interesting leads

- SpecGuard / verification-aware step-level speculative decoding: arXiv 2604.15244. Interesting for reasoning reliability and internal verifier signals, but may overlap VIA-SD/LTD.
- Goose anisotropic speculation trees: arXiv 2604.02047. Training-free speculative decoding; good fallback if training drafters is too expensive.
- ConfLayers: arXiv 2604.14612. Confidence-guided adaptive layer skipping for self-speculative decoding; likely useful as a slim-verifier proxy.
- GradFiltering / G-SNR: arXiv 2601.13697. Gradient signal-to-noise for instruction selection; may be expensive but conceptually aligned with dataset quality.
- DataProphet: arXiv 2603.19688. Training-free metric for supervision-data transfer in multimodal LLMs; worth revisiting if Enoch includes multimodal tracks.

## Recommended injection set

If injecting now, prioritize:

1. ADG answer-divergence data selection — runnable code, direct fit for ALI-208.
2. Reasoning Quality Emerges Early — direct ALI-207/ALI-208 bridge with cheap early-token scoring.
3. VIA-SD slim-verifier speculative decoding — direct ALI-206 extension.
4. LTD throughput-objective controller — direct ALI-206 scheduler/control objective.
5. CuratorKIT-style auditable curation ledger — infrastructure support for ALI-208/ALI-207.

Do not queue or dispatch these directly. They should enter Research Facility candidate/admission first, then one or two can be promoted after checking current runtime capacity and ALI priority.
