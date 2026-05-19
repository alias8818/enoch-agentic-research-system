# Promising signals backfill audit

Generated: `2026-05-19T17:06:07.490052+00:00`

This is a dry-run classification report. It does not export rows or change the companion repo.

## Summary

| Bucket | Count |
|---|---:|
| Total candidate rows | 162 |
| Export cleanly now | 92 |
| Missing required evidence/fields | 70 |
| Excluded because paper/corpus | 0 |
| Hard negative or stale | 0 |

## Backfill plan

1. Export rows in `export_cleanly_now` first; they already satisfy the deterministic public record contract.
2. Backfill rows in `missing_required_evidence_or_fields` only after source/evidence fields are recovered from control-plane or worker artifacts.
3. Leave `excluded_paper_or_corpus` out of the promising-signals repo; those belong to the paper/corpus lane.
4. Leave `hard_negative_or_stale` out unless a new deterministic decision record changes their status.

## Export cleanly now

| Project | Outcome | Issues |
|---|---|---|
| `1-bit-weights-with-fp16-residual-channels-80394161b338` | `useful_signal` |  |
| `additive-residual-codebook-for-1-58-bit-kv-cache-b4795df000ba` | `promising_if_scaled` |  |
| `anchor-gated-kv-compression-for-long-context-6e3650a20b17` | `useful_signal` |  |
| `anchor-gated-sparse-kv-cache-with-interpolated-eviction-a54888767f28` | `promising_if_scaled` |  |
| `anchor-indexed-kv-compression-with-exact-recall-positions-ab2f6cd34ec6` | `useful_signal` |  |
| `anchor-preserved-kv-compression-with-deterministic-markers-e7b017b702fb` | `promising_if_scaled` |  |
| `attention-aware-residual-codebooks-for-1-58-bit-kv-cache-3f1bc04709` | `promising_if_scaled` |  |
| `block-stochastic-quantized-optimizer-states-with-periodic-correction-8de8a5154b62` | `useful_signal` |  |
| `bounded-ablation-of-verifier-repaired-ledgers-on-small-mod-3dfb92907f` | `useful_signal` |  |
| `bounded-neural-volunteer-training-commit-reveal-validation-9946e055fc` | `promising_if_scaled` |  |
| `calibrated-entropy-plus-confidence-n-gram-router-across-co-e23bca791a` | `useful_signal` |  |
| `commit-reveal-gradient-validation-for-cheating-resistant-volunteer-training-10aad0bda5d9` | `useful_signal` |  |
| `commit-reveal-gradient-validation-for-cheating-resistant-volunteer-training-bdedf04df87d` | `promising_if_scaled` |  |
| `commit-reveal-gradient-validation-for-volunteer-distributed-training-7284e53de3a5` | `useful_signal` |  |
| `commit-reveal-gradient-validation-under-non-iid-neural-vol-426459ea98` | `useful_signal` |  |
| `commit-reveal-replay-lotteries-on-a-real-optimizer-trace-f367751cad` | `promising_if_scaled` |  |
| `commit-reveal-spot-check-gradient-verification-for-volunteer-training-c7bbf4bdc595` | `useful_signal` |  |
| `confidence-router-cascade-for-vram-reduction-ee2ba6c3c184` | `useful_signal` |  |
| `context-local-suffix-array-speculative-decoding-290e5a35ec78` | `useful_signal` |  |
| `cross-model-kv-cascade-router-with-affine-adapter-64f380dca440` | `useful_signal` |  |
| `deterministic-and-target-aware-bag-size-curricula-for-hard-f345c2cb43` | `promising_if_scaled` |  |
| `direct-agent-harness-evaluation-of-append-only-evidence-le-704935537c` | `promising_if_scaled` |  |
| `direct-confidence-quality-cascade-test-with-real-local-mod-520703164e` | `useful_signal` |  |
| `direct-federated-benchmark-for-hidden-canary-gradient-audi-aab4c9b92e` | `promising_if_scaled` |  |
| `direct-local-llm-entropy-gated-cascade-benchmark-f2df2707e8` | `promising_if_scaled` |  |
| `direct-serving-test-of-cpu-n-gram-drafting-for-code-contex-a360e35298` | `promising_if_scaled` |  |
| `direct-small-large-lm-entropy-cascade-evaluation-12393790f2` | `promising_if_scaled` |  |
| `direct-small-transformer-evaluation-of-2-bit-kv-residual-c-b8d32bd01c` | `promising_if_scaled` |  |
| `end-to-end-gpt-2-compressed-cache-decoding-validation-for-bc77f0facf` | `useful_signal` |  |
| `end-to-end-gpt-2-small-dynresact-perplexity-and-latency-pr-3a1baeb62b` | `useful_signal` |  |
| `end-to-end-perplexity-test-for-2-bit-outlier-channel-resid-85f1d9e9fb` | `promising_if_scaled` |  |
| `end-to-end-sampled-gradient-recomputation-for-volunteer-sp-0f3fe3b385` | `useful_signal` |  |
| `end-to-end-sgd-shard-lottery-validation-under-targeted-cor-659b2a05fd` | `useful_signal` |  |
| `entropy-gated-local-cascade-router-d0a9f5ce3010` | `promising_if_scaled` |  |
| `entropy-gated-local-model-cascade-e53ac0edbaa3` | `promising_if_scaled` |  |
| `equal-cost-adaptive-verifier-test-for-sparse-activation-re-abd908e4c4` | `useful_signal` |  |
| `exact-anchor-block-retrieval-via-compressed-memory-tokens-e8fd1a6fb95d` | `useful_signal` |  |
| `exact-anchor-kv-compression-via-sparse-landmark-pooling-9567f71bb992` | `useful_signal` |  |
| `exact-anchor-state-checkpoints-for-long-episode-agents-f63e4455279a` | `promising_if_scaled` |  |
| `field-ablated-merkle-trajectory-audits-on-stochastic-ppo-r-d06cb953f3` | `useful_signal` |  |
| `gpt-2-scale-token-superposition-pretraining-reproduction-ce453cf42b1f` | `promising_if_scaled` |  |
| `gradient-lottery-validation-for-volunteer-training-95065f6b3d3f` | `useful_signal` |  |
| `hidden-state-router-for-0-5b-to-3b-local-cascade-8405793743cf` | `promising_if_scaled` |  |
| `hierarchical-landmark-memory-with-bounded-o-sqrt-n-state-71d6a457f6b2` | `promising_if_scaled` |  |
| `hybrid-adam-with-spectral-second-moment-compression-8164ad3e08` | `useful_signal` |  |
| `independent-calibration-undertrained-proxy-gradient-verifi-1c467e6bea` | `useful_signal` |  |
| `kv-cache-prompt-suffix-lookahead-on-natural-long-context-c-6364cf9a9c` | `useful_signal` |  |
| `kv-cache-suffix-array-drafting-for-vram-free-speculative-decoding-503b4aedb46f` | `promising_if_scaled` |  |
| `learned-hierarchical-landmark-memory-on-structured-long-co-2088665316` | `promising_if_scaled` |  |
| `ledger-constrained-decoding-for-tool-truthfulness-in-1b-agents-bdf902b9d85e` | `promising_if_scaled` |  |
| `measure-real-kv-cache-layer-pipelined-early-exit-self-spec-c320042ad6` | `useful_signal` |  |
| `merkle-shard-commitments-for-data-poisoning-detection-486ee43d8a60` | `useful_signal` |  |
| `merkle-trajectory-ledger-to-detect-reward-hacking-in-local-ppo-agents-08438f0bd9f8` | `useful_signal` |  |
| `neural-chunk-commitment-gradient-validation-under-adaptive-735638b6db` | `useful_signal` |  |
| `outlier-channel-residual-for-2-bit-weights-2dc3ba49138c` | `promising_if_scaled` |  |
| `outlier-residual-extreme-quantization-with-principled-channel-split-f74f06ce6f54` | `useful_signal` |  |
| `parameter-matched-residual-channel-2-bit-gpt-proxy-with-pa-6568574932` | `promising_if_scaled` |  |
| `position-weighted-multi-hot-objective-for-token-superposition-24789cd22f88` | `promising_if_scaled` |  |
| `ppl-gated-cascade-without-direct-kv-reuse-a7b1bbb685` | `promising_if_scaled` |  |
| `ppl-gated-local-cascade-with-kv-handoff-92f25ad19b9a` | `promising_if_scaled` |  |
| `prompt-lookahead-suffix-array-speculative-decoding-8fb428b32e13` | `useful_signal` |  |
| `proof-of-useful-work-gradient-validation-for-volunteer-swarms-a1ad1c5709a9` | `useful_signal` |  |
| `real-kv-activation-test-for-exact-anchor-sparse-landmark-p-03f0f23aca` | `useful_signal` |  |
| `real-small-model-evidence-ledger-jury-benchmark-0ba0c258c3` | `promising_if_scaled` |  |
| `real-transformer-anchor-preserved-kv-cache-evaluation-fff3f43dd3` | `promising_if_scaled` |  |
| `real-transformer-validation-of-anchor-gated-kv-eviction-un-0d6b8b6de9` | `promising_if_scaled` |  |
| `residual-channel-1-58-bit-gpt-2-with-fp16-error-diffusion-10d18541d8ff` | `useful_signal` |  |
| `robust-3-bit-activation-weight-residual-split-validation-cf24b41197` | `useful_signal` |  |
| `robust-aggregation-for-low-cost-verifiable-gradient-lotter-5aa4c01151` | `useful_signal` |  |
| `rollback-ledger-for-tool-use-agents-d6033c25f3ec` | `useful_signal` |  |
| `rollback-ledger-with-tiny-learned-error-detector-560e1d9acda5` | `promising_if_scaled` |  |
| `second-moment-stabilization-for-blockwise-stochastic-int8-7ed4b8a6da` | `useful_signal` |  |
| `self-speculative-decoding-via-early-exit-and-shared-kv-cache-873b78e674fe` | `useful_signal` |  |
| `self-speculative-decoding-via-layer-early-exit-drafting-adecf224dc1a` | `useful_signal` |  |
| `self-speculative-decoding-via-layer-pipelined-early-exit-3a34fb6b1278` | `useful_signal` |  |
| `signed-observation-recorder-for-real-agent-evidence-ledger-873e746277` | `useful_signal` |  |
| `small-transformer-qa-test-for-exact-anchor-ledger-retrieva-30ed3725d5` | `useful_signal` |  |
| `sparse-activation-replay-for-byzantine-volunteer-gradient-verification-764c8c457dca` | `useful_signal` |  |
| `sparse-structured-residual-channels-for-1-bit-quantization-recovery-fcdc80f5e0f8` | `useful_signal` |  |
| `spectral-adam-low-rank-optimizer-state-compression-586a5411c2ed` | `useful_signal` |  |
| `spectral-residual-decomposition-for-sub-2bit-weight-quantization-5547c307a409` | `useful_signal` |  |
| `sqlite-wal-local-quorum-ledger-prototype-b1bdfc12b1` | `useful_signal` |  |
| `structured-compression-objective-for-exact-anchor-retrieva-10ca845b4c` | `useful_signal` |  |
| `structured-ledger-rejection-sampling-for-local-agents-75263160c1cb` | `promising_if_scaled` |  |
| `suffix-array-speculative-drafting-from-generation-history-eaa2278559d2` | `useful_signal` |  |
| `tamper-evident-agent-ledger-for-hallucination-detection-eff65c3bc538` | `useful_signal` |  |
| `tamper-evident-agent-ledger-via-inline-cryptographic-checksumming-a9735d105002` | `useful_signal` |  |
| `ternary-weights-plus-per-layer-residual-codebook-recovery-71052a960214` | `promising_if_scaled` |  |
| `tiered-exact-anchor-kv-cache-with-cross-layer-compression-7411950a6bc9` | `promising_if_scaled` |  |
| `trace-based-ledger-constrained-decoding-for-1b-tool-agents-8d68ea8865` | `promising_if_scaled` |  |
| `trainable-dual-memory-anchor-recall-against-parameter-matc-9ba5e67c38` | `promising_if_scaled` |  |
| `variance-guided-data-selection-for-tiny-lm-pretraining-3c3146778b0c` | `useful_signal` |  |

