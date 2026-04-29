# Featured paper selection

The launch site should sell a two-part story:

1. **The system is the product.** Enoch is a control plane for autonomous research: intake, queueing, dispatch gates, worker preflight, wake-gated completion, evidence sync, quality checks, and publication-style packaging.
2. **The output is also the product proof.** The generated corpus should show that the system can produce artifacts that are technically specific, evidence-bounded, and worth external critique or replication.

## Selection criteria

The first launch highlight set is biased toward artifacts that are easier to sell publicly because they combine several of these traits:

- a clear novelty hook;
- a strong systems angle;
- concrete reported metrics;
- reported evidence beyond a toy-only smoke test;
- relevance to agentic systems, local AI infrastructure, or model-serving reliability;
- clean caveats that avoid overclaiming.

## Launch-tier featured set

| Paper | Why it belongs on the site |
|---|---|
| Evidence-Bound Proof Synthesizer for Tool Ledger | Strongest agent/tool-use security artifact: proof-carrying tool calls, adversarial refusal, and real transcript replay. |
| DFlash Code-Generation Quality Guard | Strong speculative decoding story because it checks code quality, not just speed. |
| DFlash vLLM/SGLang Throughput Shootout | Clean GB10/vLLM performance headline with transparent negative SGLang evidence. |
| FlashAttention-4 Kernel Pipelining for sm_121 | Technically novel Blackwell/SM121 kernel exploration. |
| Open-Weight Integrity Twin Agent Sweep | Interesting model-behavior/evaluator-integrity result with public-vs-trusted score gaps. |
| Router-Distilled Triton MLP Full-Model Integration | Concrete sparse-inference integration with Triton and whole-layer prefill speedups. |
| Resource-Bounded Agent Kernel | Directly reinforces the Enoch thesis that agents need OS-like governance. |
| Adversarial Channel Router | Agent security story around typed/authenticated channel isolation. |
| Agent Identity Rotation | Crisp privilege-separation mechanism for planner/executor/committer roles. |
| Value-per-Joule Broker Online Canary | Easy-to-understand local AI operations result with energy/cost metrics. |
| Memory Pressure Admission Gate | Practical serving-control artifact with latency/energy improvements and caveats. |
| Cache Churn Alarm vLLM Adapter Benchmark | Nuanced KV-cache pressure control result that does not overclaim latency. |

## Strong runners-up

These are good candidates for deeper cards or follow-up posts:

- DFlash vs Existing Spec-Dec Baseline Harness
- GB10 Joule Router Live Calibration Adapter
- Prefix Seeder Serving Adapter Benchmark
- Evidence-First Answerability Cutoff Integration Benchmark
- Deadline-Guarded Speculation Live Serving Validation
- Byte-Memory Pointer Decoder for Fragile Spans
- Hot-Cold Tensor Paging
- Context Reuse Clusterer Local Serving Harness
- CPU-Offload Stress Harness Real-Server Scaleup
- Agent App Store With Repro Sandboxes

## Framing rule

Even for the strongest artifacts, use language like **reported**, **bounded**, **candidate**, **artifact**, and **replication-worthy**. The point is not to pretend these are peer-reviewed human papers. The point is to show that the system can generate technically specific, evidence-aware research artifacts that are worth inspecting.
