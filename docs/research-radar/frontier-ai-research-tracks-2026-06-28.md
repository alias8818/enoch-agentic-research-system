# Frontier AI research tracks — DSpark, post-training, and dataset quality

Date: 2026-06-28
Linear parent: ALI-205
Children: ALI-206, ALI-207, ALI-208

## Executive read

These are worth pursuing as Enoch research tracks, with one important constraint: they should become empirical artifacts, not broad speculation. Each track should produce a bounded note, a reproducible harness or dry-run, and a paper-candidate brief if the first evidence is promising.

The common theme is **quality-adjusted efficiency**:

1. DSpark asks whether we can get more useful output per decode step.
2. Post-training asks whether we can get more capability per parameter/update.
3. Dataset-quality benchmarking asks whether we can get more generalization per token.

That is a coherent Enoch direction because it fits the existing Research Facility contract: source-grounded, falsifiable, evidence-led, and measurable on local/GB10 hardware.

## Track 1 — DSpark / DeepSpec speculative decoding

Linear: ALI-206

### What appears new

DeepSeek's DeepSpec repo exposes a full-stack speculative decoding training/evaluation path with DSpark, DFlash, and Eagle3. Secondary reports and the DeepSpec README point to DSpark as a semi-autoregressive drafter with confidence-scheduled, hardware-aware verification. Reported headline claims are roughly 57–85% per-user speedup and 51–400% throughput uplift depending on concurrency/load, with benchmarks over Qwen/Gemma-style targets and production DeepSeek-V4 variants.

The interesting part is not merely "speculative decoding is faster". The promising mechanism is **adaptive verification budget allocation**: do not verify draft tails whose acceptance probability is poor under current load. That gives us a testable scheduler problem.

### First hypotheses to test

1. **Online acceptance scheduler beats static SPS(B) curves on local workloads.** Enoch can use recent acceptance-by-position, entropy, prompt class, and backend load to choose draft length dynamically.
2. **GB10 bottleneck may be memory/KV movement rather than drafter math.** Measure actual draft latency, verify latency, KV/cache pressure, and CUDA graph behavior before optimizing algorithmic acceptance only.
3. **Small-cache drafter training may be viable.** DeepSpec's default target-cache footprint may be too large for local iteration, but a sampled cache or distillation subset may be enough to test scheduler/acceptance ideas.
4. **Agentic workloads may differ from public evals.** Enoch prompts/tool outputs may have repetition/structure that changes speculative decoding acceptance profiles.

### Minimal experiment shape

- Source review: DSpark paper, DeepSpec README/code, DFlash, Eagle3, classic speculative decoding.
- Baseline models: start with the smallest supported Qwen/Gemma path or equivalent local model before attempting a large V4-style run.
- Metrics:
  - accepted tokens/cycle;
  - acceptance by draft position;
  - draft latency;
  - verification latency;
  - end-to-end decode tok/s;
  - p50/p95 latency at concurrency 1/N;
  - memory/KV footprint;
  - scheduler decision trace.
- Success threshold for first pass: a harness that can reproduce a baseline acceptance/latency curve and identify one scheduler modification with an explicit falsification test.

## Track 2 — fine-tuning / post-training research

Linear: ALI-207

### Why it is promising

Recent work suggests post-training outcomes are strongly conditional on data difficulty, quality, ordering, trace structure, optimizer duration, and which parameters/modules are updated. The key claim to test is not "SFT good" or "RL good". It is: **post-training generalization is controlled by data and update geometry more than most simple recipes expose**.

### First hypotheses to test

1. **Difficulty has an optimum under fixed data budget.** Too easy under-trains extrapolation; too hard increases in-distribution generalization gap.
2. **Verified long-CoT structure may transfer better than noisy larger data.** Bad data can make SFT look non-generalizing even when the method is not the limiting factor.
3. **Selective updates may preserve OOD behavior.** Attention-only / low-rank / layer-targeted updates may beat full fine-tune under small-data regimes.
4. **Specialized pretraining may beat finetune-only for far-domain data.** If domain data is unlike web text, introducing it earlier may reduce representational shock.
5. **Data regularization/replay is the real knob.** General data may act as a regularizer, not just as a selection pool.

### Minimal experiment shape

- Choose one low-cost base model likely to fit GB10/local iteration.
- Choose one task suite with held-out/OOD split and leakage controls.
- Compare tiny baselines:
  - no fine-tune / few-shot;
  - naive SFT;
  - difficulty-selected SFT;
  - diversity-selected SFT;
  - selective LoRA target modules if supported;
  - optional replay/general-data regularization.
- Required evidence:
  - exact dataset manifest;
  - checkpoint provenance;
  - train cost/time;
  - in-domain and OOD eval;
  - failure examples and regression cases.

## Track 3 — dataset diversity and generalized-understanding benchmark

Linear: ALI-208

### Core theory

The user's theory is plausible but needs careful operationalization: small models can sometimes behave like larger models if the dataset has unusually high coverage, structure, and learning signal density. Existing benchmarks mostly score model outputs, not the **learnability value of the dataset itself**.

The benchmark should estimate whether a dataset contains broad, non-redundant, compositional, and transferable training signal.

### Candidate score axes

1. **Lexical/token diversity** — entropy, long-tail coverage, repetition, near-duplicate collapse.
2. **Semantic diversity** — embedding-cluster richness/evenness/disparity.
3. **Concept graph coverage** — entities/concepts and relation density across examples.
4. **Compositional coverage** — number of templates/skills and held-out combination coverage.
5. **Gradient-space diversity** — proxy-model gradient entropy or G-Vendi-style score.
6. **Difficulty distribution** — model loss/uncertainty bands, not just human labels.
7. **Transfer proxy** — small controlled fine-tune followed by held-out/OOD eval.
8. **Anti-gaming checks** — diversity without correctness, noise, or contradiction should be penalized.

### Minimal experiment shape

- Build a scorer over two or more small contrasting datasets/fixtures.
- Produce a dataset quality report with per-axis scores and examples.
- Run a tiny downstream proxy: fine-tune or evaluate a small model on subsets selected by different score axes.
- Correlate at least one score with held-out/OOD improvement.
- Paper-candidate angle: **Dataset Quality Beyond Scale: Measuring Generalized Learning Signal Before Training**.

## Sequencing recommendation

1. Start ALI-206 first because DSpark is time-sensitive and has fresh open code/paper momentum.
2. In parallel, use ALI-208 to build the dataset-quality scorer because it can become infrastructure for ALI-207.
3. Use ALI-207 after the first scorer exists, so post-training experiments compare not just random/manual datasets but measured dataset slices.

## Immediate next actions

- ALI-206: pull DeepSpec metadata and paper, write a source-note, inspect hardware/storage requirements, and choose the first runnable target.
- ALI-208: define a v0 metric schema and fixture datasets; implement a dry-run scorer before any expensive training.
- ALI-207: literature matrix now, experiment after ALI-208's first scoring fixture is usable.
