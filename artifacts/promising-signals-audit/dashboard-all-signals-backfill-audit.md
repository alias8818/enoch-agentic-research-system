# Promising signals backfill audit

Generated: `2026-05-19T17:07:05.259816+00:00`

This is a dry-run classification report. It does not export rows or change the companion repo.

## Summary

| Bucket | Count |
|---|---:|
| Total candidate rows | 508 |
| Export cleanly now | 242 |
| Missing required evidence/fields | 266 |
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
| `1-bit-residual-channel-pretraining-for-gpt-2-small-class-e082079e4a3f` | `useful_signal` |  |
| `1-bit-weights-with-fp16-residual-channels-80394161b338` | `useful_signal` |  |
| `2-bit-kv-cache-with-per-head-residual-correction-for-long-context-7da3805285d2` | `useful_signal` |  |
| `activation-aware-learned-residual-channels-for-1-bit-recov-70ce4e2acc` | `useful_signal` |  |
| `activation-magnitude-residual-channel-preservation-for-sub-64eddc32c2` | `useful_signal` |  |
| `adaptive-cascade-router-for-latency-quality-pareto-on-10gb-341838c4456f` | `useful_signal` |  |
| `adaptive-exact-anchors-with-learned-cross-layer-kv-residua-ebc41d5055` | `useful_signal` |  |
| `adaptive-precision-residual-gates-for-2-bit-kv-cache-84a98257a7a3` | `useful_signal` |  |
| `additive-residual-codebook-for-1-58-bit-kv-cache-b4795df000ba` | `promising_if_scaled` |  |
| `adversarial-falsification-of-agent-evidence-ledgers-via-counterexample-mining-f57c8cb5e0e1` | `useful_signal` |  |
| `anchor-conditioned-kv-eviction-for-long-context-0475981f0673` | `useful_signal` |  |
| `anchor-exact-kv-compression-for-long-context-recall-1093d8eb655c` | `useful_signal` |  |
| `anchor-gated-kv-compression-for-long-context-6e3650a20b17` | `useful_signal` |  |
| `anchor-gated-kv-compression-with-exact-positional-retrieval-2578d1fa81f9` | `useful_signal` |  |
| `anchor-gated-sparse-kv-cache-with-interpolated-eviction-a54888767f28` | `promising_if_scaled` |  |
| `anchor-indexed-kv-compression-with-exact-recall-positions-ab2f6cd34ec6` | `useful_signal` |  |
| `anchor-preserved-kv-compression-with-deterministic-markers-e7b017b702fb` | `promising_if_scaled` |  |
| `anchor-preserved-kv-compression-with-entropy-gated-exact-retention-aa555ccfc2bb` | `useful_signal` |  |
| `anchor-preserved-low-rank-kv-compression-01a9ece04fee` | `useful_signal` |  |
| `anchored-hmac-checkpoints-in-a-real-agent-runtime-91aa182911` | `useful_signal` |  |
| `anchorslot-kv-compression-for-exact-long-context-retrieval-f4497b00ae17` | `useful_signal` |  |
| `append-only-evidence-ledger-for-sub-1b-agent-tool-use-hallucination-reduction-4024f83194b8` | `useful_signal` |  |
| `attention-aware-residual-codebooks-for-1-58-bit-kv-cache-3f1bc04709` | `promising_if_scaled` |  |
| `attention-mass-selected-fp16-exceptions-for-int3-kv-cache-1372b9be4a` | `useful_signal` |  |
| `block-stochastic-quantized-optimizer-states-with-periodic-correction-8de8a5154b62` | `useful_signal` |  |
| `blockwise-8-bit-adam-for-gpt-2-small-pretraining-under-4gb-vram-a41d6660b0a8` | `useful_signal` |  |
| `bounded-ablation-of-verifier-repaired-ledgers-on-small-mod-3dfb92907f` | `useful_signal` |  |
| `bounded-neural-volunteer-training-commit-reveal-validation-9946e055fc` | `promising_if_scaled` |  |
| `calibrated-auxiliary-early-exit-draft-for-speculative-deco-f71fb85632` | `useful_signal` |  |
| `calibrated-entropy-plus-confidence-n-gram-router-across-co-e23bca791a` | `useful_signal` |  |
| `calibration-trained-ternary-residual-channels-for-gpt-2-sm-59c820e71a` | `useful_signal` |  |
| `canary-gradient-probes-for-volunteer-cheating-detection-ddd8e03afd4d` | `useful_signal` |  |
| `challenge-response-forward-pass-for-volunteer-training-12ad399ab207` | `useful_signal` |  |
| `cheap-confidence-router-for-qwen2-5-coder-1-5b-7b-cascade-a460e154bb` | `useful_signal` |  |
| `commit-reveal-gradient-validation-for-cheating-resistant-volunteer-training-10aad0bda5d9` | `useful_signal` |  |
| `commit-reveal-gradient-validation-for-cheating-resistant-volunteer-training-bdedf04df87d` | `promising_if_scaled` |  |
| `commit-reveal-gradient-validation-for-volunteer-distributed-training-7284e53de3a5` | `useful_signal` |  |
| `commit-reveal-gradient-validation-under-non-iid-neural-vol-426459ea98` | `useful_signal` |  |
| `commit-reveal-replay-lotteries-on-a-real-optimizer-trace-f367751cad` | `promising_if_scaled` |  |
| `commit-reveal-shard-lottery-for-volunteer-gradient-validation-385eda026ea7` | `useful_signal` |  |
| `commit-reveal-spot-check-gradient-verification-for-volunteer-training-c7bbf4bdc595` | `useful_signal` |  |
| `committee-lottery-audits-for-volunteer-gradient-integrity-0f0bcb35374d` | `useful_signal` |  |
| `confidence-gated-cascade-with-kv-prefix-reuse-for-local-serving-abc42e4dcc77` | `useful_signal` |  |
| `confidence-gated-local-cascade-router-5f78a44d1f` | `useful_signal` |  |
| `confidence-router-cascade-for-vram-reduction-ee2ba6c3c184` | `useful_signal` |  |
| `content-aware-anchor-kv-compression-for-approximate-redund-9dc0d3705e` | `useful_signal` |  |
| `context-local-suffix-array-speculative-decoding-290e5a35ec78` | `useful_signal` |  |
| `context-suffix-speculative-decoding-without-any-draft-model-cb96b6c2ff11` | `useful_signal` |  |
| `counterexample-mining-on-realistic-agent-evidence-ledgers-b4d46ca0c6` | `useful_signal` |  |
| `coverage-constrained-variance-selection-on-real-tiny-lm-te-e88a0676c3` | `useful_signal` |  |
| `cpu-ngram-context-draft-decoding-cd3d09a0093d` | `useful_signal` |  |
| `cross-instance-evidence-verification-7c114bf77ca0` | `useful_signal` |  |
| `cross-model-kv-cascade-router-with-affine-adapter-64f380dca440` | `useful_signal` |  |
| `cryptographic-evidence-ledger-for-agent-action-provenance-2f707b2ec46f` | `useful_signal` |  |
| `curriculum-length-progressive-data-selection-81ef6a727b81` | `useful_signal` |  |
| `deterministic-and-target-aware-bag-size-curricula-for-hard-f345c2cb43` | `promising_if_scaled` |  |
| `deterministic-replay-lotteries-for-volunteer-gradient-auditing-7dfd689f8b10` | `useful_signal` |  |
| `diagonal-plus-low-rank-nonnegative-adam-second-moments-wit-a5b08cf9e3` | `useful_signal` |  |
| `direct-agent-harness-evaluation-of-append-only-evidence-le-704935537c` | `promising_if_scaled` |  |
| `direct-anchorslot-kv-cache-test-in-a-small-transformer-fcd3b91f3d` | `useful_signal` |  |
| `direct-confidence-quality-cascade-test-with-real-local-mod-520703164e` | `useful_signal` |  |
| `direct-federated-benchmark-for-hidden-canary-gradient-audi-aab4c9b92e` | `promising_if_scaled` |  |
| `direct-kv-eviction-generation-test-for-draft-scored-cascad-429543f9ee` | `useful_signal` |  |
| `direct-llm-agent-contradiction-recovery-benchmark-eeb1daa2d8` | `useful_signal` |  |
| `direct-local-llm-entropy-gated-cascade-benchmark-f2df2707e8` | `promising_if_scaled` |  |
| `direct-local-neural-validation-of-uncertainty-routed-two-t-515773c913` | `useful_signal` |  |
| `direct-serving-test-of-cpu-n-gram-drafting-for-code-contex-a360e35298` | `promising_if_scaled` |  |
| `direct-small-large-lm-entropy-cascade-evaluation-12393790f2` | `promising_if_scaled` |  |
| `direct-small-transformer-evaluation-of-2-bit-kv-residual-c-b8d32bd01c` | `promising_if_scaled` |  |
| `direct-trace-audit-benchmark-for-structured-evidence-ledge-e596f42d07` | `useful_signal` |  |
| `disk-backed-evidence-ledger-rollback-versus-practical-snap-2ab253a70f` | `useful_signal` |  |
| `distribution-preserving-gradient-diversity-coresets-on-rea-0781d4adb5` | `useful_signal` |  |
| `draft-scored-kv-eviction-cascade-13e63fb1013c` | `useful_signal` |  |
| `dual-memory-hierarchical-state-with-exact-anchor-recall-563dc565acb3` | `useful_signal` |  |
| `durable-rollback-ledger-for-real-tool-adapters-under-crash-7d5a4300db` | `useful_signal` |  |
| `dynresact-dynamic-outlier-residual-channels-for-4-bit-activations-4552506ca304` | `useful_signal` |  |
| `embedding-diversity-reservoir-sampling-for-tiny-pretraining-data-selection-ead988174539` | `useful_signal` |  |
| `end-to-end-gpt-2-compressed-cache-decoding-validation-for-bc77f0facf` | `useful_signal` |  |
| `end-to-end-gpt-2-small-dynresact-perplexity-and-latency-pr-3a1baeb62b` | `useful_signal` |  |
| `end-to-end-perplexity-test-for-2-bit-outlier-channel-resid-85f1d9e9fb` | `promising_if_scaled` |  |
| `end-to-end-sampled-gradient-recomputation-for-volunteer-sp-0f3fe3b385` | `useful_signal` |  |
| `end-to-end-sgd-shard-lottery-validation-under-targeted-cor-659b2a05fd` | `useful_signal` |  |
| `enforced-evidence-ledger-validator-for-sub-1b-tool-use-ans-6a220ac83f` | `useful_signal` |  |
| `entropy-arbitrated-speculative-router-with-n-gram-fallback-9016e1b6d614` | `useful_signal` |  |
| `entropy-gated-local-cascade-router-d0a9f5ce3010` | `promising_if_scaled` |  |
| `entropy-gated-local-model-cascade-e53ac0edbaa3` | `promising_if_scaled` |  |
| `entropy-routed-two-tier-local-cascade-9039a28c21f0` | `useful_signal` |  |
| `equal-cost-adaptive-verifier-test-for-sparse-activation-re-abd908e4c4` | `useful_signal` |  |
| `evidence-audit-reward-on-real-tool-agent-traces-c31c613762` | `useful_signal` |  |
| `evidence-ledger-auditor-on-labeled-rag-or-agent-traces-c55c925359` | `useful_signal` |  |
| `evidence-ledger-for-small-agent-tool-calls-8a46fc204841` | `useful_signal` |  |
| `evidenceledgertoolhallucination-68bf0a21e3b8` | `useful_signal` |  |
| `exact-anchor-block-retrieval-via-compressed-memory-tokens-e8fd1a6fb95d` | `useful_signal` |  |
| `exact-anchor-checkpointing-in-a-real-long-episode-agent-ru-b3338a9490` | `useful_signal` |  |
| `exact-anchor-kv-cache-compression-via-tiered-summarization-32a35f931905` | `useful_signal` |  |
| `exact-anchor-kv-compression-via-sparse-landmark-pooling-9567f71bb992` | `useful_signal` |  |
| `exact-anchor-kv-saliency-gating-with-clustered-non-anchor-compression-d2462d72c7d3` | `useful_signal` |  |
| `exact-anchor-ledger-for-compressed-agent-episodic-memory-880ec5c31eee` | `useful_signal` |  |
| `exact-anchor-ledger-on-real-agent-traces-with-llm-compress-97250787a1` | `useful_signal` |  |
| `exact-anchor-state-checkpoints-for-long-episode-agents-f63e4455279a` | `promising_if_scaled` |  |
| `exact-kv-cache-context-suffix-verification-on-standard-tex-6b19508496` | `useful_signal` |  |
| `exact-token-transformer-test-of-quality-weighted-embedding-f8de11619d` | `useful_signal` |  |
| `executable-agent-validation-of-evidence-ledgers-under-cali-f2ff0f6718` | `useful_signal` |  |
| `field-ablated-merkle-trajectory-audits-on-stochastic-ppo-r-d06cb953f3` | `useful_signal` |  |
| `gpt-2-scale-token-superposition-pretraining-reproduction-ce453cf42b1f` | `promising_if_scaled` |  |
| `gradient-coreset-tiny-pretraining-954ea4314cd5` | `useful_signal` |  |
| `gradient-informed-residual-channel-preservation-for-1-58-bit-quantization-7b3e6b413461` | `useful_signal` |  |
| `gradient-lottery-validation-for-volunteer-training-95065f6b3d3f` | `useful_signal` |  |
| `hash-chain-evidence-ledger-for-agent-self-verification-0697af8d6d59` | `useful_signal` |  |
| `hessian-trace-residual-channel-preservation-for-sub-2bit-quantization-3664c59792af` | `useful_signal` |  |
| `hidden-state-cluster-router-for-local-specialists-a134afb96043` | `useful_signal` |  |
| `hidden-state-router-for-0-5b-to-3b-local-cascade-8405793743cf` | `promising_if_scaled` |  |
| `hierarchical-anchor-kv-cache-with-tiered-compression-3393410f60ab` | `useful_signal` |  |
| `hierarchical-landmark-memory-with-bounded-o-sqrt-n-state-71d6a457f6b2` | `promising_if_scaled` |  |
| `hierarchical-memory-tokens-for-long-context-with-exact-anchor-ledger-8926a3c04282` | `useful_signal` |  |
| `home-quorum-ledger-for-small-agent-swarms-16bf644875c9` | `useful_signal` |  |
| `hybrid-adam-with-spectral-second-moment-compression-8164ad3e08` | `useful_signal` |  |
| `hybrid-low-rank-first-moment-with-diagonal-second-moment-r-da1ee9f5fe` | `useful_signal` |  |
| `in-context-n-gram-speculative-decoding-without-draft-model-vram-5217fe32082a` | `useful_signal` |  |
| `incremental-merkle-kv-ledger-on-real-agent-traces-663a492842` | `useful_signal` |  |
| `independent-calibration-undertrained-proxy-gradient-verifi-1c467e6bea` | `useful_signal` |  |
| `kv-cache-aware-context-n-gram-drafting-on-modern-long-cont-bfd9174b02` | `useful_signal` |  |
| `kv-cache-benchmark-for-in-context-n-gram-speculative-decod-4aaa12c32d` | `useful_signal` |  |
| `kv-cache-int3-with-fp16-residual-window-b9e2348ca149` | `useful_signal` |  |
| `kv-cache-offload-router-for-multi-turn-local-serving-639041a0dcc9` | `useful_signal` |  |
| `kv-cache-prompt-suffix-lookahead-on-natural-long-context-c-6364cf9a9c` | `useful_signal` |  |
| `kv-cache-suffix-array-drafting-for-vram-free-speculative-decoding-503b4aedb46f` | `promising_if_scaled` |  |
| `kv-cache-suffix-tree-speculative-decoding-dd2b477dffaa` | `useful_signal` |  |
| `learned-anchor-router-for-exact-kv-retrieval-edc371259c` | `useful_signal` |  |
| `learned-hierarchical-landmark-memory-on-structured-long-co-2088665316` | `promising_if_scaled` |  |
| `learned-reuse-prediction-for-kv-cache-offload-admission-4d483f575e` | `useful_signal` |  |
| `ledger-constrained-decoding-for-tool-truthfulness-in-1b-agents-bdf902b9d85e` | `promising_if_scaled` |  |
| `live-tool-trace-evidence-ledger-hallucination-test-33c9e965a2` | `useful_signal` |  |
| `local-agent-evidence-ledger-with-cryptographic-task-provenance-f5ba7e47f3f2` | `useful_signal` |  |
| `lora-early-exit-speculative-decoding-bdf39a1e422b` | `useful_signal` |  |
| `lottery-gradient-audits-on-non-iid-federated-benchmarks-d69ad20f01` | `useful_signal` |  |
| `low-bit-block-residual-gates-for-2-bit-kv-cache-7b04369b80` | `useful_signal` |  |
| `low-rank-adam-optimizer-states-for-tiny-vram-training-9a16be688a20` | `useful_signal` |  |
| `low-rank-factored-adam-states-with-adaptive-rank-selection-fbfbd0edbec7` | `useful_signal` |  |
| `low-rank-residual-channels-for-sub-2-bit-weight-quantization-9d2dbe9c0188` | `useful_signal` |  |
| `measure-real-kv-cache-layer-pipelined-early-exit-self-spec-c320042ad6` | `useful_signal` |  |
| `medium-decode-quality-validation-for-anchor-preserved-low-9e00fc5c08` | `useful_signal` |  |
| `merkle-shard-commitments-for-data-poisoning-detection-486ee43d8a60` | `useful_signal` |  |
| `merkle-trajectory-ledger-to-detect-reward-hacking-in-local-ppo-agents-08438f0bd9f8` | `useful_signal` |  |
| `merkleized-kv-ledger-for-local-agent-integrity-86296c8425e9` | `useful_signal` |  |
| `multi-anchor-exactness-under-restricted-retrieval-queries-487403b40e` | `useful_signal` |  |
| `mutable-state-rollback-via-evidence-ledger-snapshots-2d404a46c6ec` | `useful_signal` |  |
| `natural-language-agent-benchmark-for-evidence-ledger-rollb-a18e2d5755` | `useful_signal` |  |
| `neural-chunk-commitment-gradient-validation-under-adaptive-735638b6db` | `useful_signal` |  |
| `noise-robust-gradient-lottery-for-volunteer-selection-86515f50eb` | `useful_signal` |  |
| `online-suffix-history-drafter-in-a-real-speculative-decodi-6c8536a3c2` | `useful_signal` |  |
| `optimized-suffix-copy-speculative-decoding-on-repetitive-r-9772305176` | `useful_signal` |  |
| `outlier-channel-residual-for-2-bit-weights-2dc3ba49138c` | `promising_if_scaled` |  |
| `outlier-residual-extreme-quantization-with-principled-channel-split-f74f06ce6f54` | `useful_signal` |  |
| `parameter-matched-residual-channel-2-bit-gpt-proxy-with-pa-6568574932` | `promising_if_scaled` |  |
| `paraphrased-llm-agent-memory-grounding-benchmark-8e4fcaa0b9` | `useful_signal` |  |
| `per-seed-noninferiority-test-for-confidence-router-cascade-2a5353e1a8` | `useful_signal` |  |
| `position-weighted-multi-hot-objective-for-token-superposition-24789cd22f88` | `promising_if_scaled` |  |
| `ppl-gated-cascade-without-direct-kv-reuse-a7b1bbb685` | `promising_if_scaled` |  |
| `ppl-gated-local-cascade-with-kv-handoff-92f25ad19b9a` | `promising_if_scaled` |  |
| `programmatic-isolated-ledger-on-real-multi-turn-tool-use-t-ca0d2c557e` | `useful_signal` |  |
| `prompt-complexity-router-for-local-model-cascades-f709678185e6` | `useful_signal` |  |
| `prompt-derived-suffix-array-speculation-f9881c3f20d0` | `useful_signal` |  |
| `prompt-lookahead-suffix-array-speculative-decoding-8fb428b32e13` | `useful_signal` |  |
| `proof-of-useful-work-gradient-validation-for-volunteer-swarms-a1ad1c5709a9` | `useful_signal` |  |
| `proxy-model-gradient-alignment-checks-for-volunteer-verification-64faedf9ba57` | `useful_signal` |  |
| `real-agent-evidence-bound-ledger-hallucination-audit-15a45b1385` | `useful_signal` |  |
| `real-agent-provenance-ledger-integration-and-robustness-be-0c7f3a1d75` | `useful_signal` |  |
| `real-corpus-cross-instance-evidence-verification-81ee601954` | `useful_signal` |  |
| `real-kv-activation-test-for-exact-anchor-sparse-landmark-p-03f0f23aca` | `useful_signal` |  |
| `real-kv-anchor-selection-for-long-context-recall-6b026f5518` | `useful_signal` |  |
| `real-llm-trace-validation-for-exact-kv-cache-suffix-drafti-c464a99207` | `useful_signal` |  |
| `real-lm-confidence-gated-anchor-kv-eviction-cc5be8c44e` | `useful_signal` |  |
| `real-model-hakv-inference-fidelity-on-small-pretrained-tra-d8a4514144` | `useful_signal` |  |
| `real-runtime-signed-provenance-ledger-evaluation-for-agent-f56187a255` | `useful_signal` |  |
| `real-small-model-evidence-ledger-jury-benchmark-0ba0c258c3` | `promising_if_scaled` |  |
| `real-text-flop-matched-length-curriculum-for-gpt-2-small-c-81bbe3db88` | `useful_signal` |  |
| `real-token-gpt-2-small-4-gib-blockwise-adamw-validation-bcd8476f2b` | `useful_signal` |  |
| `real-trace-evidence-ledger-evaluation-for-tool-use-agents-a583987517` | `useful_signal` |  |
| `real-transformer-anchor-preserved-kv-cache-evaluation-fff3f43dd3` | `promising_if_scaled` |  |
| `real-transformer-validation-of-anchor-gated-kv-eviction-un-0d6b8b6de9` | `promising_if_scaled` |  |
| `redundant-small-agent-jury-with-evidence-ledgers-b9ea9ef9d440` | `useful_signal` |  |
| `repeated-hidden-validation-for-multi-step-volunteer-gradie-74b77e99c3` | `useful_signal` |  |
| `rerank-attention-trace-successor-candidates-for-speculativ-c95d7d1685` | `useful_signal` |  |
| `residual-calibrated-kv-adapter-with-acceptance-router-f7d9a81091` | `useful_signal` |  |
| `residual-channel-1-58-bit-gpt-2-with-fp16-error-diffusion-10d18541d8ff` | `useful_signal` |  |
| `residual-channel-2-bit-gpt-2-small-pretraining-36993888df3a` | `useful_signal` |  |
| `residual-preserving-1-bit-bottleneck-with-dense-bypass-gat-523376c000` | `useful_signal` |  |
| `residual-rank-and-initialization-ablation-for-ternary-gpt-8ce25888d5` | `useful_signal` |  |
| `residual-soft-hidden-state-router-for-local-lm-specialists-46a55506cc` | `useful_signal` |  |
| `residualfp-channels-in-a-tiny-transformer-language-model-deadf0804b` | `useful_signal` |  |
| `residualfp-extreme-1-bit-weights-with-principled-fp16-residual-channels-eb9b28f112e3` | `useful_signal` |  |
| `retrievalgroundedagentmemory-35aeea5b7ed9` | `useful_signal` |  |
| `robust-3-bit-activation-weight-residual-split-validation-cf24b41197` | `useful_signal` |  |
| `robust-aggregation-for-low-cost-verifiable-gradient-lotter-5aa4c01151` | `useful_signal` |  |
| `rollback-ledger-for-tool-use-agents-d6033c25f3ec` | `useful_signal` |  |
| `rollback-ledger-with-tiny-learned-error-detector-560e1d9acda5` | `promising_if_scaled` |  |
| `second-moment-stabilization-for-blockwise-stochastic-int8-7ed4b8a6da` | `useful_signal` |  |
| `self-correcting-ledger-for-sub-3b-agent-reasoning-9768cc0647f2` | `useful_signal` |  |
| `self-speculative-decoding-via-early-exit-and-shared-kv-cache-873b78e674fe` | `useful_signal` |  |
| `self-speculative-decoding-via-layer-early-exit-drafting-adecf224dc1a` | `useful_signal` |  |
| `self-speculative-decoding-via-layer-pipelined-early-exit-3a34fb6b1278` | `useful_signal` |  |
| `shared-weight-early-exit-speculative-decoding-7ad97d5cfa22` | `useful_signal` |  |
| `signed-observation-recorder-for-real-agent-evidence-ledger-873e746277` | `useful_signal` |  |
| `signed-shard-commitments-plus-semantic-scanner-for-pre-tra-6fd21fc80e` | `useful_signal` |  |
| `small-lm-direct-kv-intervention-for-exact-anchors-plus-log-98b1dc3c48` | `useful_signal` |  |
| `small-lm-ledger-grounded-react-with-non-oracle-source-chec-7a6ac865ed` | `useful_signal` |  |
| `small-model-kv-cache-suffix-drafting-latency-test-2316475335` | `useful_signal` |  |
| `small-transformer-anchor-indexed-kv-cache-evaluation-3f4864c38c` | `useful_signal` |  |
| `small-transformer-kv-trace-replay-for-entropy-gated-exact-882d894cb9` | `useful_signal` |  |
| `small-transformer-perplexity-test-for-gradient-informed-re-53132be3e8` | `useful_signal` |  |
| `small-transformer-qa-test-for-exact-anchor-ledger-retrieva-30ed3725d5` | `useful_signal` |  |
| `sparse-activation-replay-for-byzantine-volunteer-gradient-verification-764c8c457dca` | `useful_signal` |  |
| `sparse-structured-residual-channels-for-1-bit-quantization-recovery-fcdc80f5e0f8` | `useful_signal` |  |
| `spectral-adam-low-rank-optimizer-state-compression-586a5411c2ed` | `useful_signal` |  |
| `spectral-residual-decomposition-for-sub-2bit-weight-quantization-5547c307a409` | `useful_signal` |  |
| `sqlite-wal-local-quorum-ledger-prototype-b1bdfc12b1` | `useful_signal` |  |
| `storage-matched-residual-channel-binary-transformer-ablati-65f8861a0b` | `useful_signal` |  |
| `streaming-low-memory-adam-moments-on-a-small-language-mode-306e86668c` | `useful_signal` |  |
| `structured-compression-objective-for-exact-anchor-retrieva-10ca845b4c` | `useful_signal` |  |
| `structured-evidence-ledger-for-tool-use-agents-851634d693f8` | `useful_signal` |  |
| `structured-evidence-ledger-reduces-hallucinated-tool-calls-in-small-agents-417a2250bb0c` | `useful_signal` |  |
| `structured-ledger-rejection-sampling-for-local-agents-75263160c1cb` | `promising_if_scaled` |  |
| `suffix-array-speculative-drafting-from-generation-history-eaa2278559d2` | `useful_signal` |  |
| `tamper-evident-agent-ledger-for-hallucination-detection-eff65c3bc538` | `useful_signal` |  |
| `tamper-evident-agent-ledger-via-inline-cryptographic-checksumming-a9735d105002` | `useful_signal` |  |
| `ternary-kv-cache-with-residual-error-feedback-for-long-context-c1c50fcb5949` | `useful_signal` |  |
| `ternary-weights-plus-per-layer-residual-codebook-recovery-71052a960214` | `promising_if_scaled` |  |
| `tiered-exact-anchor-kv-cache-with-cross-layer-compression-7411950a6bc9` | `promising_if_scaled` |  |
| `tiny-auditor-evidence-ledger-flags-reduce-agent-hallucinations-e5dcae51d722` | `useful_signal` |  |
| `tiny-prompt-router-for-local-1-5b-7b-cascade-9825621b040e` | `useful_signal` |  |
| `token-entropy-routed-speculative-decoding-a47708aa33a1` | `useful_signal` |  |
| `token-level-verifier-test-for-prompt-local-copy-speculatio-2c6ef887fd` | `useful_signal` |  |
| `token-superposition-for-long-context-anchor-compression-2e427b5fb840` | `useful_signal` |  |
| `tool-use-ledger-cuts-1b-agent-hallucinations-0bf8f8438dcf` | `useful_signal` |  |
| `trace-based-ledger-constrained-decoding-for-1b-tool-agents-8d68ea8865` | `promising_if_scaled` |  |
| `trace-replay-validation-of-structured-ledger-rejection-sam-d667538718` | `useful_signal` |  |
| `train-a-calibrated-gpt-2-intermediate-head-for-self-specul-ab7b7bb3b5` | `useful_signal` |  |
| `train-gpt-2-small-early-exit-heads-for-exact-self-speculat-b13407a3ce` | `useful_signal` |  |
| `trainable-dual-memory-anchor-recall-against-parameter-matc-9ba5e67c38` | `promising_if_scaled` |  |
| `variance-guided-data-selection-for-tiny-lm-pretraining-3c3146778b0c` | `useful_signal` |  |
| `verifiable-gradient-lottery-for-home-volunteer-training-ceaa3f86f272` | `useful_signal` |  |

