# Enoch unified trace/oracle project: `spec_trace_oracle_v0`

Build **one DFlash-first tracing harness** that runs normal speculative decoding, but shadows four additional signal probes during each round:

1. **SSD-lite probe:** Can we predict accept length / rejection / bonus-token branch?
2. **Dynamic vocab probe:** Would smaller contextual vocabularies cover the target token?
3. **Controller probe:** Would different block sizes / no-spec decisions have been better?
4. **Retrieval probe:** Would prompt/session/global suffix matches have proposed accepted spans?
5. **Grammar probe:** For structured tasks, does the valid-token frontier materially reduce entropy or invalid draft work?

Do **not** implement the five systems yet. The first pass should produce an oracle report that says which one deserves implementation.

This is aligned with the current research directions: Saguaro/SSD precomputes likely verification outcomes while verification is ongoing; SpecVocab selects a per-step vocabulary subset instead of using a fixed reduced vocab; SuffixDecoding uses suffix trees over prompts and previous outputs; and constrained decoding work such as DOMINO/JSONSchemaBench shows that schema/grammar handling has real systems overhead and evaluation value. ([arXiv][1])

---

## 0. Harness design principle

Run **one primary DFlash trace** at a large draft block size, then derive the oracles offline.

Recommended name:

```text
enoch/research/spec_trace_oracle_v0/
```

Primary run:

```text
Target: Qwen/Qwen3-8B
Draft:  z-lab/Qwen3-8B-DFlash-b16
Mode:   DFlash, num_speculative_tokens=16
```

Reason: the DFlash repository explicitly lists Qwen3-8B non-thinking and Llama-3.1-8B-Instruct support, and its Transformers example uses `Qwen/Qwen3-8B` with `z-lab/Qwen3-8B-DFlash-b16`, making this a practical local default. ([GitHub][2])

Optional cross-check:

```text
Target: meta-llama/Llama-3.1-8B-Instruct
Draft:  z-lab/LLaMA3.1-8B-Instruct-DFlash-UltraChat
```

Reference-only:

```text
EAGLE-3 on a 48-prompt mini-slice, only if same target/model family is already wired.
```

Do not let EAGLE-3 integration block the harness. EAGLE-3 is useful as a reference because it uses direct token prediction and multi-layer feature fusion, but the harness decision should be DFlash-centered. ([arXiv][3])

---

# 1. Exact trace schema

Use **JSONL per speculative round** plus optional compact sidecars.

Recommended files:

```text
traces/
  run_manifest.json
  rounds.jsonl
  requests.jsonl
  final_outputs.jsonl
  candidate_sets.parquet
  topk_sidecar.npz
  hidden_sketch_sidecar.npz        # optional
  timing_microbench.json
```

## 1.1 `run_manifest.json`

One file per run.

```json
{
  "schema_version": "spec_trace_oracle_v0.1",
  "run_id": "2026-05-19-qwen3-8b-dflash-b16-main",
  "created_utc": "2026-05-19T00:00:00Z",
  "host": {
    "machine_class": "GB10-class local",
    "gpu_name": "string",
    "gpu_count": 1,
    "driver_version": "string",
    "cuda_version": "string",
    "torch_version": "string",
    "backend": "transformers|vllm|sglang|custom",
    "commit_enoch": "git_sha",
    "commit_decoder": "git_sha"
  },
  "models": {
    "target_model_id": "Qwen/Qwen3-8B",
    "draft_model_id": "z-lab/Qwen3-8B-DFlash-b16",
    "reference_model_id": null,
    "tokenizer_id": "Qwen/Qwen3-8B",
    "dtype": "bf16|fp16|int8|fp8",
    "quantization": "none|awq|gptq|fp8|other",
    "max_context_tokens": 32768
  },
  "decode_config": {
    "spec_method": "dflash",
    "num_speculative_tokens": 16,
    "temperatures": [0.0, 0.7],
    "top_p": 0.95,
    "top_k_sampling": null,
    "repetition_penalty": 1.0,
    "seed_base": 1700000000,
    "stop_token_ids": [],
    "max_new_tokens_default": 384
  },
  "logging_config": {
    "draft_topk": 32,
    "target_topk": 32,
    "store_full_logits": false,
    "store_text": false,
    "store_token_text_sample": false,
    "hidden_sketch_dim": 256,
    "hidden_sketch_rate": 0.1,
    "candidate_vocab_budgets": [128, 256, 512, 1024, 2048, 4096],
    "suffix_probe_lengths": [4, 8, 16, 32],
    "suffix_candidate_count": 4
  }
}
```

## 1.2 `requests.jsonl`

One line per generation request.

```json
{
  "run_id": "string",
  "request_id": "string",
  "prompt_id": "string",
  "category": "agentic_loop|json_tool|code_edit|math_reasoning|open_chat|long_context",
  "dataset_source": "enoch_private|humaneval|mbpp|gsm8k|math500|mt_bench|jsonschemabench|synthetic",
  "temperature": 0.0,
  "top_p": 0.95,
  "max_new_tokens": 512,
  "seed": 1700000001,
  "prompt_token_count": 1536,
  "prompt_hash_sha256": "string",
  "prompt_prefix_hash_sha256": "string",
  "contains_private_data": true,
  "grammar": {
    "enabled": false,
    "grammar_type": null,
    "schema_id": null,
    "schema_hash_sha256": null
  },
  "cache_scope": {
    "prompt_cache_enabled": true,
    "session_cache_enabled": true,
    "global_cache_enabled": true,
    "global_cache_snapshot_id": "string|null"
  }
}
```