## Missing required evidence/fields

| Project | Outcome | Issues |
|---|---|---|
| `acceptance-aware-gpt-2-small-early-exit-heads-for-exact-se-bc1a42be2d` | `useful_signal` | sources:required |
| `activation-aware-calibration-for-static-residual-adapters-08e1f264dc` | `useful_signal` | sources:required |
| `adaptive-or-periodically-corrected-low-rank-adamw-for-smal-afbae3b446` | `useful_signal` | sources:required |
| `adaptive-rank-anchor-kv-compression-on-gpt-2-small-class-l-003174ac4a` | `useful_signal` | sources:required |
| `behavior-aware-learned-kv-residual-prediction-for-exact-an-b76f7664e0` | `promising_if_scaled` | sources:required |
| `blockwise-stabilized-4-bit-adam-second-moment-on-a-small-t-d75abbd657` | `promising_if_scaled` | sources:required |
| `bounded-full-scale-commit-reveal-replay-auditing-on-a-real-3eddb3740f` | `promising_if_scaled` | sources:required |
| `bounded-full-scale-memory-pressure-validation-for-streamed-6f56b891a0` | `promising_if_scaled` | sources:required |
| `bounded-scale-gap-validation-of-calibrated-ppl-gates-for-n-08c789374b` | `promising_if_scaled` | sources:required |
| `calibrated-evidence-ledger-jury-with-larger-real-data-cove-0937d49bc3` | `promising_if_scaled` | sources:required |
| `checkpointed-gpt-2-intermediate-kl-heads-for-actual-specul-9042abd5e4` | `useful_signal` | sources:required |
| `coverage-constrained-sampled-adamw-recomputation-on-the-sa-04a71608ba` | `useful_signal` | sources:required |
| `distribution-aware-calibration-for-residual-activation-ver-66be993511` | `useful_signal` | sources:required |
| `durable-restart-validation-for-anchored-langgraph-checkpoi-9d1f914464` | `useful_signal` | sources:required |
| `fused-packed-2-bit-residual-channel-projection-kernel-on-g-d75620eff6` | `promising_if_scaled` | sources:required |
| `generative-local-llm-confidence-cascade-with-actual-server-00a5434e21` | `promising_if_scaled` | sources:required |
| `gpt-2-small-inference-validation-of-key-addressed-anchorsl-2f16602be2` | `useful_signal` | sources:required |
| `gradient-dot-audits-for-label-flip-anomaly-detection-063cd69498` | `promising_if_scaled` | sources:required |
| `hierarchical-shrinkage-local-cascade-gates-for-selective-r-18b0ed1fac` | `useful_signal` | sources:required |
| `int4-kv-residual-window-validation-with-measured-memory-an-6c4762396d` | `promising_if_scaled` | sources:required |
| `integrated-commit-reveal-audit-on-a-real-gpt-2-small-train-44f22cfc92` | `promising_if_scaled` | sources:required |
| `langgraph-adapter-rollback-ledger-under-randomized-crash-a-b627e5b7ef` | `useful_signal` | sources:required |
| `layer-and-objective-sweep-for-gpt-2-self-speculative-inter-feb8826fcb` | `useful_signal` | sources:required |
| `layerwise-and-multi-layer-direct-fidelity-residual-substit-5e515aa9cc` | `promising_if_scaled` | sources:required |
| `live-agent-tool-path-signed-recorder-with-crash-and-concur-d3d8173e93` | `useful_signal` | sources:required |
| `live-tool-trace-contradiction-recovery-without-last-mentio-f02b02654c` | `promising_if_scaled` | sources:required |
| `long-context-copy-heavy-prompt-n-gram-speculative-decoding-9afd8b765d` | `promising_if_scaled` | sources:required |
| `mass-aware-exact-anchor-clustered-kv-cache-decoding-on-gpt-22c14bdcc3` | `useful_signal` | sources:required |
| `medium-confirmation-of-small-large-lm-entropy-cascade-rout-d1012a5de3` | `promising_if_scaled` | sources:required |
| `medium-direct-confirmation-of-uncertainty-routed-cascades-72a499b232` | `useful_signal` | sources:required |
| `medium-multi-corpus-cross-instance-evidence-verification-9ea0827de6` | `useful_signal` | sources:required |
| `medium-neural-shard-lottery-validation-under-adaptive-shar-ee7572f07e` | `useful_signal` | sources:required |
| `medium-real-kv-anchor-router-benchmark-73c2329123` | `promising_if_scaled` | sources:required |
| `medium-scale-commit-reveal-replay-auditing-on-a-larger-opt-dd9c25b0da` | `promising_if_scaled` | sources:required |
| `medium-validation-of-deployable-ppl-uncertainty-gates-for-05dff99f7d` | `promising_if_scaled` | sources:required |
| `multi-model-hakv-inference-fidelity-robustness-at-25--rete-563c210425` | `useful_signal` | sources:required |
| `naturalistic-copy-suffix-localization-without-explicit-quo-bc04d2807a` | `useful_signal` | sources:required |
| `neural-ppo-field-ablated-merkle-audit-reproduction-6ac380c201` | `useful_signal` | sources:required |
| `nonlinear-shared-gradient-proxy-verifier-confirmation-15238b296a` | `useful_signal` | sources:required |
| `optimized-exact-cache-path-for-gpt-2-intermediate-head-sel-0692caf722` | `useful_signal` | sources:required |
| `optimized-suffix-copy-speculative-decoding-across-corpora-ad6443df25` | `useful_signal` | sources:required |
| `packed-int2-kv-residual-window-validation-with-measured-me-c114b1bd71` | `promising_if_scaled` | sources:required |
| `per-layer-attention-only-versus-adaptive-hakv-retention-at-9f783e5b95` | `useful_signal` | sources:required |
| `practical-randomized-svd-hybrid-spectral-adamw-on-small-tr-e7c4eede14` | `useful_signal` | sources:required |
| `prefetch-aware-pytorch-dataloader-replay-state-for-multi-w-a94886129a` | `promising_if_scaled` | sources:required |
| `process-kill-rollback-ledger-validation-with-external-serv-9a2fc1f56f` | `useful_signal` | sources:required |
| `production-trace-strict-n-gram-drafting-cpu-serving-valida-6d3078dd22` | `promising_if_scaled` | sources:required |
| `real-agent-trace-replay-evidence-ledger-poisoning-validati-cd96859f9d` | `promising_if_scaled` | sources:required |
| `real-corpus-medium-validation-for-streamed-adam-moment-sto-3a0d2e995a` | `promising_if_scaled` | sources:required |
| `real-fl-validation-of-commit-reveal-volunteer-training-c9fdba9e03` | `promising_if_scaled` | sources:required |
| `real-lm-hidden-state-shuffled-error-validation-for-router-57eb325275` | `useful_signal` | sources:required |
| `real-report-validation-of-trace-specific-gains-in-multi-cl-afbbf95ada` | `promising_if_scaled` | sources:required |
| `real-small-lm-kv-trace-test-for-2-bit-residual-block-gates-f8490ab41d` | `useful_signal` | sources:required |
| `recorded-agent-tool-trace-contradiction-recovery-benchmark-ceac3cc2cf` | `promising_if_scaled` | sources:required |
| `residual-channel-preservation-on-real-bpe-tokenizations-6d45bd8b4c` | `useful_signal` | sources:required |
| `richer-calibration-for-entropy-routing-on-multiclass-casca-c34659b1bc` | `promising_if_scaled` | sources:required |
| `robust-commit-reveal-gradient-validation-with-public-refer-e07a20a294` | `useful_signal` | sources:required |
| `routing-knowledge-ablation-for-neural-shard-lottery-robust-79097af03f` | `useful_signal` | sources:required |
| `small-transformer-confirmation-for-hybrid-spectral-adam-a484f816b0` | `useful_signal` | sources:required |
| `small-transformer-validation-of-sqrt-stabilized-blockwise-c0007cb542` | `useful_signal` | sources:required |
| `streaming-storage-saving-dplr-floor-adam-versus-adam-and-a-414ba530a2` | `useful_signal` | sources:required |
| `strict-verifier-cpu-n-gram-drafting-serving-test-469c406314` | `promising_if_scaled` | sources:required |
| `tail-stabilized-causal-anchor-selection-for-real-kv-landma-ef313763fc` | `useful_signal` | sources:required |
| `token-level-gpt-2-latency-test-for-suffix-copy-speculative-4980023e0f` | `useful_signal` | sources:required |
| `trace-driven-paged-kv-anchor-cache-serving-benchmark-5d60334321` | `useful_signal` | sources:required |
| `train-real-auxiliary-exit-heads-for-early-exit-speculative-a72b6570f4` | `useful_signal` | sources:required |
| `uncertainty-gated-anchor-kv-eviction-across-real-lms-and-c-49749d6603` | `promising_if_scaled` | sources:required |
| `variable-length-pointer-copy-transformer-for-length-robust-62bc618d59` | `useful_signal` | sources:required |
| `vectorized-periodic-mass-aware-kv-clustering-budget-sweep-71f10f9e70` | `useful_signal` | sources:required |
| `zero-floor-or-percentile-scaled-sqrt-int8-adam-v-state-par-af0d5936b2` | `useful_signal` | sources:required |

## Excluded because paper/corpus

| Project | Outcome | Issues |
|---|---|---|
| _none_ |  |  |

## Hard negative or stale

| Project | Outcome | Issues |
|---|---|---|
| _none_ |  |  |