## Missing required evidence/fields

| Project | Outcome | Issues |
|---|---|---|
| `4-gb-capped-rank-0-factored-optimizer-validation-96f718707f` | `useful_signal` | sources:required |
| `acceptance-aware-gpt-2-small-early-exit-heads-for-exact-se-bc1a42be2d` | `useful_signal` | sources:required |
| `activation-aware-calibration-for-static-residual-adapters-08e1f264dc` | `useful_signal` | sources:required |
| `activation-selected-residual-channels-with-error-aware-2-b-ad5a87cb53` | `useful_signal` | sources:required |
| `actual-head-identity-plus-recency-kv-gating-on-gpt-2-small-2bacb1c6e5` | `useful_signal` | sources:required |
| `adaptive-or-periodically-corrected-low-rank-adamw-for-smal-afbae3b446` | `useful_signal` | sources:required |
| `adaptive-rank-anchor-kv-compression-on-gpt-2-small-class-l-003174ac4a` | `useful_signal` | sources:required |
| `adaptive-training-loop-validation-for-conditional-lottery-e6bb1c9086` | `useful_signal` | sources:required |
| `adversarial-persistence-test-for-incremental-merkle-kv-age-e2048a7490` | `useful_signal` | sources:required |
| `async-or-host-resident-streamed-adamw-backend-in-a-real-tr-5535bfa367` | `useful_signal` | sources:required |
| `batched-larger-model-evidence-ledger-counterexample-sweep-ccaf21822f` | `useful_signal` | sources:required |
| `behavior-aware-learned-kv-residual-prediction-for-exact-an-b76f7664e0` | `promising_if_scaled` | sources:required |
| `blinded-multi-agent-evidence-ledger-counterexample-benchma-eed79744df` | `useful_signal` | sources:required |
| `block-aligned-learned-commitment-masks-for-real-sparse-att-fad58349e8` | `useful_signal` | sources:required |
| `blockwise-stabilized-4-bit-adam-second-moment-on-a-small-t-d75abbd657` | `promising_if_scaled` | sources:required |
| `bounded-full-scale-commit-reveal-replay-auditing-on-a-real-3eddb3740f` | `promising_if_scaled` | sources:required |
| `bounded-full-scale-memory-pressure-validation-for-streamed-6f56b891a0` | `promising_if_scaled` | sources:required |
| `bounded-full-scale-validation-of-nonzero-floor-4-bit-adam-2d840742e7` | `useful_signal` | sources:required |
| `bounded-production-style-strict-n-gram-drafting-cpu-servin-4ef349b27f` | `useful_signal` | sources:required |
| `bounded-scale-gap-validation-of-calibrated-ppl-gates-for-n-08c789374b` | `promising_if_scaled` | sources:required |
| `calibrated-confidence-gated-local-llm-cascade-with-held-ou-b689674c75` | `useful_signal` | sources:required |
| `calibrated-confidence-gates-for-stable-local-cascade-routi-4973719f64` | `useful_signal` | sources:required |
| `calibrated-evidence-ledger-jury-with-larger-real-data-cove-0937d49bc3` | `promising_if_scaled` | sources:required |
| `calibrated-logprob-routing-with-a-stronger-qwen2-5-coder-f-cf6506eb83` | `useful_signal` | sources:required |
| `calibrated-soft-source-diversity-for-cross-corpus-claim-ve-908672b271` | `useful_signal` | sources:required |
| `calibrated-top-k-qwed-interpolation-on-a-second-real-corpu-658f7a5b78` | `useful_signal` | sources:required |
| `calibration-trained-ternary-low-rank-residual-repair-for-g-0e07829031` | `useful_signal` | sources:required |
| `causal-non-oracle-anchor-selection-for-real-kv-landmark-po-09956cac81` | `useful_signal` | sources:required |
| `cheap-ranker-for-cache-aware-n-gram-candidate-selection-26a468c4ec` | `useful_signal` | sources:required |
| `checkpointed-gpt-2-intermediate-kl-heads-for-actual-specul-9042abd5e4` | `useful_signal` | sources:required |
| `cifar-10-calibrated-uncertainty-routed-cascades-with-laten-e93d3deda8` | `useful_signal` | sources:required |
| `claim-ledger-audit-with-strong-independent-nli-verificatio-1b04378348` | `useful_signal` | sources:required |
| `concurrent-atomic-rollback-ledger-recovery-under-external-f4ccb768a5` | `useful_signal` | sources:required |
| `consistency-forced-verifier-repaired-ledger-state-tracking-e378de737a` | `useful_signal` | sources:required |
| `constrained-model-authored-evidence-ledgers-for-sub-1b-qa-9b15f7fcd3` | `useful_signal` | sources:required |
| `constrained-span-candidate-evidence-ledgers-for-sub-1b-qa-41c6554697` | `useful_signal` | sources:required |
| `controlled-residualfp-channel-ablations-in-a-longer-tiny-l-d79bfcfb7c` | `useful_signal` | sources:required |
| `controller-integrated-postgres-langgraph-hard-cutover-faul-77a07dc1a4` | `useful_signal` | sources:required |
| `cost-aware-frozen-confidence-router-with-measured-overhead-787a704188` | `useful_signal` | sources:required |
| `cost-matched-robust-lottery-versus-robust-top-k-at-boundar-ac22ab74d3` | `useful_signal` | sources:required |
| `coverage-constrained-sampled-adamw-recomputation-on-the-sa-04a71608ba` | `useful_signal` | sources:required |
| `cross-device-adamw-sampled-gradient-recomputation-on-a-sma-9de0074913` | `useful_signal` | sources:required |
| `deployment-faithful-witness-gossip-replay-for-non-cancelab-d97c30da6c` | `useful_signal` | sources:required |
| `depth-4-robustness-validation-of-top-k-qwed-interpolation-dc1d13dfd0` | `useful_signal` | sources:required |
| `direct-llm-ledger-trace-replay-validation-8b9e7ec7a2` | `useful_signal` | sources:required |
| `distribution-aware-calibration-for-residual-activation-ver-66be993511` | `useful_signal` | sources:required |
| `durable-concurrent-agent-runtime-provenance-ledger-integra-649a141b48` | `useful_signal` | sources:required |
| `durable-restart-validation-for-anchored-langgraph-checkpoi-9d1f914464` | `useful_signal` | sources:required |
| `efficient-hybrid-low-rank-adamw-update-for-small-lm-traini-c8a1d93ce9` | `useful_signal` | sources:required |
| `end-to-end-adaptive-ticket-routing-for-conditional-lottery-568f77571d` | `useful_signal` | sources:required |
| `end-to-end-anchor-kv-cache-hit-rate-and-amortization-bench-ca58c29fb4` | `useful_signal` | sources:required |
| `end-to-end-causal-tail-mass-landmark-pooling-without-stabi-bfc557c959` | `useful_signal` | sources:required |
| `end-to-end-gpt-2-small-self-speculative-decoding-with-trai-f29c835448` | `useful_signal` | sources:required |
| `end-to-end-prompt-local-copy-speculative-decoding-on-extra-8d842ef544` | `useful_signal` | sources:required |
| `end-to-end-suffix-kv-reuse-in-a-real-speculative-decoding-29999772c3` | `useful_signal` | sources:required |
| `enforced-4-gib-cuda-cap-gpt-2-small-adamw-boundary-test-1b0e42d018` | `useful_signal` | sources:required |
| `entropy-coded-anchor-preprocessing-against-standard-compre-d69ad54fb5` | `useful_signal` | sources:required |
| `equal-cost-adaptive-verifier-on-real-small-transformer-act-0b1d1d6116` | `useful_signal` | sources:required |
| `exactness-audit-for-prompt-lookup-speculative-decoding-72282eb048` | `useful_signal` | sources:required |
| `externally-enforced-ledger-react-with-semantic-source-veri-40002ab1d8` | `useful_signal` | sources:required |
| `free-form-evidence-audit-reward-on-real-tool-agent-summari-c1cf194f11` | `useful_signal` | sources:required |
| `frozen-gpt-2-small-native-kv-intervention-for-anchor-and-l-8d8f96fac8` | `useful_signal` | sources:required |
| `frozen-rule-multi-dataset-confidence-router-package-with-s-626cd501b3` | `useful_signal` | sources:required |
| `full-writer-femnist-sparsity-and-rewinding-gradient-audit-ec8edb7f50` | `useful_signal` | sources:required |
| `fused-gpt-2-small-dynresact-latency-and-metadata-accountin-c5841e0478` | `useful_signal` | sources:required |
| `fused-packed-2-bit-residual-channel-projection-kernel-on-g-d75620eff6` | `promising_if_scaled` | sources:required |
| `fused-real-kv-anchor-router-latency-validation-1c251337a8` | `useful_signal` | sources:required |
| `gate-initialization-and-schedule-ablation-for-binary-resid-0c020311b6` | `useful_signal` | sources:required |
| `generative-local-llm-confidence-cascade-with-actual-server-00a5434e21` | `promising_if_scaled` | sources:required |
| `gpt-2-small-class-bpe-validation-of-functional-ternary-low-b431ffc6df` | `useful_signal` | sources:required |
| `gpt-2-small-class-detached-residual-split-q3-w-a-validatio-d08e69867d` | `useful_signal` | sources:required |
| `gpt-2-small-class-dual-memory-anchor-recall-with-layout-ab-27f0e20420` | `useful_signal` | sources:required |
| `gpt-2-small-class-memory-budget-validation-for-factored-ad-e65a948c12` | `useful_signal` | sources:required |
| `gpt-2-small-class-tokenized-validation-of-sqrt-int8-adam-v-b236358172` | `useful_signal` | sources:required |
| `gpt-2-small-inference-validation-of-key-addressed-anchorsl-2f16602be2` | `useful_signal` | sources:required |
| `gpt-2-small-validation-of-activation-aware-residual-adapte-8a67fa3593` | `useful_signal` | sources:required |
| `gradient-dot-audits-for-label-flip-anomaly-detection-063cd69498` | `promising_if_scaled` | sources:required |
| `hard-unsupported-claim-ledger-audit-across-models-bac6248a0f` | `useful_signal` | sources:required |
| `held-out-adversarial-paraphrase-benchmark-for-hybrid-signe-9f09a96b0c` | `useful_signal` | sources:required |
| `held-out-mbpp-humaneval-confirmation-for-minimum-token-log-13719bee3c` | `useful_signal` | sources:required |
| `held-out-natural-copy-suffix-localization-benchmark-b1acbb1e92` | `useful_signal` | sources:required |
| `held-out-sub-1b-generation-test-for-evidence-ledger-valida-be30b56387` | `useful_signal` | sources:required |
| `hierarchical-shrinkage-local-cascade-gates-for-selective-r-18b0ed1fac` | `useful_signal` | sources:required |
| `human-llm-paraphrase-memory-grounding-with-semantic-retrie-312e6bb9b1` | `useful_signal` | sources:required |
| `hybrid-raw-context-plus-evidence-ledger-abstention-gate-0d6d88f6a0` | `useful_signal` | sources:required |
| `hybrid-semantic-gradient-text-coresets-against-strong-sema-9e9439faf7` | `useful_signal` | sources:required |
| `identity-biased-kv-trace-gates-with-measured-skip-savings-19e057074e` | `useful_signal` | sources:required |
| `incremental-key-anchor-kv-cache-serving-validation-be5111575d` | `useful_signal` | sources:required |
| `independent-label-evaluation-of-evidence-audit-rewards-on-08b7d9eb85` | `useful_signal` | sources:required |
| `instrumented-serving-replay-for-learned-kv-offload-admissi-504dcc1afb` | `useful_signal` | sources:required |
| `int4-kv-residual-window-validation-with-measured-memory-an-6c4762396d` | `promising_if_scaled` | sources:required |
| `integrated-commit-reveal-audit-on-a-real-gpt-2-small-train-44f22cfc92` | `promising_if_scaled` | sources:required |
| `internal-kv-cache-anchors-versus-prompt-token-anchors-on-e-55a2892ad1` | `useful_signal` | sources:required |
| `kv-cache-suffix-history-speculative-decoding-on-mixed-prom-9c482497e8` | `useful_signal` | sources:required |
| `langgraph-adapter-rollback-ledger-under-randomized-crash-a-b627e5b7ef` | `useful_signal` | sources:required |
| `layer-and-objective-sweep-for-gpt-2-self-speculative-inter-feb8826fcb` | `useful_signal` | sources:required |
| `layerwise-and-multi-layer-direct-fidelity-residual-substit-5e515aa9cc` | `promising_if_scaled` | sources:required |
| `learned-latent-kv-slots-versus-parameter-matched-prompt-to-5eccd0e9ee` | `useful_signal` | sources:required |
| `learned-pre-attention-commitment-masks-for-trace-driven-la-d315aeeda5` | `useful_signal` | sources:required |
| `live-agent-integration-replay-test-for-signed-tool-path-re-428259d2c6` | `useful_signal` | sources:required |
| `live-agent-runtime-signed-provenance-ledger-integration-1b54de2acc` | `useful_signal` | sources:required |
| `live-agent-tool-path-signed-recorder-with-crash-and-concur-d3d8173e93` | `useful_signal` | sources:required |
| `live-append-restart-recovery-for-isolated-ledger-tailing-1e380a0ab2` | `useful_signal` | sources:required |
| `live-llm-agent-failure-recall-with-append-only-evidence-le-aed02f6519` | `useful_signal` | sources:required |
| `live-tool-trace-contradiction-recovery-without-last-mentio-f02b02654c` | `promising_if_scaled` | sources:required |
| `llm-agent-natural-language-evidence-ledger-counterexample-32dadf6f5e` | `useful_signal` | sources:required |
| `long-context-copy-heavy-prompt-n-gram-speculative-decoding-9afd8b765d` | `promising_if_scaled` | sources:required |
| `long-context-model-integrated-candidate-ranking-for-cache-61d531a365` | `useful_signal` | sources:required |
| `longer-streaming-real-trace-anchor-cadence-validation-for-1df80410a4` | `useful_signal` | sources:required |
| `manually-audited-semantic-multi-trace-verification-for-rea-04d2330f8a` | `useful_signal` | sources:required |
| `mass-aware-exact-anchor-clustered-kv-cache-decoding-on-gpt-22c14bdcc3` | `useful_signal` | sources:required |
| `medium-benchmark-of-executable-validation-on-llm-authored-0d662e79ce` | `useful_signal` | sources:required |
| `medium-confirmation-of-activation-selected-residual-channe-8da773aa9f` | `useful_signal` | sources:required |
| `medium-confirmation-of-direct-trace-auditing-on-multi-clai-12114ef815` | `useful_signal` | sources:required |
| `medium-confirmation-of-flop-matched-length-curriculum-with-46f1ae376e` | `useful_signal` | sources:required |
| `medium-confirmation-of-small-large-lm-entropy-cascade-rout-d1012a5de3` | `promising_if_scaled` | sources:required |
| `medium-direct-confirmation-of-uncertainty-routed-cascades-72a499b232` | `useful_signal` | sources:required |
| `medium-gpt-2-class-residual-split-q3-w-a-confirmation-658dc44fcb` | `useful_signal` | sources:required |
| `medium-kv-cache-benchmark-for-prompt-n-gram-speculative-de-83b47bbef2` | `useful_signal` | sources:required |
| `medium-lottery-gradient-audit-confirmation-on-femnist-and-690ec03534` | `useful_signal` | sources:required |
| `medium-multi-corpus-cross-instance-evidence-verification-9ea0827de6` | `useful_signal` | sources:required |
| `medium-multi-model-contradiction-recovery-confirmation-43a57b2c44` | `useful_signal` | sources:required |
| `medium-multi-seed-key-addressed-anchorslot-kv-cache-confir-5cace3d1df` | `useful_signal` | sources:required |
| `medium-natural-long-context-validation-of-anchor-gated-kv-913bb4d635` | `useful_signal` | sources:required |
| `medium-neural-gradient-confirmation-for-distribution-prese-5ec91d2b4f` | `useful_signal` | sources:required |
| `medium-neural-shard-lottery-validation-under-adaptive-shar-ee7572f07e` | `useful_signal` | sources:required |
| `medium-non-iid-adaptive-validation-of-commit-reveal-volunt-7a8e1754ac` | `useful_signal` | sources:required |
| `medium-real-agent-provenance-ledger-integration-benchmark-c8aa9f7b11` | `useful_signal` | sources:required |
| `medium-real-kv-anchor-router-benchmark-73c2329123` | `promising_if_scaled` | sources:required |
| `medium-real-lm-benchmark-for-confidence-gated-anchor-kv-ev-faabe119e5` | `useful_signal` | sources:required |
| `medium-real-task-repeated-vs-one-shot-hidden-volunteer-gra-0dd61c3177` | `useful_signal` | sources:required |
| `medium-real-trace-confirmation-for-evidence-ledger-auditin-3817c20ac4` | `useful_signal` | sources:required |
| `medium-scale-commit-reveal-replay-auditing-on-a-larger-opt-dd9c25b0da` | `promising_if_scaled` | sources:required |
| `medium-scale-robustness-benchmark-for-hidden-canary-gradie-482e5b4759` | `useful_signal` | sources:required |
| `medium-tokenized-gpt-confirmation-of-low-rank-residuals-fo-e57c48b774` | `useful_signal` | sources:required |
| `medium-transformer-validation-of-neural-chunk-commitment-u-0962eea1a9` | `useful_signal` | sources:required |
| `medium-validation-of-deployable-ppl-uncertainty-gates-for-05dff99f7d` | `promising_if_scaled` | sources:required |
| `memory-accurate-gpt-2-small-class-validation-of-2-bit-kv-r-c2fef5b828` | `useful_signal` | sources:required |
| `model-generated-copy-suffix-localization-with-controlled-e-b7a81ba63a` | `useful_signal` | sources:required |
| `model-generated-ledger-trace-replay-validation-a5474fed54` | `useful_signal` | sources:required |
| `model-integrated-cache-aware-n-gram-drafting-on-code-and-r-16dea29f32` | `useful_signal` | sources:required |
| `multi-model-hakv-inference-fidelity-robustness-at-25--rete-563c210425` | `useful_signal` | sources:required |
| `multi-model-held-out-exact-anchor-ledger-replay-on-real-ag-d3dd4b6cc9` | `useful_signal` | sources:required |
| `multi-model-live-agent-validation-of-evidence-ledger-rollb-2bafcbdb12` | `useful_signal` | sources:required |
| `multi-model-semi-real-evidence-ledger-hallucination-eval-36c7076304` | `useful_signal` | sources:required |
| `multi-model-true-document-anchor-kv-retention-validation-5578b6c16f` | `useful_signal` | sources:required |
| `multi-pair-fixed-answer-confidence-cascade-validation-b89dbd4689` | `useful_signal` | sources:required |
| `multi-trace-evidence-ledger-verification-on-real-agent-fin-e0f0c3182b` | `useful_signal` | sources:required |
| `native-evidence-ledger-poisoning-with-live-replay-agent-f76af5924e` | `useful_signal` | sources:required |
| `natural-corpus-anchor-kv-retention-against-non-recency-con-14801e439d` | `useful_signal` | sources:required |
| `natural-corpus-multi-anchor-exactness-with-coverage-rerank-01615747c2` | `useful_signal` | sources:required |
| `natural-corpus-paraphrase-memory-grounding-with-equal-budg-d480d2d7bc` | `useful_signal` | sources:required |
| `natural-evidence-claim-ledger-audit-with-independent-verif-071314f2ad` | `useful_signal` | sources:required |
| `natural-tool-trace-ledger-react-with-independent-semantic-609daf2f66` | `useful_signal` | sources:required |
| `naturalistic-copy-suffix-localization-without-explicit-quo-bc04d2807a` | `useful_signal` | sources:required |
| `naturalistic-paraphrase-memory-grounding-with-end-to-end-a-45f563a044` | `useful_signal` | sources:required |
| `neural-multiclass-cascade-validation-for-calibrated-entrop-91c266152d` | `useful_signal` | sources:required |
| `neural-ppo-field-ablated-merkle-audit-reproduction-6ac380c201` | `useful_signal` | sources:required |
| `neural-semantic-detector-ablation-for-signed-shard-paraphr-33d651ac24` | `useful_signal` | sources:required |
| `nli-llm-evidence-ledger-jury-on-multi-dataset-fact-qa-3a7448a8d6` | `useful_signal` | sources:required |
| `noisy-transaction-extraction-for-verifier-repaired-ledger-f7246743e3` | `useful_signal` | sources:required |
| `nonlinear-adapter-hidden-volunteer-repetition-under-fresh-4fe051b828` | `useful_signal` | sources:required |
| `nonlinear-residual-predictor-optimized-for-direct-cache-su-dd938b3461` | `useful_signal` | sources:required |
| `nonlinear-shared-gradient-proxy-verifier-confirmation-15238b296a` | `useful_signal` | sources:required |
| `online-isolated-ledger-tailing-during-live-multi-turn-tool-d1913d050e` | `useful_signal` | sources:required |
| `optimized-exact-cache-path-for-gpt-2-intermediate-head-sel-0692caf722` | `useful_signal` | sources:required |
| `optimized-long-context-real-kv-anchor-router-benchmark-e4b7adedbe` | `useful_signal` | sources:required |
| `optimized-persistent-merkle-kv-ledger-with-crash-restart-a-9dcce7bc1b` | `useful_signal` | sources:required |
| `optimized-suffix-copy-speculative-decoding-across-corpora-ad6443df25` | `useful_signal` | sources:required |
| `organic-llm-authored-multi-source-evidence-ledger-validati-f6e85c3c36` | `useful_signal` | sources:required |
| `organic-llm-authored-public-data-evidence-ledger-validatio-bc531a9fd7` | `useful_signal` | sources:required |
| `packed-int2-kv-residual-window-validation-with-measured-me-c114b1bd71` | `promising_if_scaled` | sources:required |
| `parameter-matched-and-regularized-residualfp-fast-path-tes-fa722443e9` | `useful_signal` | sources:required |
| `per-layer-attention-only-versus-adaptive-hakv-retention-at-9f783e5b95` | `useful_signal` | sources:required |
| `pointer-head-small-transformer-test-for-exact-anchor-ledge-306a5a9bd4` | `useful_signal` | sources:required |
| `post-mask-recovery-validation-for-gpt-2-bpe-residual-chann-17140c408e` | `useful_signal` | sources:required |
| `practical-randomized-svd-hybrid-spectral-adamw-on-small-tr-e7c4eede14` | `useful_signal` | sources:required |
| `pre-registered-conservative-confidence-router-validation-o-00e10bbdac` | `useful_signal` | sources:required |
| `prefetch-aware-pytorch-dataloader-replay-state-for-multi-w-a94886129a` | `promising_if_scaled` | sources:required |
| `pretrained-small-lm-anchor-indexed-kv-cache-validation-5e2a72d80e` | `useful_signal` | sources:required |
| `process-kill-rollback-ledger-validation-with-external-serv-9a2fc1f56f` | `useful_signal` | sources:required |
| `process-kill-sqlite-wal-quorum-cleanup-under-concurrent-re-4b10ee88e8` | `useful_signal` | sources:required |
| `process-level-exact-anchor-resume-in-a-1000-step-tool-usin-38fce41f14` | `useful_signal` | sources:required |
| `production-baseline-crash-campaign-for-incremental-merkle-46d4f04fc4` | `useful_signal` | sources:required |
| `production-cache-prompt-local-copy-speculative-decoding-on-5f15be9656` | `useful_signal` | sources:required |
| `production-style-copy-on-write-kv-suffix-history-speculati-3ee4d280af` | `useful_signal` | sources:required |
| `production-style-persistent-external-anchor-ledger-under-c-0a4f581633` | `useful_signal` | sources:required |
| `production-trace-provenance-ledger-validation-against-matu-84b6cf9286` | `useful_signal` | sources:required |
| `production-trace-strict-n-gram-drafting-cpu-serving-valida-6d3078dd22` | `promising_if_scaled` | sources:required |
| `profiler-matched-text-retrieval-length-curriculum-c00fda505f` | `useful_signal` | sources:required |
| `prototype-hybrid-snapshot-plus-evidence-ledger-rollback-in-19becd2e73` | `useful_signal` | sources:required |
| `rank-anchor-frontier-for-quality-bounded-low-rank-kv-compr-4a9a64cb1e` | `useful_signal` | sources:required |
| `real-agent-evaluation-of-evidence-ledger-rollback-benchmar-138960146a` | `useful_signal` | sources:required |
| `real-agent-runtime-batched-signed-provenance-ledger-integr-7e80aea690` | `useful_signal` | sources:required |
| `real-agent-trace-replay-evidence-ledger-poisoning-validati-cd96859f9d` | `promising_if_scaled` | sources:required |
| `real-corpus-medium-validation-for-streamed-adam-moment-sto-3a0d2e995a` | `promising_if_scaled` | sources:required |
| `real-dataset-small-model-evidence-ledger-jury-benchmark-4e95f7d83d` | `useful_signal` | sources:required |
| `real-fl-validation-of-commit-reveal-volunteer-training-c9fdba9e03` | `promising_if_scaled` | sources:required |
| `real-framework-deterministic-replay-with-dataloader-state-7b6cf748c0` | `useful_signal` | sources:required |
| `real-kv-anchors-on-a-competent-learned-recall-model-1b68c0de0b` | `useful_signal` | sources:required |
| `real-llm-tool-agent-provenance-ledger-validation-with-conc-e05539bbf7` | `useful_signal` | sources:required |
| `real-llm-tool-trace-ledger-verification-under-constrained-3b450fcc17` | `useful_signal` | sources:required |
| `real-lm-hidden-state-shuffled-error-validation-for-router-57eb325275` | `useful_signal` | sources:required |
| `real-model-int3-kv-cache-with-online-attention-history-fp1-a957bb51dd` | `useful_signal` | sources:required |
| `real-model-kv-trace-replay-for-content-aware-anchor-compre-91cf91e29c` | `useful_signal` | sources:required |
| `real-report-validation-of-trace-specific-gains-in-multi-cl-afbbf95ada` | `promising_if_scaled` | sources:required |
| `real-serving-calibration-for-learned-kv-offload-admission-b385fd3a41` | `useful_signal` | sources:required |
| `real-small-lm-kv-trace-test-for-2-bit-residual-block-gates-f8490ab41d` | `useful_signal` | sources:required |
| `real-task-severe-scarcity-nonlinear-adapter-validation-2e407b5048` | `useful_signal` | sources:required |
| `real-text-convergence-validation-for-gpt-2-small-factored-f2435c231e` | `useful_signal` | sources:required |
| `real-text-exact-anchor-compression-confirmation-9611f5ce6a` | `useful_signal` | sources:required |
| `real-text-exact-token-qwed-selection-with-loss-guardrail-f8e8bdcace` | `useful_signal` | sources:required |
| `real-text-storage-matched-residual-channel-binary-mlp-swee-8c0ef44583` | `useful_signal` | sources:required |
| `real-tool-agent-harness-evaluation-for-ledger-constrained-ea106e457e` | `useful_signal` | sources:required |
| `real-trace-restart-recovery-for-isolated-ledger-tailing-422e23e008` | `useful_signal` | sources:required |
| `real-trace-validation-of-append-only-failure-evidence-ledg-e2a52d3d02` | `useful_signal` | sources:required |
| `recency-first-int3-kv-cache-fp16-exceptions-d11940a3d7` | `useful_signal` | sources:required |
| `recency-protected-draft-scored-kv-eviction-38a039467f` | `useful_signal` | sources:required |
| `recorded-agent-tool-trace-contradiction-recovery-benchmark-ceac3cc2cf` | `promising_if_scaled` | sources:required |
| `replay-evidence-ledger-poisoning-on-real-stored-agent-trac-ef8b48b380` | `useful_signal` | sources:required |
| `replicated-hybrid-snapshot-versus-evidence-ledger-rollback-99d01e65ab` | `useful_signal` | sources:required |
| `residual-channel-preservation-on-real-bpe-tokenizations-6d45bd8b4c` | `useful_signal` | sources:required |
| `residual-channel-selection-on-top-of-gptq-awq-style-2-bit-7a72c2c121` | `useful_signal` | sources:required |
| `residual-nonlinear-activation-verifier-with-actual-verifie-458ccb1b76` | `useful_signal` | sources:required |
| `richer-calibration-for-entropy-routing-on-multiclass-casca-c34659b1bc` | `promising_if_scaled` | sources:required |
| `risk-controlled-local-cascade-gates-with-conformal-abstent-2c67ea84c6` | `useful_signal` | sources:required |
| `robust-1024-token-mass-aware-kv-pooling-validation-with-op-8232bd5bcc` | `useful_signal` | sources:required |
| `robust-commit-reveal-gradient-validation-with-public-refer-e07a20a294` | `useful_signal` | sources:required |
| `robust-logprob-confidence-scores-for-qwen2-5-coder-cascade-75c3d70e9f` | `useful_signal` | sources:required |
| `robust-residual-channel-preservation-with-tokenizer-lm-and-50ca57b25e` | `useful_signal` | sources:required |
| `router-calibrated-kv-adapter-with-cache-integrated-error-f-41199327e2` | `useful_signal` | sources:required |
| `routing-knowledge-ablation-for-neural-shard-lottery-robust-79097af03f` | `useful_signal` | sources:required |
| `segment-aware-masking-for-content-anchor-kv-replay-353c198c3d` | `useful_signal` | sources:required |
| `shuffled-error-and-multi-layer-validation-for-router-calib-2ce5778d6c` | `useful_signal` | sources:required |
| `signed-recorder-on-real-multi-step-agent-tool-traces-3d0cea7dba` | `useful_signal` | sources:required |
| `small-transformer-adapter-validation-for-residual-preservi-dfbb836955` | `useful_signal` | sources:required |
| `small-transformer-confirmation-for-hybrid-spectral-adam-a484f816b0` | `useful_signal` | sources:required |
| `small-transformer-shard-dropout-versus-routing-knowledge-a-22ae468db7` | `useful_signal` | sources:required |
| `small-transformer-validation-of-sqrt-stabilized-blockwise-c0007cb542` | `useful_signal` | sources:required |
| `sparse-paged-execution-for-exact-segment-aware-content-anc-8669d434c6` | `useful_signal` | sources:required |
| `sqlite-wal-quorum-ledger-with-prepare-commit-cleanup-580bb7741c` | `useful_signal` | sources:required |
| `static-parameter-matched-residual-adapters-for-1-bit-recov-8ee68488ea` | `useful_signal` | sources:required |
| `storage-real-gpt-2-small-validation-of-tuned-nonzero-floor-04f091edf4` | `useful_signal` | sources:required |
| `streaming-storage-saving-dplr-floor-adam-versus-adam-and-a-414ba530a2` | `useful_signal` | sources:required |
| `strict-verifier-cpu-n-gram-drafting-serving-test-469c406314` | `promising_if_scaled` | sources:required |
| `structured-tool-exact-anchor-replay-on-multi-seed-real-cod-28fd3cd21f` | `useful_signal` | sources:required |
| `suffix-history-speculative-decoding-in-a-real-kv-cache-ser-f44e0013af` | `useful_signal` | sources:required |
| `tail-stabilized-causal-anchor-selection-for-real-kv-landma-ef313763fc` | `useful_signal` | sources:required |
| `token-level-gpt-2-latency-test-for-suffix-copy-speculative-4980023e0f` | `useful_signal` | sources:required |
| `token-level-ledger-constrained-decoding-on-1b-tool-agents-f623678536` | `useful_signal` | sources:required |
| `token-level-ledger-constrained-decoding-vs-post-hoc-repair-d687163747` | `useful_signal` | sources:required |
| `token-suffix-speculative-drafting-without-kv-cache-reuse-6f3cc61086` | `useful_signal` | sources:required |
| `tokenizer-level-suffix-match-drafter-integrated-with-a-sma-9396e3555b` | `useful_signal` | sources:required |
| `trace-driven-learned-kv-offload-admission-under-memory-pre-20fc2b74de` | `useful_signal` | sources:required |
| `trace-driven-paged-kv-anchor-cache-serving-benchmark-5d60334321` | `useful_signal` | sources:required |
| `train-real-auxiliary-exit-heads-for-early-exit-speculative-a72b6570f4` | `useful_signal` | sources:required |
| `transformer-scale-residual-hidden-state-router-for-frozen-6d36c9a4d8` | `useful_signal` | sources:required |
| `true-4-gb-capped-fused-dplr-adam-validation-3f2b80a8d7` | `useful_signal` | sources:required |
| `true-femnist-writer-partition-and-longer-cifar-10-lottery-276241cd81` | `useful_signal` | sources:required |
| `true-fused-dynresact-route-scatter-kernel-for-gpt-2-small-b490e7dadf` | `useful_signal` | sources:required |
| `ultra-low-budget-gradient-aware-text-coresets-2e11cea8fe` | `useful_signal` | sources:required |
| `uncertainty-gated-anchor-kv-eviction-across-real-lms-and-c-49749d6603` | `promising_if_scaled` | sources:required |
| `validate-hybrid-snapshot-plus-evidence-ledger-rollback-in-e4cbdfb07e` | `useful_signal` | sources:required |
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