## 1.3 `rounds.jsonl`

This is the core trace. One line per speculative round.

```json
{
  "schema_version": "spec_trace_oracle_v0.1",
  "run_id": "string",
  "request_id": "string",
  "round_id": 17,

  "round_position": {
    "prefix_len_tokens": 2048,
    "generated_len_before_round": 96,
    "remaining_budget_tokens": 416,
    "context_window_remaining": 30000,
    "previous_round_accepted_len": 5,
    "rolling_accept_rate_last_8": 0.61,
    "rolling_mean_accepted_len_last_8": 4.75,
    "rolling_rejection_rate_last_8": 0.39
  },

  "decode_state": {
    "temperature": 0.0,
    "top_p": 0.95,
    "draft_block_size": 16,
    "batch_size": 1,
    "active_batch_position": 0,
    "kv_cache_tokens_before": 2048,
    "seed": 1700000017
  },

  "prefix_fingerprints": {
    "last_4_hash": "string",
    "last_8_hash": "string",
    "last_16_hash": "string",
    "last_32_hash": "string",
    "last_64_hash": "string"
  },

  "draft": {
    "method": "dflash",
    "draft_token_ids": [101, 102, 103],
    "draft_len": 16,
    "draft_token_classes": [
      "word",
      "whitespace",
      "punct",
      "json_struct",
      "code_struct",
      "number",
      "identifier",
      "unknown"
    ],
    "topk_ref": "topk_sidecar.npz:draft:req=...:round=17",
    "topk_k": 32,
    "per_position_entropy": [1.23, 2.34],
    "per_position_top1_prob": [0.72, 0.31],
    "per_position_top2_margin": [0.44, 0.07],
    "lm_head_time_ms": 0.42,
    "forward_time_ms": 2.31,
    "total_time_ms": 2.96
  },

  "target_verify": {
    "verified_token_ids": [101, 102, 103],
    "verify_len": 16,
    "target_topk_ref": "topk_sidecar.npz:target:req=...:round=17",
    "target_topk_k": 32,
    "target_logprob_of_draft_tokens": [-0.02, -0.10, -3.92],
    "target_entropy_per_position": [0.18, 0.44, 4.21],
    "target_top1_prob_per_position": [0.94, 0.82, 0.17],
    "target_top2_margin_per_position": [0.88, 0.71, 0.03],
    "target_argmax_token_ids": [101, 102, 999],
    "bonus_token_id": 999,
    "bonus_token_rank_in_draft_topk": null,
    "bonus_token_rank_in_target_topk": 1,
    "forward_time_ms": 8.91,
    "lm_head_time_ms": 1.06,
    "sampling_or_argmax_time_ms": 0.12,
    "total_time_ms": 10.34
  },

  "acceptance": {
    "accepted_len": 2,
    "accepted_token_ids": [101, 102],
    "rejected": true,
    "rejected_pos": 2,
    "rejected_draft_token_id": 103,
    "target_replacement_token_id": 999,
    "emitted_token_ids": [101, 102, 999],
    "emitted_len": 3,
    "all_draft_tokens_accepted": false,
    "stop_reached": false,
    "lossless_check_passed": true
  },

  "vocab_probe": {
    "candidate_set_ref": "candidate_sets.parquet:req=...:round=17",
    "budgets": [128, 256, 512, 1024, 2048, 4096],
    "selectors": [
      "global_freq",
      "prompt_tokens",
      "session_suffix",
      "global_suffix",
      "draft_topk_union",
      "target_prev_topk",
      "grammar_frontier",
      "hybrid_union"
    ],
    "coverage_by_selector_budget": {
      "hybrid_union@512": {
        "target_token_covered_positions": [true, true, false],
        "first_miss_pos": 2,
        "accepted_prefix_under_vocab": 2
      }
    }
  },

  "retrieval_probe": {
    "enabled": true,
    "lookup_time_ms": 0.18,
    "best_match": {
      "source": "prompt|session|global|null",
      "match_suffix_len": 16,
      "candidate_span_token_ids": [101, 102, 999, 104],
      "candidate_span_len": 4,
      "rank": 1,
      "source_request_id": "string|null",
      "source_offset": 1234,
      "recency_rank": 7
    },
    "top_candidates_ref": "candidate_sets.parquet:req=...:round=17:retrieval",
    "exact_prefix_match_to_emitted": 3,
    "would_accept_len_greedy_lower_bound": 3
  },

  "grammar_probe": {
    "enabled": false,
    "schema_id": null,
    "grammar_state_id": null,
    "valid_token_count": null,
    "valid_token_hash": null,
    "valid_token_set_ref": null,
    "draft_invalid_positions": [],
    "draft_invalid_count": 0,
    "target_emitted_token_valid": true,
    "forced_token": false,
    "forced_token_id": null,
    "grammar_mask_time_ms": null
  },

  "controller_features": {
    "feature_vector_version": "v0.1",
    "eligible_pre_verify_features_only": {
      "prefix_len_tokens": 2048,
      "generated_len_before_round": 96,
      "previous_round_accepted_len": 5,
      "rolling_mean_accepted_len_last_8": 4.75,
      "draft_entropy_mean": 2.17,
      "draft_entropy_max": 5.13,
      "draft_top1_prob_mean": 0.52,
      "draft_margin_mean": 0.21,
      "token_class_mode": "word",
      "category": "code_edit",
      "temperature": 0.0,
      "cache_match_suffix_len": 16,
      "grammar_valid_token_count": null
    },
    "post_verify_features_for_analysis_only": {
      "target_entropy_mean": 1.84,
      "target_margin_mean": 0.31
    }
  },

  "timing": {
    "round_wall_time_ms": 13.82,
    "gpu_elapsed_ms": 13.41,
    "cpu_overhead_ms": 0.41,
    "cuda_sync_used_for_measurement": true,
    "tokens_emitted_per_second_round": 217.08
  },

  "memory": {
    "gpu_allocated_mb_before": 24500,
    "gpu_allocated_mb_after": 24650,
    "gpu_peak_allocated_mb": 24800,
    "kv_cache_estimated_mb": 8120
  },

  "quality_and_debug": {
    "nan_or_inf_seen": false,
    "tokenizer_decode_error": false,
    "round_error": null,
    "notes": []
  }
}
```

## 1.4 `candidate_sets.parquet`

Use Parquet rather than embedding large sets in `rounds.jsonl`.

Columns:

```text
run_id: string
request_id: string
round_id: int
position: int                     # draft position within round, or -1 for round-level retrieval
selector: string                  # global_freq, prompt_tokens, session_suffix, etc.
budget: int                       # 128, 256, 512, ...
candidate_token_ids: list<int32>
candidate_source: string
candidate_count: int
contains_target_token: bool
contains_draft_token: bool
target_token_rank_if_present: int|null
draft_token_rank_if_present: int|null
build_time_ms: float
```

## 1.5 `topk_sidecar.npz`

Store compact top-k arrays, not full logits.

Required arrays:

```text
draft_topk_ids          int32 [num_round_positions, K_draft_topk]
draft_topk_logprobs     float16 [num_round_positions, K_draft_topk]
target_topk_ids         int32 [num_round_positions, K_target_topk]
target_topk_logprobs    float16 [num_round_positions, K_target_topk]
round_index             int64 [num_round_positions, 4]
                         # columns: request_idx, round_id, position, source_type
```

## 1.6 Optional `hidden_sketch_sidecar.npz`

Only store this if dynamic vocab looks promising or you want cheap selector training.

Do **not** store full hidden states initially. Store random-projection sketches.

```text
draft_hidden_sketch      float16 [sampled_positions, 256]
target_hidden_sketch     float16 [sampled_positions, 256]    # optional
round_index              int64 [sampled_positions, 4]
projection_seed          int64 scalar
projection_matrix_hash   string scalar
```

Sampling rate:

```text
hidden_sketch_rate = 0.10
```

This is enough to train a toy vocab selector or acceptance classifier without turning the trace into a tensor dump.

---

# 2. Minimal benchmark suite

Run **one primary DFlash suite**:

```text
6 categories × 32 prompts × 2 temperatures = 384 generations
```

Total maximum new tokens:

```text
~155k generated tokens
```

Use this exact first-pass suite.

| Category         | Prompts | Max new tokens | Temperatures | Why it matters                                                                                                                   |
| ---------------- | ------: | -------------: | ------------ | -------------------------------------------------------------------------------------------------------------------------------- |
| `agentic_loop`   |      32 |            512 | 0.0, 0.7     | Tests SSD-lite stability and retrieval/suffix reuse. Enoch’s autonomous loops are likely repetitive and branch-predictable.      |
| `json_tool`      |      32 |            256 | 0.0, 0.7     | Tests grammar/schema-aware speculation, dynamic vocab, forced tokens, and structured-output validity.                            |
| `code_edit`      |      32 |            512 | 0.0, 0.7     | Tests suffix reuse, punctuation/indentation predictability, dynamic vocab tails, and acceptance on structured but non-JSON text. |
| `math_reasoning` |      32 |            512 | 0.0, 0.7     | Tests high/medium entropy transitions, controller backoff, and whether speculation collapses during reasoning.                   |
| `open_chat`      |      32 |            256 | 0.0, 0.7     | Negative-control category. Prevents overfitting to structured/repetitive workloads.                                              |
| `long_context`   |      32 |            384 | 0.0, 0.7     | Tests prompt-local suffix reuse, context-length latency shifts, and KV/memory sensitivity.                                       |

## Prompt sources

Use public prompts where possible, plus Enoch-private prompts as a separate labeled partition.

Recommended split:

```text
Public/reproducible: 24 prompts/category
Enoch-private:        8 prompts/category
```

Public sources:

| Category         | Suggested source                                                                          |
| ---------------- | ----------------------------------------------------------------------------------------- |
| `agentic_loop`   | synthetic self-reflection / tool-retry traces; optionally public SWE-agent style snippets |
| `json_tool`      | JSONSchemaBench small/medium schemas + synthetic tool-call requests                       |
| `code_edit`      | HumanEval/MBPP edit variants, small bugfix patches                                        |
| `math_reasoning` | GSM8K + MATH500 subset                                                                    |
| `open_chat`      | MT-Bench / Alpaca-style prompts                                                           |
| `long_context`   | summarization/RAG snippets with repeated sections and citations                           |

JSONSchemaBench is useful here because it contains real-world JSON schemas and is designed to evaluate constrained decoding efficiency and coverage. ([arXiv][4])

## Models

Primary:

```text
Target: Qwen/Qwen3-8B
Draft:  z-lab/Qwen3-8B-DFlash-b16
Backend: Transformers first, vLLM/SGLang if already wired
Draft block: 16
```

Secondary sanity slice:

```text
Target: Llama-3.1-8B-Instruct
Draft:  z-lab/LLaMA3.1-8B-Instruct-DFlash-UltraChat
Prompts: 6 categories × 8 prompts × 1 temperature = 48 generations
Temperature: 0.0
```

EAGLE-3 reference slice:

```text
Prompts: same 48-prompt sanity slice
Only run if EAGLE-3 is already available for the same target/tokenizer path.
```

Do not run full EAGLE-3 unless the DFlash trace produces a candidate worth comparing.

---

# 3. Oracle analyses from the same trace

## 3.1 SSD-lite verification-outcome oracle

### Question

Can Enoch predict the next verification outcome well enough that branch precomputation is worth implementing?

### Labels

From each round:

```text
accepted_len
all_draft_tokens_accepted
rejected_pos
bonus_token_id
bonus_token_in_target_topk
emitted_token_ids
```

Use only **pre-verification features** for prediction:

```text
category
temperature
prefix length
generated length
previous accepted length
rolling accepted length
draft entropy mean/max
draft top-1 probability mean
draft top-2 margin mean
token class mix
retrieval match length
grammar valid-token count
```

Do **not** train with current target entropy or current target logits unless labeling it as an upper-bound oracle.

### Models

Run three tiny predictors:

```text
accept_len_classifier:      logistic regression / XGBoost / small MLP
all_accepted_classifier:    logistic regression
bonus_token_ranker:         top-k from draft, target-prev-topk, suffix candidates, grammar frontier
```

### Outputs

```text
ssd_oracle.json
ssd_accept_len_confusion.csv
ssd_branch_hit_by_category.csv
ssd_expected_latency_model.csv
```

### Metrics

```text
top1_accept_len_accuracy
top2_accept_len_accuracy
top4_outcome_hit_rate
bonus_token_top4_hit
bonus_token_top8_hit
expected_saved_draft_ms
expected_wasted_branch_ms
modeled_tpot_gain_percent
```

### Interpretation

Implement SSD-lite only if the oracle says:

```text
top4_outcome_hit_rate >= 0.60
AND draft_total_time_ms / round_wall_time_ms >= 0.08
AND modeled_tpot_gain_percent >= 8
AND expected_wasted_branch_ms <= 0.5 * expected_saved_draft_ms
```

Kill SSD-lite if:

```text
top4_outcome_hit_rate < 0.50
OR draft_total_time_ms / round_wall_time_ms < 0.05
OR modeled_tpot_gain_percent < 5
```

---

## 3.2 Dynamic speculative vocabulary oracle

### Question

Can a small contextual vocabulary cover the target/emitted tokens often enough to reduce draft LM-head cost?

SpecVocab is relevant because it argues that a fixed reduced vocab can fail when the target token is out-of-vocabulary, while per-step vocabulary selection can retain acceptance and improve throughput. ([arXiv][5])

### Candidate selectors

Evaluate these sets for each round position:

```text
global_freq@N
prompt_tokens@N
session_suffix@N
global_suffix@N
draft_topk_union@N
target_prev_topk@N
grammar_frontier@N
hybrid_union@N
```

Budgets:

```text
N = 128, 256, 512, 1024, 2048, 4096
```

Hybrid priority order:

```text
1. grammar_frontier if active
2. exact prompt/session/global suffix continuation tokens
3. draft top-k tokens
4. previous target top-k tokens
5. prompt token IDs
6. global frequency fallback
```

### Outputs

```text
vocab_oracle.json
vocab_coverage_by_budget.csv
vocab_miss_examples.jsonl
lm_head_microbench.json
```

### Metrics

```text
target_token_coverage@N
accepted_prefix_under_vocab@N
oov_rejection_rate@N
draft_lm_head_fraction
indexed_lm_head_speedup_estimate
modeled_tpot_gain_percent
coverage_by_category
coverage_by_token_class
```

### Required microbench

Run a small isolated timing pass:

```text
full_vocab_lm_head_ms
indexed_vocab_512_ms
indexed_vocab_1024_ms
indexed_vocab_2048_ms
indexed_vocab_4096_ms
candidate_build_ms
```

### Implement dynamic vocab if:

```text
draft_lm_head_fraction >= 0.20
AND hybrid_union@2048 target_token_coverage >= 0.95
AND oov_rejection_rate@2048 <= 0.03
AND indexed_lm_head_2048 is at least 1.30x faster than full-vocab head
AND modeled_tpot_gain_percent >= 5
```

Kill dynamic vocab if:

```text
draft_lm_head_fraction < 0.12
OR hybrid_union@4096 target_token_coverage < 0.95
OR indexed vocab matmul is slower than full vocab matmul
OR oov_rejection_rate@2048 > 0.08
```

---

## 3.3 Entropy/acceptance controller oracle

### Question

Would a small controller choosing block size / no-spec / proposer type beat fixed DFlash?

### Key shortcut

Run DFlash with block size 16. Then simulate smaller block sizes from the same round:

```text
block_size = 1, 2, 4, 8, 16
```

Approximate accepted length under smaller block size:

```text
accepted_len_k = min(accepted_len_16, k)
```

Use timing microbench to model draft cost at each block size.

Also model `no_spec`:

```text
no_spec_cost = target_next_token_decode_ms
```

You can get this from a small AR timing slice, not from full AR benchmarking.

### Outputs

```text
controller_oracle.json
controller_action_distribution.csv
controller_oracle_gain_by_category.csv
controller_features_train.parquet
```

### Metrics

```text
best_static_block_size
oracle_dynamic_tpot
best_static_tpot
oracle_gain_over_best_static_percent
oracle_gain_over_fixed_b16_percent
acceptance_predictor_auc
regression_by_category
p95_latency_delta
```

### Implement controller if:

```text
oracle_gain_over_best_static_percent >= 8
AND acceptance_predictor_auc >= 0.65
AND simple_rule_policy_captures >= 50% of oracle gain
AND no category modeled regression > 3
```

Kill controller if:

```text
oracle_gain_over_best_static_percent < 5
OR acceptance_predictor_auc < 0.60
OR simple policy gain < 3
OR p95 latency worsens by > 5
```

### First controller actions

Start with only:

```text
block_size ∈ {2, 4, 8, 16}
no_spec ∈ {true, false}
```

Do not route among five proposers until this basic controller has signal.

---

## 3.4 Retrieval/suffix-cache oracle

### Question

Would a model-free suffix proposer beat or complement DFlash on Enoch-style repeated outputs?

SuffixDecoding is explicitly designed for agentic/repetitive workloads using suffix trees over prompt and prior outputs; vLLM also documents suffix decoding as useful for repetition-heavy tasks such as code editing, self-reflection, self-consistency, and RL rollouts. ([arXiv][6])

### Shortcut implementation

Do not build a full suffix tree first.

Use a rolling n-gram index:

```text
key = hash(last_n_tokens), n ∈ {4, 8, 16, 32}
value = list of following spans up to 32 tokens
```

Scopes:

```text
prompt-local
session-local
global-cache snapshot
```

For each round, shadow-propose:

```text
top 4 candidate spans
max span length = 32
```

Compare candidate span to actual emitted target-verified output.

### Outputs

```text
retrieval_oracle.json
retrieval_hits_by_scope.csv
retrieval_failure_cases.jsonl
cache_memory_report.json
```

### Metrics

```text
round_hit_rate
accepted_tokens_per_hit
accepted_tokens_per_round
lookup_time_ms
cache_memory_mb
modeled_tpot_gain_percent
hit_rate_by_category
hit_rate_by_suffix_len
```

### Implement retrieval/suffix cache if:

```text
round_hit_rate >= 0.20 on agentic_loop or code_edit
AND accepted_tokens_per_hit >= 3.0
AND lookup_time_ms <= 0.20
AND modeled_tpot_gain_percent >= 10 on at least two structured/repetitive categories
AND modeled average gain across full suite >= 5
```

Kill retrieval if:

```text
round_hit_rate < 0.10
OR accepted_tokens_per_hit < 1.5
OR lookup_time_ms > 10% of round_wall_time_ms
OR gains appear only in private Enoch traces and not in public/synthetic reproductions
```

---

## 3.5 Grammar/schema-aware speculation oracle

### Question

For structured outputs, does grammar information reduce the speculative search space enough to justify implementation?

DOMINO is directly relevant because it addresses subword/token alignment and uses precomputation/speculation for constrained decoding; JSONSchemaBench is useful because it provides real schemas and evaluates constrained decoding efficiency and coverage. ([arXiv][7])

### Shadow probe

For `json_tool` prompts:

```text
Compute grammar-valid token frontier per round.
Do not constrain generation yet.
Log whether DFlash draft tokens are valid.
Log whether target/emitted tokens are valid.
Log valid_token_count.
Log forced-token states.
```

### Outputs

```text
grammar_oracle.json
grammar_frontier_stats.csv
grammar_invalid_draft_cases.jsonl
schema_complexity_report.csv
```

### Metrics

```text
median_valid_token_count
p90_valid_token_count
forced_token_round_fraction
draft_invalid_position_rate
target_token_in_frontier_rate
grammar_mask_time_ms
modeled_tpot_gain_percent
schema_compliance_rate
```

### Implement grammar-aware decoding if:

```text
median_valid_token_count <= 512
OR median_valid_token_count <= 0.10 * vocab_size
AND forced_token_round_fraction >= 0.15
AND draft_invalid_position_rate >= 0.10
AND grammar_mask_time_ms <= 10% of round_wall_time_ms
AND modeled_tpot_gain_percent >= 8 on json_tool
```

Kill grammar-aware speculation if:

```text
grammar_mask_time_ms > 20% of round_wall_time_ms
OR median_valid_token_count > 4096 and forced_token_round_fraction < 0.05
OR tokenizer/grammar alignment failures exceed 1%
OR gains only appear on toy schemas
```

---

# 4. Decision matrix

Use this matrix after the first trace/oracle run.

| Trace result                                                                           | Implement next                                   | Rationale                                                                                    |
| -------------------------------------------------------------------------------------- | ------------------------------------------------ | -------------------------------------------------------------------------------------------- |
| SSD top-4 outcome hit ≥60%, draft cost ≥8% of round, modeled gain ≥8%                  | **SSD-lite**                                     | Round-boundary overhead is predictable enough to hide or precompute.                         |
| Dynamic vocab coverage@2048 ≥95%, LM-head fraction ≥20%, indexed head ≥1.3× faster     | **Dynamic vocab**                                | Draft output projection is a real bottleneck and can be reduced without too many OOV misses. |
| Controller oracle gain over best static ≥8%, acceptance AUC ≥0.65                      | **Entropy/acceptance controller**                | Fixed DFlash policy is leaving measurable performance on the table.                          |
| Retrieval hit rate ≥20%, accepted tokens/hit ≥3, lookup ≤0.2 ms                        | **Retrieval/suffix cache**                       | Repetition is strong enough for model-free speculation.                                      |
| JSON median valid frontier ≤512 or forced-token fraction ≥15%, invalid draft rate ≥10% | **Grammar/schema-aware decoding**                | Structure is strong enough to shape speculation.                                             |
| Multiple branches pass                                                                 | **Controller first, then plug in best proposer** | Controller becomes the router. Avoid implementing several independent systems.               |
| Only grammar passes                                                                    | **Grammar-aware DFlash for tool/JSON path only** | Keep it scoped; do not touch open-text decode.                                               |
| Only retrieval passes                                                                  | **Suffix cache as pre-DFlash proposer**          | Cheap, no training, likely agentic-specific.                                                 |
| Only dynamic vocab passes                                                              | **Vocab selector + LM-head microkernel**         | Implementation effort justified only if LM-head bottleneck is proven.                        |
| Only SSD passes                                                                        | **SSD-lite simulator → limited branch cache**    | Do not attempt full Saguaro on one GPU until branch hit-rate is proven.                      |
| No branch has modeled gain ≥5%                                                         | **Stop whole line for now**                      | DFlash is already near local optimum for this workload. Publish negative trace report.       |

---

# 5. Concrete success and kill thresholds

## Whole harness success threshold

The unified trace/oracle project succeeds if it produces at least one of:

```text
A. One branch with modeled TPOT gain >= 8%
B. Two branches with modeled TPOT gain >= 5%
C. A clean negative result showing all five branches have upper-bound gain < 5%
D. A workload-specific result: e.g., retrieval or grammar gives >= 10% on agentic/json but not general text
```

A negative result is useful if it includes:

```text
acceptance distributions
latency breakdown
oracle upper bounds
failure cases
public reproducible prompts
model/hardware details
```

## Whole line kill threshold

Stop the speculative-decoding branch line if all are true:

```text
SSD modeled gain < 5%
Dynamic vocab modeled gain < 5%
Controller oracle gain over best static < 5%
Retrieval modeled average gain < 5% and category gain < 8%
Grammar modeled json_tool gain < 8%
Measurement noise > 5% after 3 repeated timing passes
```

## Branch thresholds summary

| Branch        | Continue threshold                                                                   | Kill threshold                                                    |
| ------------- | ------------------------------------------------------------------------------------ | ----------------------------------------------------------------- |
| SSD-lite      | top-4 outcome hit ≥60%; draft cost ≥8%; modeled gain ≥8%                             | top-4 hit <50%; draft cost <5%; modeled gain <5%                  |
| Dynamic vocab | coverage@2048 ≥95%; LM-head ≥20%; indexed head ≥1.3× faster; modeled gain ≥5%        | coverage@4096 <95%; LM-head <12%; indexed slower than full        |
| Controller    | oracle gain ≥8%; AUC ≥0.65; simple policy captures ≥50% oracle gain                  | oracle gain <5%; AUC <0.60; p95 regression >5%                    |
| Retrieval     | hit ≥20%; accepted tokens/hit ≥3; lookup ≤0.2 ms; category gain ≥10%                 | hit <10%; accepted tokens/hit <1.5; lookup >10% round time        |
| Grammar       | median frontier ≤512 or ≤10% vocab; forced rounds ≥15%; invalid draft ≥10%; gain ≥8% | grammar overhead >20%; frontier too large; alignment failures >1% |

---

# 6. Estimated wall-clock time on one GB10-class machine

Assuming Qwen3-8B-class target, DFlash b16, detailed tracing, batch size 1.

| Phase                        | Work                                                                   |                       Expected wall-clock |
| ---------------------------- | ---------------------------------------------------------------------- | ----------------------------------------: |
| Instrumentation shortcut     | Add trace hooks, top-k capture, latency timers, n-gram retrieval probe | 4–8 hours if DFlash harness already works |
| Warmup                       | 12 warmup prompts, not logged                                          |                                 15–30 min |
| Timing microbench            | AR next-token, DFlash b1/b2/b4/b8/b16, LM-head indexed estimates       |                                 30–60 min |
| Primary DFlash trace         | 384 generations, ~155k max new tokens                                  |                                 2–6 hours |
| AR baseline mini-slice       | 48 prompts, temp 0.0                                                   |                                 30–90 min |
| EAGLE-3 reference mini-slice | 48 prompts, optional                                                   |                                 1–3 hours |
| Oracle analysis              | SSD, vocab, controller, retrieval, grammar reports                     |                                30–120 min |
| Report generation            | Markdown + JSON artifacts                                              |                                 30–60 min |

Expected first-pass runtime:

```text
Same day if DFlash is already working.
1–2 days if instrumentation needs cleanup.
```

Do not spend more than two engineering days before producing the first oracle report.

---

# 7. Enoch artifact checklist

## Required directory layout

```text
.enoch/
  project_decision.json

spec_trace_oracle_v0/
  run_notes.md
  metrics.json
  trace_schema.md
  oracle_report.md
  failure_cases.jsonl
  timing_microbench.json

  traces/
    run_manifest.json
    requests.jsonl
    rounds.jsonl
    final_outputs.jsonl
    candidate_sets.parquet
    topk_sidecar.npz
    hidden_sketch_sidecar.npz       # optional

  oracle/
    ssd_oracle.json
    vocab_oracle.json
    controller_oracle.json
    retrieval_oracle.json
    grammar_oracle.json
    branch_decision_matrix.csv

  plots/
    accepted_len_hist.png
    latency_breakdown.png
    vocab_coverage_curve.png
    retrieval_hit_curve.png
    controller_oracle_gain.png
    grammar_frontier_distribution.png
```

## `run_notes.md`

Minimum contents:

```markdown
# spec_trace_oracle_v0 run notes

## Run identity
- run_id:
- date:
- machine:
- GPU:
- backend:
- Enoch commit:
- decoder commit:

## Models
- target:
- draft:
- tokenizer:
- dtype:
- quantization:

## Decode config
- DFlash block size:
- temperatures:
- top_p:
- max tokens:

## Benchmark suite
- categories:
- prompt counts:
- public/private split:
- exclusions:

## Known issues
- measurement caveats:
- failed prompts:
- backend warnings:
```

## `metrics.json`

Top-level metrics only.

```json
{
  "run_id": "string",
  "summary": {
    "num_requests": 384,
    "num_rounds": 12345,
    "num_generated_tokens": 155000,
    "mean_tpot_ms": 0.0,
    "p50_tpot_ms": 0.0,
    "p95_tpot_ms": 0.0,
    "mean_tokens_per_sec": 0.0,
    "mean_accepted_len": 0.0,
    "p50_accepted_len": 0.0,
    "p95_accepted_len": 0.0,
    "draft_time_fraction": 0.0,
    "verify_time_fraction": 0.0,
    "cpu_overhead_fraction": 0.0
  },
  "branch_oracles": {
    "ssd_lite": {
      "top4_outcome_hit_rate": 0.0,
      "modeled_tpot_gain_percent": 0.0,
      "decision": "continue|kill"
    },
    "dynamic_vocab": {
      "coverage_hybrid_2048": 0.0,
      "draft_lm_head_fraction": 0.0,
      "modeled_tpot_gain_percent": 0.0,
      "decision": "continue|kill"
    },
    "controller": {
      "oracle_gain_over_best_static_percent": 0.0,
      "acceptance_predictor_auc": 0.0,
      "decision": "continue|kill"
    },
    "retrieval_suffix": {
      "round_hit_rate": 0.0,
      "accepted_tokens_per_hit": 0.0,
      "modeled_tpot_gain_percent": 0.0,
      "decision": "continue|kill"
    },
    "grammar_schema": {
      "median_valid_token_count": 0.0,
      "draft_invalid_position_rate": 0.0,
      "modeled_tpot_gain_percent": 0.0,
      "decision": "continue|kill"
    }
  }
}
```

## `trace_schema.md`

Include:

```text
schema version
field definitions
required vs optional fields
privacy notes
sidecar array shapes
known limitations
```

## `oracle_report.md`

Structure:

```markdown
# Oracle report

## Executive decision
- recommended next project:
- second-best:
- stop conditions:

## DFlash baseline
- acceptance distribution
- latency breakdown
- per-category performance

## SSD-lite oracle
## Dynamic vocab oracle
## Controller oracle
## Retrieval/suffix oracle
## Grammar/schema oracle

## Cross-branch interactions
## Negative results
## Failure cases
## Reproducibility notes
```

## `failure_cases.jsonl`

One line per notable failure.

```json
{
  "run_id": "string",
  "request_id": "string",
  "round_id": 17,
  "category": "code_edit",
  "failure_type": "low_acceptance|vocab_miss|retrieval_false_hit|grammar_alignment|timing_noise|ssd_mispredict",
  "short_description": "string",
  "prefix_hash": "string",
  "draft_token_ids": [1, 2, 3],
  "target_token_ids": [1, 2, 9],
  "metrics": {
    "accepted_len": 2,
    "draft_entropy_mean": 2.1,
    "target_entropy_mean": 4.7
  }
}
```

## `.enoch/project_decision.json`

This should be machine-readable.

```json
{
  "project": "spec_trace_oracle_v0",
  "run_id": "2026-05-19-qwen3-8b-dflash-b16-main",
  "decision_time_utc": "2026-05-19T00:00:00Z",
  "overall_decision": "implement_controller|implement_dynamic_vocab|implement_ssd_lite|implement_retrieval_suffix|implement_grammar_schema|stop_line",
  "ranked_next_projects": [
    {
      "name": "controller",
      "rank": 1,
      "decision": "continue",
      "modeled_gain_percent": 9.4,
      "confidence": "medium",
      "blocking_risks": ["wall_clock_noise", "category_regression"],
      "required_next_artifact": "controller_v0_online_ablation"
    }
  ],
  "kill_reasons": [
    {
      "name": "ssd_lite",
      "reason": "top4 outcome hit below threshold",
      "observed": 0.47,
      "threshold": 0.60
    }
  ],
  "thresholds": {
    "ssd_lite_top4_hit": 0.60,
    "dynamic_vocab_coverage_2048": 0.95,
    "controller_oracle_gain": 8.0,
    "retrieval_round_hit_rate": 0.20,
    "grammar_median_frontier": 512
  },
  "reproducibility": {
    "public_prompt_fraction": 0.75,
    "private_prompt_fraction": 0.25,
    "trace_contains_text": false,
    "trace_contains_token_ids": true
  }
}
```

---

# 8. Implementation shortcuts

## 8.1 Do not build full SSD-lite

For the first pass:

```text
Log accept length, rejection position, bonus token.
Train offline predictor.
Simulate branch-cache savings.
```

Only implement branch precomputation if the predictor clears the threshold.

## 8.2 Do not build dynamic vocab kernels first

First pass:

```text
Measure LM-head fraction.
Compute coverage curves.
Microbench indexed matmul with synthetic gathered vocab rows.
```

Only write real indexed-head integration if:

```text
coverage is high
AND LM-head is a measured bottleneck
AND indexed matmul wins in isolation
```

## 8.3 Simulate controller from one large-block run

Use DFlash block size 16 and simulate:

```text
block_size 1, 2, 4, 8, 16
```

You do not need to rerun the whole benchmark for each block size.

Run only a microbench to estimate draft cost per block size.

## 8.4 Use n-gram maps before suffix trees

For retrieval, start with:

```python
dict[hash(last_n_tokens)] -> list[next_32_token_spans]
```

This gives most of the first-order signal. Build a suffix tree only after the n-gram oracle shows real hit rate.

## 8.5 Shadow grammar only

For grammar:

```text
Do not constrain generation yet.
Only compute valid-token frontier and invalid draft positions.
```

This tells you whether grammar could help before you integrate constrained decoding into the speculative loop.

## 8.6 Do not store full logits

Store:

```text
top-32 IDs/logprobs
entropy scalar
top-1 probability
top-2 margin
logprob of actual draft token
```

Full logits will inflate traces and slow the run.

## 8.7 Use prompt-level train/test split

For SSD/controller models:

```text
train: 70% prompts
validation: 15% prompts
test: 15% prompts
```

Split by prompt, not by round. Round-level random splits will leak prompt behavior.

## 8.8 Keep private and public partitions separate

Report:

```text
public-only result
private-only result
combined result
```

The public-only result determines publishability. The private result determines Enoch operational value.

---

# Final recommendation

Enoch should run **one unified trace/oracle project first**, not directly implement any of the five branches.

Reason:

* DFlash is already the strongest local baseline.
* The five candidate branches depend on different hidden bottlenecks:

  * SSD-lite depends on predictable verification outcomes and nontrivial draft cost.
  * Dynamic vocab depends on LM-head bottleneck and high small-vocab coverage.
  * Controller depends on measurable static-policy waste.
  * Retrieval depends on repetition.
  * Grammar depends on small valid-token frontiers or invalid draft waste.
* A single DFlash b16 trace can evaluate all five with bounded runtime.
* Negative output is still useful: it identifies which speculative directions are not worth local engineering effort and gives hyperscaler researchers a reproducible trace/oracle methodology.

Recommended first command target:

```text
Run spec_trace_oracle_v0 on Qwen/Qwen3-8B + z-lab/Qwen3-8B-DFlash-b16,
384 generations,
~155k max new tokens,
DFlash block size 16,
temperatures 0.0 and 0.7,
with SSD/vocab/controller/retrieval/grammar probes enabled.
```

Then implement exactly one branch based on `.enoch/project_decision.json`.

[1]: https://arxiv.org/abs/2603.03251?utm_source=chatgpt.com "[2603.03251] Speculative Speculative Decoding"
[2]: https://github.com/z-lab/dflash "GitHub - z-lab/dflash: DFlash: Block Diffusion for Flash Speculative Decoding · GitHub"
[3]: https://arxiv.org/abs/2503.01840?utm_source=chatgpt.com "EAGLE-3: Scaling up Inference Acceleration of Large Language Models via Training-Time Test"
[4]: https://arxiv.org/abs/2501.10868?utm_source=chatgpt.com "Generating Structured Outputs from Language Models: Benchmark and Studies"
[5]: https://arxiv.org/abs/2602.13836?utm_source=chatgpt.com "Speculative Decoding with a Speculative Vocabulary"
[6]: https://arxiv.org/abs/2411.04975?utm_source=chatgpt.com "Extreme Speculative Decoding for Emerging AI Applications"
[7]: https://arxiv.org/html/2403.06988v1?utm_source=chatgpt.com "Guiding LLMs The Right Way: Fast, Non-Invasive ..."
