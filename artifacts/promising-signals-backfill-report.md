# Promising signals backfill audit

Generated: `2026-05-19T19:19:10.227747+00:00`

This is a dry-run classification report. It does not export rows or change the companion repo.

## Summary

| Bucket | Count |
|---|---:|
| Total candidate rows | 1695 |
| Export cleanly now | 515 |
| Backfilled exportable | 267 |
| Missing required evidence/fields | 0 |
| Excluded because paper/corpus | 269 |
| Hard negative or stale | 911 |

## Backfill plan

1. Export rows in `export_cleanly_now` first; they already satisfy the deterministic public record contract.
2. Backfill rows in `missing_required_evidence_or_fields` only after source/evidence fields are recovered from control-plane or worker artifacts.
3. Leave `excluded_paper_or_corpus` out of the promising-signals repo; those belong to the paper/corpus lane.
4. Leave `hard_negative_or_stale` out unless a new deterministic decision record changes their status.

## Export cleanly now

| Project | Outcome | Issues | Backfill |
|---|---|---|---|
| `1-bit-residual-channel-pretraining-for-gpt-2-small-class-e082079e4a3f` | `useful_signal` |  |  |
| `1-bit-weights-with-fp16-residual-channels-80394161b338` | `useful_signal` |  |  |
| `2-bit-kv-cache-with-per-head-residual-correction-for-long-context-7da3805285d2` | `useful_signal` |  |  |
| `4-gb-capped-rank-0-factored-optimizer-validation-96f718707f` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `acceptance-aware-gpt-2-small-early-exit-heads-for-exact-se-bc1a42be2d` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `activation-aware-calibration-for-static-residual-adapters-08e1f264dc` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `activation-aware-learned-residual-channels-for-1-bit-recov-70ce4e2acc` | `useful_signal` |  |  |
| `activation-magnitude-residual-channel-preservation-for-sub-64eddc32c2` | `useful_signal` |  |  |
| `activation-selected-residual-channels-with-error-aware-2-b-ad5a87cb53` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `actual-head-identity-plus-recency-kv-gating-on-gpt-2-small-2bacb1c6e5` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `adaptive-cascade-router-for-latency-quality-pareto-on-10gb-341838c4456f` | `useful_signal` |  |  |
| `adaptive-exact-anchors-with-learned-cross-layer-kv-residua-ebc41d5055` | `useful_signal` |  |  |
| `adaptive-or-periodically-corrected-low-rank-adamw-for-smal-afbae3b446` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `adaptive-precision-residual-gates-for-2-bit-kv-cache-84a98257a7a3` | `useful_signal` |  |  |
| `adaptive-rank-anchor-kv-compression-on-gpt-2-small-class-l-003174ac4a` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `adaptive-training-loop-validation-for-conditional-lottery-e6bb1c9086` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `additive-residual-codebook-for-1-58-bit-kv-cache-b4795df000ba` | `promising_if_scaled` |  |  |
| `adversarial-falsification-of-agent-evidence-ledgers-via-counterexample-mining-f57c8cb5e0e1` | `useful_signal` |  |  |
| `adversarial-persistence-test-for-incremental-merkle-kv-age-e2048a7490` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `anchor-conditioned-kv-eviction-for-long-context-0475981f0673` | `useful_signal` |  |  |
| `anchor-exact-kv-compression-for-long-context-recall-1093d8eb655c` | `useful_signal` |  |  |
| `anchor-gated-kv-compression-for-long-context-6e3650a20b17` | `useful_signal` |  |  |
| `anchor-gated-kv-compression-with-exact-positional-retrieval-2578d1fa81f9` | `useful_signal` |  |  |
| `anchor-gated-sparse-kv-cache-with-interpolated-eviction-a54888767f28` | `promising_if_scaled` |  |  |
| `anchor-indexed-kv-compression-with-exact-recall-positions-ab2f6cd34ec6` | `useful_signal` |  |  |
| `anchor-preserved-kv-compression-with-deterministic-markers-e7b017b702fb` | `promising_if_scaled` |  |  |
| `anchor-preserved-kv-compression-with-entropy-gated-exact-retention-aa555ccfc2bb` | `useful_signal` |  |  |
| `anchor-preserved-low-rank-kv-compression-01a9ece04fee` | `useful_signal` |  |  |
| `anchored-hmac-checkpoints-in-a-real-agent-runtime-91aa182911` | `useful_signal` |  |  |
| `anchorslot-kv-compression-for-exact-long-context-retrieval-f4497b00ae17` | `useful_signal` |  |  |
| `append-only-evidence-ledger-for-sub-1b-agent-tool-use-hallucination-reduction-4024f83194b8` | `useful_signal` |  |  |
| `async-or-host-resident-streamed-adamw-backend-in-a-real-tr-5535bfa367` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `attention-aware-residual-codebooks-for-1-58-bit-kv-cache-3f1bc04709` | `promising_if_scaled` |  |  |
| `attention-mass-selected-fp16-exceptions-for-int3-kv-cache-1372b9be4a` | `useful_signal` |  |  |
| `batched-larger-model-evidence-ledger-counterexample-sweep-ccaf21822f` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `behavior-aware-learned-kv-residual-prediction-for-exact-an-b76f7664e0` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `blinded-multi-agent-evidence-ledger-counterexample-benchma-eed79744df` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `block-aligned-learned-commitment-masks-for-real-sparse-att-fad58349e8` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `block-stochastic-quantized-optimizer-states-with-periodic-correction-8de8a5154b62` | `useful_signal` |  |  |
| `blockwise-8-bit-adam-for-gpt-2-small-pretraining-under-4gb-vram-a41d6660b0a8` | `useful_signal` |  |  |
| `blockwise-stabilized-4-bit-adam-second-moment-on-a-small-t-d75abbd657` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `bounded-ablation-of-verifier-repaired-ledgers-on-small-mod-3dfb92907f` | `useful_signal` |  |  |
| `bounded-full-scale-commit-reveal-replay-auditing-on-a-real-3eddb3740f` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `bounded-full-scale-memory-pressure-validation-for-streamed-6f56b891a0` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `bounded-full-scale-validation-of-nonzero-floor-4-bit-adam-2d840742e7` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `bounded-neural-volunteer-training-commit-reveal-validation-9946e055fc` | `promising_if_scaled` |  |  |
| `bounded-production-style-strict-n-gram-drafting-cpu-servin-4ef349b27f` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `bounded-scale-gap-validation-of-calibrated-ppl-gates-for-n-08c789374b` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `calibrated-auxiliary-early-exit-draft-for-speculative-deco-f71fb85632` | `useful_signal` |  |  |
| `calibrated-confidence-gated-local-llm-cascade-with-held-ou-b689674c75` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `calibrated-confidence-gates-for-stable-local-cascade-routi-4973719f64` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `calibrated-entropy-plus-confidence-n-gram-router-across-co-e23bca791a` | `useful_signal` |  |  |
| `calibrated-evidence-ledger-jury-with-larger-real-data-cove-0937d49bc3` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `calibrated-logprob-routing-with-a-stronger-qwen2-5-coder-f-cf6506eb83` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `calibrated-soft-source-diversity-for-cross-corpus-claim-ve-908672b271` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `calibrated-top-k-qwed-interpolation-on-a-second-real-corpu-658f7a5b78` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `calibration-trained-ternary-low-rank-residual-repair-for-g-0e07829031` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `calibration-trained-ternary-residual-channels-for-gpt-2-sm-59c820e71a` | `useful_signal` |  |  |
| `canary-gradient-probes-for-volunteer-cheating-detection-ddd8e03afd4d` | `useful_signal` |  |  |
| `causal-non-oracle-anchor-selection-for-real-kv-landmark-po-09956cac81` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `challenge-response-forward-pass-for-volunteer-training-12ad399ab207` | `useful_signal` |  |  |
| `cheap-confidence-router-for-qwen2-5-coder-1-5b-7b-cascade-a460e154bb` | `useful_signal` |  |  |
| `cheap-ranker-for-cache-aware-n-gram-candidate-selection-26a468c4ec` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `checkpointed-gpt-2-intermediate-kl-heads-for-actual-specul-9042abd5e4` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `cifar-10-calibrated-uncertainty-routed-cascades-with-laten-e93d3deda8` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `claim-ledger-audit-with-strong-independent-nli-verificatio-1b04378348` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `commit-reveal-gradient-validation-for-cheating-resistant-volunteer-training-10aad0bda5d9` | `useful_signal` |  |  |
| `commit-reveal-gradient-validation-for-cheating-resistant-volunteer-training-bdedf04df87d` | `promising_if_scaled` |  |  |
| `commit-reveal-gradient-validation-for-volunteer-distributed-training-7284e53de3a5` | `useful_signal` |  |  |
| `commit-reveal-gradient-validation-under-non-iid-neural-vol-426459ea98` | `useful_signal` |  |  |
| `commit-reveal-replay-lotteries-on-a-real-optimizer-trace-f367751cad` | `promising_if_scaled` |  |  |
| `commit-reveal-shard-lottery-for-volunteer-gradient-validation-385eda026ea7` | `useful_signal` |  |  |
| `commit-reveal-spot-check-gradient-verification-for-volunteer-training-c7bbf4bdc595` | `useful_signal` |  |  |
| `committee-lottery-audits-for-volunteer-gradient-integrity-0f0bcb35374d` | `useful_signal` |  |  |
| `concurrent-atomic-rollback-ledger-recovery-under-external-f4ccb768a5` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `concurrent-signed-witness-soak-for-anchored-agent-ledgers-d5e8aa1740` | `useful_signal` |  |  |
| `confidence-gated-cascade-with-kv-prefix-reuse-for-local-serving-abc42e4dcc77` | `useful_signal` |  |  |
| `confidence-gated-local-cascade-router-5f78a44d1f` | `useful_signal` |  |  |
| `confidence-router-cascade-for-vram-reduction-ee2ba6c3c184` | `useful_signal` |  |  |
| `consistency-forced-verifier-repaired-ledger-state-tracking-e378de737a` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `constrained-model-authored-evidence-ledgers-for-sub-1b-qa-9b15f7fcd3` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `constrained-span-candidate-evidence-ledgers-for-sub-1b-qa-41c6554697` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `content-aware-anchor-kv-compression-for-approximate-redund-9dc0d3705e` | `useful_signal` |  |  |
| `context-local-suffix-array-speculative-decoding-290e5a35ec78` | `useful_signal` |  |  |
| `context-suffix-speculative-decoding-without-any-draft-model-cb96b6c2ff11` | `useful_signal` |  |  |
| `controlled-residualfp-channel-ablations-in-a-longer-tiny-l-d79bfcfb7c` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `controller-integrated-postgres-langgraph-hard-cutover-faul-77a07dc1a4` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `cost-aware-frozen-confidence-router-with-measured-overhead-787a704188` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `cost-matched-robust-lottery-versus-robust-top-k-at-boundar-ac22ab74d3` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `counterexample-mining-on-realistic-agent-evidence-ledgers-b4d46ca0c6` | `useful_signal` |  |  |
| `coverage-constrained-sampled-adamw-recomputation-on-the-sa-04a71608ba` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `coverage-constrained-variance-selection-on-real-tiny-lm-te-e88a0676c3` | `useful_signal` |  |  |
| `cpu-ngram-context-draft-decoding-cd3d09a0093d` | `useful_signal` |  |  |
| `cross-device-adamw-sampled-gradient-recomputation-on-a-sma-9de0074913` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `cross-instance-evidence-verification-7c114bf77ca0` | `useful_signal` |  |  |
| `cross-model-kv-cascade-router-with-affine-adapter-64f380dca440` | `useful_signal` |  |  |
| `cryptographic-evidence-ledger-for-agent-action-provenance-2f707b2ec46f` | `useful_signal` |  |  |
| `curriculum-length-progressive-data-selection-81ef6a727b81` | `useful_signal` |  |  |
| `deployment-faithful-witness-gossip-replay-for-non-cancelab-d97c30da6c` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `depth-4-robustness-validation-of-top-k-qwed-interpolation-dc1d13dfd0` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `deterministic-and-target-aware-bag-size-curricula-for-hard-f345c2cb43` | `promising_if_scaled` |  |  |
| `deterministic-replay-lotteries-for-volunteer-gradient-auditing-7dfd689f8b10` | `useful_signal` |  |  |
| `diagonal-plus-low-rank-nonnegative-adam-second-moments-wit-a5b08cf9e3` | `useful_signal` |  |  |
| `direct-agent-harness-evaluation-of-append-only-evidence-le-704935537c` | `promising_if_scaled` |  |  |
| `direct-anchorslot-kv-cache-test-in-a-small-transformer-fcd3b91f3d` | `useful_signal` |  |  |
| `direct-confidence-quality-cascade-test-with-real-local-mod-520703164e` | `useful_signal` |  |  |
| `direct-federated-benchmark-for-hidden-canary-gradient-audi-aab4c9b92e` | `promising_if_scaled` |  |  |
| `direct-kv-eviction-generation-test-for-draft-scored-cascad-429543f9ee` | `useful_signal` |  |  |
| `direct-llm-agent-contradiction-recovery-benchmark-eeb1daa2d8` | `useful_signal` |  |  |
| `direct-llm-ledger-trace-replay-validation-8b9e7ec7a2` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `direct-local-llm-entropy-gated-cascade-benchmark-f2df2707e8` | `promising_if_scaled` |  |  |
| `direct-local-neural-validation-of-uncertainty-routed-two-t-515773c913` | `useful_signal` |  |  |
| `direct-serving-test-of-cpu-n-gram-drafting-for-code-contex-a360e35298` | `promising_if_scaled` |  |  |
| `direct-small-large-lm-entropy-cascade-evaluation-12393790f2` | `promising_if_scaled` |  |  |
| `direct-small-transformer-evaluation-of-2-bit-kv-residual-c-b8d32bd01c` | `promising_if_scaled` |  |  |
| `direct-trace-audit-benchmark-for-structured-evidence-ledge-e596f42d07` | `useful_signal` |  |  |
| `disk-backed-evidence-ledger-rollback-versus-practical-snap-2ab253a70f` | `useful_signal` |  |  |
| `distribution-aware-calibration-for-residual-activation-ver-66be993511` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `distribution-preserving-gradient-diversity-coresets-on-rea-0781d4adb5` | `useful_signal` |  |  |
| `draft-scored-kv-eviction-cascade-13e63fb1013c` | `useful_signal` |  |  |
| `dual-memory-hierarchical-state-with-exact-anchor-recall-563dc565acb3` | `useful_signal` |  |  |
| `durable-concurrent-agent-runtime-provenance-ledger-integra-649a141b48` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `durable-restart-validation-for-anchored-langgraph-checkpoi-9d1f914464` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `durable-rollback-ledger-for-real-tool-adapters-under-crash-7d5a4300db` | `useful_signal` |  |  |
| `dynamic-vram-router-for-model-cascades-1ce88212c855` | `useful_signal` |  |  |
| `dynresact-dynamic-outlier-residual-channels-for-4-bit-activations-4552506ca304` | `useful_signal` |  |  |
| `efficient-hybrid-low-rank-adamw-update-for-small-lm-traini-c8a1d93ce9` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `embedding-diversity-reservoir-sampling-for-tiny-pretraining-data-selection-ead988174539` | `useful_signal` |  |  |
| `end-to-end-adaptive-ticket-routing-for-conditional-lottery-568f77571d` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `end-to-end-anchor-kv-cache-hit-rate-and-amortization-bench-ca58c29fb4` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `end-to-end-causal-tail-mass-landmark-pooling-without-stabi-bfc557c959` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `end-to-end-gpt-2-compressed-cache-decoding-validation-for-bc77f0facf` | `useful_signal` |  |  |
| `end-to-end-gpt-2-small-dynresact-perplexity-and-latency-pr-3a1baeb62b` | `useful_signal` |  |  |
| `end-to-end-gpt-2-small-self-speculative-decoding-with-trai-f29c835448` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `end-to-end-perplexity-test-for-2-bit-outlier-channel-resid-85f1d9e9fb` | `promising_if_scaled` |  |  |
| `end-to-end-prompt-local-copy-speculative-decoding-on-extra-8d842ef544` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `end-to-end-sampled-gradient-recomputation-for-volunteer-sp-0f3fe3b385` | `useful_signal` |  |  |
| `end-to-end-sgd-shard-lottery-validation-under-targeted-cor-659b2a05fd` | `useful_signal` |  |  |
| `end-to-end-suffix-kv-reuse-in-a-real-speculative-decoding-29999772c3` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `enforced-4-gib-cuda-cap-gpt-2-small-adamw-boundary-test-1b0e42d018` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `enforced-evidence-ledger-validator-for-sub-1b-tool-use-ans-6a220ac83f` | `useful_signal` |  |  |
| `entropy-arbitrated-speculative-router-with-n-gram-fallback-9016e1b6d614` | `useful_signal` |  |  |
| `entropy-coded-anchor-preprocessing-against-standard-compre-d69ad54fb5` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `entropy-gated-local-cascade-router-d0a9f5ce3010` | `promising_if_scaled` |  |  |
| `entropy-gated-local-model-cascade-e53ac0edbaa3` | `promising_if_scaled` |  |  |
| `entropy-routed-two-tier-local-cascade-9039a28c21f0` | `useful_signal` |  |  |
| `equal-cost-adaptive-verifier-on-real-small-transformer-act-0b1d1d6116` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `equal-cost-adaptive-verifier-test-for-sparse-activation-re-abd908e4c4` | `useful_signal` |  |  |
| `evidence-audit-reward-on-real-tool-agent-traces-c31c613762` | `useful_signal` |  |  |
| `evidence-ledger-auditor-on-labeled-rag-or-agent-traces-c55c925359` | `useful_signal` |  |  |
| `evidence-ledger-for-small-agent-tool-calls-8a46fc204841` | `useful_signal` |  |  |
| `evidenceledgertoolhallucination-68bf0a21e3b8` | `useful_signal` |  |  |
| `exact-anchor-block-retrieval-via-compressed-memory-tokens-e8fd1a6fb95d` | `useful_signal` |  |  |
| `exact-anchor-checkpointing-in-a-real-long-episode-agent-ru-b3338a9490` | `useful_signal` |  |  |
| `exact-anchor-kv-cache-compression-via-tiered-summarization-32a35f931905` | `useful_signal` |  |  |
| `exact-anchor-kv-compression-via-sparse-landmark-pooling-9567f71bb992` | `useful_signal` |  |  |
| `exact-anchor-kv-saliency-gating-with-clustered-non-anchor-compression-d2462d72c7d3` | `useful_signal` |  |  |
| `exact-anchor-ledger-for-compressed-agent-episodic-memory-880ec5c31eee` | `useful_signal` |  |  |
| `exact-anchor-ledger-on-real-agent-traces-with-llm-compress-97250787a1` | `useful_signal` |  |  |
| `exact-anchor-state-checkpoints-for-long-episode-agents-f63e4455279a` | `promising_if_scaled` |  |  |
| `exact-kv-cache-context-suffix-verification-on-standard-tex-6b19508496` | `useful_signal` |  |  |
| `exact-token-transformer-test-of-quality-weighted-embedding-f8de11619d` | `useful_signal` |  |  |
| `exactness-audit-for-prompt-lookup-speculative-decoding-72282eb048` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `executable-agent-validation-of-evidence-ledgers-under-cali-f2ff0f6718` | `useful_signal` |  |  |
| `externally-enforced-ledger-react-with-semantic-source-veri-40002ab1d8` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `field-ablated-merkle-trajectory-audits-on-stochastic-ppo-r-d06cb953f3` | `useful_signal` |  |  |
| `free-form-evidence-audit-reward-on-real-tool-agent-summari-c1cf194f11` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `frozen-gpt-2-small-native-kv-intervention-for-anchor-and-l-8d8f96fac8` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `frozen-rule-multi-dataset-confidence-router-package-with-s-626cd501b3` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `full-writer-femnist-sparsity-and-rewinding-gradient-audit-ec8edb7f50` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `fused-gpt-2-small-dynresact-latency-and-metadata-accountin-c5841e0478` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `fused-packed-2-bit-residual-channel-projection-kernel-on-g-d75620eff6` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `fused-real-kv-anchor-router-latency-validation-1c251337a8` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `gate-initialization-and-schedule-ablation-for-binary-resid-0c020311b6` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `generative-local-llm-confidence-cascade-with-actual-server-00a5434e21` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `gpt-2-scale-token-superposition-pretraining-reproduction-ce453cf42b1f` | `promising_if_scaled` |  |  |
| `gpt-2-small-class-bpe-validation-of-functional-ternary-low-b431ffc6df` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `gpt-2-small-class-detached-residual-split-q3-w-a-validatio-d08e69867d` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `gpt-2-small-class-dual-memory-anchor-recall-with-layout-ab-27f0e20420` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `gpt-2-small-class-memory-budget-validation-for-factored-ad-e65a948c12` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `gpt-2-small-class-tokenized-validation-of-sqrt-int8-adam-v-b236358172` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `gpt-2-small-inference-validation-of-key-addressed-anchorsl-2f16602be2` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `gpt-2-small-validation-of-activation-aware-residual-adapte-8a67fa3593` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `gradient-coreset-tiny-pretraining-954ea4314cd5` | `useful_signal` |  |  |
| `gradient-dot-audits-for-label-flip-anomaly-detection-063cd69498` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `gradient-informed-residual-channel-preservation-for-1-58-bit-quantization-7b3e6b413461` | `useful_signal` |  |  |
| `gradient-lottery-validation-for-volunteer-training-95065f6b3d3f` | `useful_signal` |  |  |
| `hard-unsupported-claim-ledger-audit-across-models-bac6248a0f` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `hash-chain-evidence-ledger-for-agent-self-verification-0697af8d6d59` | `useful_signal` |  |  |
| `held-out-adversarial-paraphrase-benchmark-for-hybrid-signe-9f09a96b0c` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `held-out-mbpp-humaneval-confirmation-for-minimum-token-log-13719bee3c` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `held-out-natural-copy-suffix-localization-benchmark-b1acbb1e92` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `held-out-sub-1b-generation-test-for-evidence-ledger-valida-be30b56387` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `hessian-trace-residual-channel-preservation-for-sub-2bit-quantization-3664c59792af` | `useful_signal` |  |  |
| `hidden-state-cluster-router-for-local-specialists-a134afb96043` | `useful_signal` |  |  |
| `hidden-state-router-for-0-5b-to-3b-local-cascade-8405793743cf` | `promising_if_scaled` |  |  |
| `hierarchical-anchor-kv-cache-with-tiered-compression-3393410f60ab` | `useful_signal` |  |  |
| `hierarchical-landmark-memory-with-bounded-o-sqrt-n-state-71d6a457f6b2` | `promising_if_scaled` |  |  |
| `hierarchical-memory-tokens-for-long-context-with-exact-anchor-ledger-8926a3c04282` | `useful_signal` |  |  |
| `hierarchical-shrinkage-local-cascade-gates-for-selective-r-18b0ed1fac` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `home-quorum-ledger-for-small-agent-swarms-16bf644875c9` | `useful_signal` |  |  |
| `human-llm-paraphrase-memory-grounding-with-semantic-retrie-312e6bb9b1` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `hybrid-adam-with-spectral-second-moment-compression-8164ad3e08` | `useful_signal` |  |  |
| `hybrid-low-rank-first-moment-with-diagonal-second-moment-r-da1ee9f5fe` | `useful_signal` |  |  |
| `hybrid-raw-context-plus-evidence-ledger-abstention-gate-0d6d88f6a0` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `hybrid-semantic-gradient-text-coresets-against-strong-sema-9e9439faf7` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `identity-biased-kv-trace-gates-with-measured-skip-savings-19e057074e` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `in-context-n-gram-speculative-decoding-without-draft-model-vram-5217fe32082a` | `useful_signal` |  |  |
| `incremental-key-anchor-kv-cache-serving-validation-be5111575d` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `incremental-merkle-kv-ledger-on-real-agent-traces-663a492842` | `useful_signal` |  |  |
| `independent-calibration-undertrained-proxy-gradient-verifi-1c467e6bea` | `useful_signal` |  |  |
| `independent-label-evaluation-of-evidence-audit-rewards-on-08b7d9eb85` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `instrumented-serving-replay-for-learned-kv-offload-admissi-504dcc1afb` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `int4-kv-residual-window-validation-with-measured-memory-an-6c4762396d` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `integrated-commit-reveal-audit-on-a-real-gpt-2-small-train-44f22cfc92` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `internal-kv-cache-anchors-versus-prompt-token-anchors-on-e-55a2892ad1` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `kv-cache-aware-context-n-gram-drafting-on-modern-long-cont-bfd9174b02` | `useful_signal` |  |  |
| `kv-cache-benchmark-for-in-context-n-gram-speculative-decod-4aaa12c32d` | `useful_signal` |  |  |
| `kv-cache-int3-with-fp16-residual-window-b9e2348ca149` | `useful_signal` |  |  |
| `kv-cache-offload-router-for-multi-turn-local-serving-639041a0dcc9` | `useful_signal` |  |  |
| `kv-cache-prompt-suffix-lookahead-on-natural-long-context-c-6364cf9a9c` | `useful_signal` |  |  |
| `kv-cache-suffix-array-drafting-for-vram-free-speculative-decoding-503b4aedb46f` | `promising_if_scaled` |  |  |
| `kv-cache-suffix-history-speculative-decoding-on-mixed-prom-9c482497e8` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `kv-cache-suffix-tree-speculative-decoding-dd2b477dffaa` | `useful_signal` |  |  |
| `langgraph-adapter-rollback-ledger-under-randomized-crash-a-b627e5b7ef` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `layer-and-objective-sweep-for-gpt-2-self-speculative-inter-feb8826fcb` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `layerwise-and-multi-layer-direct-fidelity-residual-substit-5e515aa9cc` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `learned-anchor-router-for-exact-kv-retrieval-edc371259c` | `useful_signal` |  |  |
| `learned-hierarchical-landmark-memory-on-structured-long-co-2088665316` | `promising_if_scaled` |  |  |
| `learned-latent-kv-slots-versus-parameter-matched-prompt-to-5eccd0e9ee` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `learned-pre-attention-commitment-masks-for-trace-driven-la-d315aeeda5` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `learned-reuse-prediction-for-kv-cache-offload-admission-4d483f575e` | `useful_signal` |  |  |
| `ledger-constrained-decoding-for-tool-truthfulness-in-1b-agents-bdf902b9d85e` | `promising_if_scaled` |  |  |
| `live-agent-integration-replay-test-for-signed-tool-path-re-428259d2c6` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `live-agent-runtime-signed-provenance-ledger-integration-1b54de2acc` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `live-agent-tool-path-signed-recorder-with-crash-and-concur-d3d8173e93` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `live-append-restart-recovery-for-isolated-ledger-tailing-1e380a0ab2` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `live-llm-agent-failure-recall-with-append-only-evidence-le-aed02f6519` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `live-tool-trace-contradiction-recovery-without-last-mentio-f02b02654c` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `live-tool-trace-evidence-ledger-hallucination-test-33c9e965a2` | `useful_signal` |  |  |
| `llm-agent-natural-language-evidence-ledger-counterexample-32dadf6f5e` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `local-agent-evidence-ledger-with-cryptographic-task-provenance-f5ba7e47f3f2` | `useful_signal` |  |  |
| `long-context-copy-heavy-prompt-n-gram-speculative-decoding-9afd8b765d` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `long-context-model-integrated-candidate-ranking-for-cache-61d531a365` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `longer-streaming-real-trace-anchor-cadence-validation-for-1df80410a4` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `lora-early-exit-speculative-decoding-bdf39a1e422b` | `useful_signal` |  |  |
| `lottery-gradient-audits-on-non-iid-federated-benchmarks-d69ad20f01` | `useful_signal` |  |  |
| `low-bit-block-residual-gates-for-2-bit-kv-cache-7b04369b80` | `useful_signal` |  |  |
| `low-rank-adam-optimizer-states-for-tiny-vram-training-9a16be688a20` | `useful_signal` |  |  |
| `low-rank-factored-adam-states-with-adaptive-rank-selection-fbfbd0edbec7` | `useful_signal` |  |  |
| `low-rank-residual-channels-for-sub-2-bit-weight-quantization-9d2dbe9c0188` | `useful_signal` |  |  |
| `manually-audited-semantic-multi-trace-verification-for-rea-04d2330f8a` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `mass-aware-exact-anchor-clustered-kv-cache-decoding-on-gpt-22c14bdcc3` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `measure-real-kv-cache-layer-pipelined-early-exit-self-spec-c320042ad6` | `useful_signal` |  |  |
| `medium-benchmark-of-executable-validation-on-llm-authored-0d662e79ce` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-confirmation-of-activation-selected-residual-channe-8da773aa9f` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-confirmation-of-direct-trace-auditing-on-multi-clai-12114ef815` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-confirmation-of-flop-matched-length-curriculum-with-46f1ae376e` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-confirmation-of-small-large-lm-entropy-cascade-rout-d1012a5de3` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-decode-quality-validation-for-anchor-preserved-low-9e00fc5c08` | `useful_signal` |  |  |
| `medium-direct-confirmation-of-uncertainty-routed-cascades-72a499b232` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-gpt-2-class-residual-split-q3-w-a-confirmation-658dc44fcb` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-kv-cache-benchmark-for-prompt-n-gram-speculative-de-83b47bbef2` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-lottery-gradient-audit-confirmation-on-femnist-and-690ec03534` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-multi-corpus-cross-instance-evidence-verification-9ea0827de6` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-multi-model-contradiction-recovery-confirmation-43a57b2c44` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-multi-seed-key-addressed-anchorslot-kv-cache-confir-5cace3d1df` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-natural-long-context-validation-of-anchor-gated-kv-913bb4d635` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-neural-gradient-confirmation-for-distribution-prese-5ec91d2b4f` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-neural-shard-lottery-validation-under-adaptive-shar-ee7572f07e` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-non-iid-adaptive-validation-of-commit-reveal-volunt-7a8e1754ac` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-real-agent-provenance-ledger-integration-benchmark-c8aa9f7b11` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-real-kv-anchor-router-benchmark-73c2329123` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-real-lm-benchmark-for-confidence-gated-anchor-kv-ev-faabe119e5` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-real-task-repeated-vs-one-shot-hidden-volunteer-gra-0dd61c3177` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-real-trace-confirmation-for-evidence-ledger-auditin-3817c20ac4` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-scale-commit-reveal-replay-auditing-on-a-larger-opt-dd9c25b0da` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-scale-robustness-benchmark-for-hidden-canary-gradie-482e5b4759` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-tokenized-gpt-confirmation-of-low-rank-residuals-fo-e57c48b774` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-transformer-validation-of-neural-chunk-commitment-u-0962eea1a9` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-validation-of-deployable-ppl-uncertainty-gates-for-05dff99f7d` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `memory-accurate-gpt-2-small-class-validation-of-2-bit-kv-r-c2fef5b828` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `merkle-shard-commitments-for-data-poisoning-detection-486ee43d8a60` | `useful_signal` |  |  |
| `merkle-trajectory-ledger-to-detect-reward-hacking-in-local-ppo-agents-08438f0bd9f8` | `useful_signal` |  |  |
| `merkleized-kv-ledger-for-local-agent-integrity-86296c8425e9` | `useful_signal` |  |  |
| `model-generated-copy-suffix-localization-with-controlled-e-b7a81ba63a` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `model-generated-ledger-trace-replay-validation-a5474fed54` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `model-integrated-cache-aware-n-gram-drafting-on-code-and-r-16dea29f32` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `multi-anchor-exactness-under-restricted-retrieval-queries-487403b40e` | `useful_signal` |  |  |
| `multi-model-hakv-inference-fidelity-robustness-at-25--rete-563c210425` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `multi-model-held-out-exact-anchor-ledger-replay-on-real-ag-d3dd4b6cc9` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `multi-model-live-agent-validation-of-evidence-ledger-rollb-2bafcbdb12` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `multi-model-semi-real-evidence-ledger-hallucination-eval-36c7076304` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `multi-model-true-document-anchor-kv-retention-validation-5578b6c16f` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `multi-pair-fixed-answer-confidence-cascade-validation-b89dbd4689` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `multi-trace-evidence-ledger-verification-on-real-agent-fin-e0f0c3182b` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `multi-trace-external-witness-validation-for-anchored-merkl-600a7b18f0` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `mutable-state-rollback-via-evidence-ledger-snapshots-2d404a46c6ec` | `useful_signal` |  |  |
| `native-evidence-ledger-poisoning-with-live-replay-agent-f76af5924e` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `natural-corpus-anchor-kv-retention-against-non-recency-con-14801e439d` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `natural-corpus-multi-anchor-exactness-with-coverage-rerank-01615747c2` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `natural-corpus-paraphrase-memory-grounding-with-equal-budg-d480d2d7bc` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `natural-evidence-claim-ledger-audit-with-independent-verif-071314f2ad` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `natural-language-agent-benchmark-for-evidence-ledger-rollb-a18e2d5755` | `useful_signal` |  |  |
| `natural-tool-trace-ledger-react-with-independent-semantic-609daf2f66` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `naturalistic-copy-suffix-localization-without-explicit-quo-bc04d2807a` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `naturalistic-paraphrase-memory-grounding-with-end-to-end-a-45f563a044` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `neural-chunk-commitment-gradient-validation-under-adaptive-735638b6db` | `useful_signal` |  |  |
| `neural-multiclass-cascade-validation-for-calibrated-entrop-91c266152d` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `neural-ppo-field-ablated-merkle-audit-reproduction-6ac380c201` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `neural-semantic-detector-ablation-for-signed-shard-paraphr-33d651ac24` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `nli-llm-evidence-ledger-jury-on-multi-dataset-fact-qa-3a7448a8d6` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `noise-robust-gradient-lottery-for-volunteer-selection-86515f50eb` | `useful_signal` |  |  |
| `noisy-transaction-extraction-for-verifier-repaired-ledger-f7246743e3` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `nonlinear-adapter-hidden-volunteer-repetition-under-fresh-4fe051b828` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `nonlinear-residual-predictor-optimized-for-direct-cache-su-dd938b3461` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `nonlinear-shared-gradient-proxy-verifier-confirmation-15238b296a` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `online-isolated-ledger-tailing-during-live-multi-turn-tool-d1913d050e` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `online-suffix-history-drafter-in-a-real-speculative-decodi-6c8536a3c2` | `useful_signal` |  |  |
| `optimized-exact-cache-path-for-gpt-2-intermediate-head-sel-0692caf722` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `optimized-long-context-real-kv-anchor-router-benchmark-e4b7adedbe` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `optimized-persistent-merkle-kv-ledger-with-crash-restart-a-9dcce7bc1b` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `optimized-suffix-copy-speculative-decoding-across-corpora-ad6443df25` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `optimized-suffix-copy-speculative-decoding-on-repetitive-r-9772305176` | `useful_signal` |  |  |
| `organic-llm-authored-multi-source-evidence-ledger-validati-f6e85c3c36` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `organic-llm-authored-public-data-evidence-ledger-validatio-bc531a9fd7` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `outlier-channel-residual-for-2-bit-weights-2dc3ba49138c` | `promising_if_scaled` |  |  |
| `outlier-residual-extreme-quantization-with-principled-channel-split-f74f06ce6f54` | `useful_signal` |  |  |
| `packed-int2-kv-residual-window-validation-with-measured-me-c114b1bd71` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `parameter-matched-and-regularized-residualfp-fast-path-tes-fa722443e9` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `parameter-matched-residual-channel-2-bit-gpt-proxy-with-pa-6568574932` | `promising_if_scaled` |  |  |
| `paraphrased-llm-agent-memory-grounding-benchmark-8e4fcaa0b9` | `useful_signal` |  |  |
| `per-layer-attention-only-versus-adaptive-hakv-retention-at-9f783e5b95` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `per-seed-noninferiority-test-for-confidence-router-cascade-2a5353e1a8` | `useful_signal` |  |  |
| `persisted-multi-process-witness-validation-for-anchored-ag-c8419f5d56` | `useful_signal` |  |  |
| `pointer-head-small-transformer-test-for-exact-anchor-ledge-306a5a9bd4` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `position-weighted-multi-hot-objective-for-token-superposition-24789cd22f88` | `promising_if_scaled` |  |  |
| `post-mask-recovery-validation-for-gpt-2-bpe-residual-chann-17140c408e` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `ppl-gated-cascade-without-direct-kv-reuse-a7b1bbb685` | `promising_if_scaled` |  |  |
| `ppl-gated-local-cascade-with-kv-handoff-92f25ad19b9a` | `promising_if_scaled` |  |  |
| `practical-randomized-svd-hybrid-spectral-adamw-on-small-tr-e7c4eede14` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `pre-registered-conservative-confidence-router-validation-o-00e10bbdac` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `prefetch-aware-pytorch-dataloader-replay-state-for-multi-w-a94886129a` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `pretrained-small-lm-anchor-indexed-kv-cache-validation-5e2a72d80e` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `process-kill-rollback-ledger-validation-with-external-serv-9a2fc1f56f` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `process-kill-sqlite-wal-quorum-cleanup-under-concurrent-re-4b10ee88e8` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `process-level-exact-anchor-resume-in-a-1000-step-tool-usin-38fce41f14` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `production-baseline-crash-campaign-for-incremental-merkle-46d4f04fc4` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `production-cache-prompt-local-copy-speculative-decoding-on-5f15be9656` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `production-style-copy-on-write-kv-suffix-history-speculati-3ee4d280af` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `production-style-persistent-external-anchor-ledger-under-c-0a4f581633` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `production-trace-provenance-ledger-validation-against-matu-84b6cf9286` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `production-trace-strict-n-gram-drafting-cpu-serving-valida-6d3078dd22` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `profiler-matched-text-retrieval-length-curriculum-c00fda505f` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `programmatic-isolated-ledger-on-real-multi-turn-tool-use-t-ca0d2c557e` | `useful_signal` |  |  |
| `prompt-complexity-router-for-local-model-cascades-f709678185e6` | `useful_signal` |  |  |
| `prompt-derived-suffix-array-speculation-f9881c3f20d0` | `useful_signal` |  |  |
| `prompt-lookahead-suffix-array-speculative-decoding-8fb428b32e13` | `useful_signal` |  |  |
| `proof-of-useful-work-gradient-validation-for-volunteer-swarms-a1ad1c5709a9` | `useful_signal` |  |  |
| `prototype-hybrid-snapshot-plus-evidence-ledger-rollback-in-19becd2e73` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `proxy-model-gradient-alignment-checks-for-volunteer-verification-64faedf9ba57` | `useful_signal` |  |  |
| `rank-anchor-frontier-for-quality-bounded-low-rank-kv-compr-4a9a64cb1e` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-agent-evaluation-of-evidence-ledger-rollback-benchmar-138960146a` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-agent-evidence-bound-ledger-hallucination-audit-15a45b1385` | `useful_signal` |  |  |
| `real-agent-provenance-ledger-integration-and-robustness-be-0c7f3a1d75` | `useful_signal` |  |  |
| `real-agent-runtime-batched-signed-provenance-ledger-integr-7e80aea690` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-agent-trace-replay-evidence-ledger-poisoning-validati-cd96859f9d` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-agent-trace-validation-for-anchored-merkleized-action-9d76338a65` | `useful_signal` |  |  |
| `real-corpus-cross-instance-evidence-verification-81ee601954` | `useful_signal` |  |  |
| `real-corpus-medium-validation-for-streamed-adam-moment-sto-3a0d2e995a` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-dataset-small-model-evidence-ledger-jury-benchmark-4e95f7d83d` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-fl-validation-of-commit-reveal-volunteer-training-c9fdba9e03` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-framework-deterministic-replay-with-dataloader-state-7b6cf748c0` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-kv-activation-test-for-exact-anchor-sparse-landmark-p-03f0f23aca` | `useful_signal` |  |  |
| `real-kv-anchor-selection-for-long-context-recall-6b026f5518` | `useful_signal` |  |  |
| `real-kv-anchors-on-a-competent-learned-recall-model-1b68c0de0b` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-llm-tool-agent-provenance-ledger-validation-with-conc-e05539bbf7` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-llm-tool-trace-ledger-verification-under-constrained-3b450fcc17` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-llm-trace-validation-for-exact-kv-cache-suffix-drafti-c464a99207` | `useful_signal` |  |  |
| `real-lm-confidence-gated-anchor-kv-eviction-cc5be8c44e` | `useful_signal` |  |  |
| `real-lm-hidden-state-shuffled-error-validation-for-router-57eb325275` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-model-hakv-inference-fidelity-on-small-pretrained-tra-d8a4514144` | `useful_signal` |  |  |
| `real-model-int3-kv-cache-with-online-attention-history-fp1-a957bb51dd` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-model-kv-trace-replay-for-content-aware-anchor-compre-91cf91e29c` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-report-validation-of-trace-specific-gains-in-multi-cl-afbbf95ada` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-runtime-signed-provenance-ledger-evaluation-for-agent-f56187a255` | `useful_signal` |  |  |
| `real-runtime-vram-aware-cascade-replay-with-small-local-mo-2f77d39ff5` | `useful_signal` |  |  |
| `real-serving-calibration-for-learned-kv-offload-admission-b385fd3a41` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-small-lm-kv-trace-test-for-2-bit-residual-block-gates-f8490ab41d` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-small-model-evidence-ledger-jury-benchmark-0ba0c258c3` | `promising_if_scaled` |  |  |
| `real-task-severe-scarcity-nonlinear-adapter-validation-2e407b5048` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-text-convergence-validation-for-gpt-2-small-factored-f2435c231e` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-text-exact-anchor-compression-confirmation-9611f5ce6a` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-text-exact-token-qwed-selection-with-loss-guardrail-f8e8bdcace` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-text-flop-matched-length-curriculum-for-gpt-2-small-c-81bbe3db88` | `useful_signal` |  |  |
| `real-text-storage-matched-residual-channel-binary-mlp-swee-8c0ef44583` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-token-gpt-2-small-4-gib-blockwise-adamw-validation-bcd8476f2b` | `useful_signal` |  |  |
| `real-tool-agent-harness-evaluation-for-ledger-constrained-ea106e457e` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-trace-evidence-ledger-evaluation-for-tool-use-agents-a583987517` | `useful_signal` |  |  |
| `real-trace-restart-recovery-for-isolated-ledger-tailing-422e23e008` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-trace-validation-of-append-only-failure-evidence-ledg-e2a52d3d02` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-transformer-anchor-preserved-kv-cache-evaluation-fff3f43dd3` | `promising_if_scaled` |  |  |
| `real-transformer-validation-of-anchor-gated-kv-eviction-un-0d6b8b6de9` | `promising_if_scaled` |  |  |
| `recency-first-int3-kv-cache-fp16-exceptions-d11940a3d7` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `recency-protected-draft-scored-kv-eviction-38a039467f` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `recorded-agent-tool-trace-contradiction-recovery-benchmark-ceac3cc2cf` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `redundant-small-agent-jury-with-evidence-ledgers-b9ea9ef9d440` | `useful_signal` |  |  |
| `repeated-hidden-validation-for-multi-step-volunteer-gradie-74b77e99c3` | `useful_signal` |  |  |
| `replay-evidence-ledger-poisoning-on-real-stored-agent-trac-ef8b48b380` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `replicated-hybrid-snapshot-versus-evidence-ledger-rollback-99d01e65ab` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `rerank-attention-trace-successor-candidates-for-speculativ-c95d7d1685` | `useful_signal` |  |  |
| `residual-calibrated-kv-adapter-with-acceptance-router-f7d9a81091` | `useful_signal` |  |  |
| `residual-channel-1-58-bit-gpt-2-with-fp16-error-diffusion-10d18541d8ff` | `useful_signal` |  |  |
| `residual-channel-2-bit-gpt-2-small-pretraining-36993888df3a` | `useful_signal` |  |  |
| `residual-channel-preservation-on-real-bpe-tokenizations-6d45bd8b4c` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `residual-channel-selection-on-top-of-gptq-awq-style-2-bit-7a72c2c121` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `residual-nonlinear-activation-verifier-with-actual-verifie-458ccb1b76` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `residual-preserving-1-bit-bottleneck-with-dense-bypass-gat-523376c000` | `useful_signal` |  |  |
| `residual-rank-and-initialization-ablation-for-ternary-gpt-8ce25888d5` | `useful_signal` |  |  |
| `residual-soft-hidden-state-router-for-local-lm-specialists-46a55506cc` | `useful_signal` |  |  |
| `residualfp-channels-in-a-tiny-transformer-language-model-deadf0804b` | `useful_signal` |  |  |
| `residualfp-extreme-1-bit-weights-with-principled-fp16-residual-channels-eb9b28f112e3` | `useful_signal` |  |  |
| `retrievalgroundedagentmemory-35aeea5b7ed9` | `useful_signal` |  |  |
| `richer-calibration-for-entropy-routing-on-multiclass-casca-c34659b1bc` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `risk-controlled-local-cascade-gates-with-conformal-abstent-2c67ea84c6` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `robust-1024-token-mass-aware-kv-pooling-validation-with-op-8232bd5bcc` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `robust-3-bit-activation-weight-residual-split-validation-cf24b41197` | `useful_signal` |  |  |
| `robust-aggregation-for-low-cost-verifiable-gradient-lotter-5aa4c01151` | `useful_signal` |  |  |
| `robust-commit-reveal-gradient-validation-with-public-refer-e07a20a294` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `robust-logprob-confidence-scores-for-qwen2-5-coder-cascade-75c3d70e9f` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `robust-residual-channel-preservation-with-tokenizer-lm-and-50ca57b25e` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `rollback-ledger-for-tool-use-agents-d6033c25f3ec` | `useful_signal` |  |  |
| `rollback-ledger-with-tiny-learned-error-detector-560e1d9acda5` | `promising_if_scaled` |  |  |
| `router-calibrated-kv-adapter-with-cache-integrated-error-f-41199327e2` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `routing-knowledge-ablation-for-neural-shard-lottery-robust-79097af03f` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `second-moment-stabilization-for-blockwise-stochastic-int8-7ed4b8a6da` | `useful_signal` |  |  |
| `segment-aware-masking-for-content-anchor-kv-replay-353c198c3d` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `self-correcting-ledger-for-sub-3b-agent-reasoning-9768cc0647f2` | `useful_signal` |  |  |
| `self-speculative-decoding-via-early-exit-and-shared-kv-cache-873b78e674fe` | `useful_signal` |  |  |
| `self-speculative-decoding-via-layer-early-exit-drafting-adecf224dc1a` | `useful_signal` |  |  |
| `self-speculative-decoding-via-layer-pipelined-early-exit-3a34fb6b1278` | `useful_signal` |  |  |
| `shared-weight-early-exit-speculative-decoding-7ad97d5cfa22` | `useful_signal` |  |  |
| `shuffled-error-and-multi-layer-validation-for-router-calib-2ce5778d6c` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `signed-observation-recorder-for-real-agent-evidence-ledger-873e746277` | `useful_signal` |  |  |
| `signed-recorder-on-real-multi-step-agent-tool-traces-3d0cea7dba` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `signed-shard-commitments-plus-semantic-scanner-for-pre-tra-6fd21fc80e` | `useful_signal` |  |  |
| `small-lm-direct-kv-intervention-for-exact-anchors-plus-log-98b1dc3c48` | `useful_signal` |  |  |
| `small-lm-ledger-grounded-react-with-non-oracle-source-chec-7a6ac865ed` | `useful_signal` |  |  |
| `small-model-kv-cache-suffix-drafting-latency-test-2316475335` | `useful_signal` |  |  |
| `small-transformer-adapter-validation-for-residual-preservi-dfbb836955` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `small-transformer-anchor-indexed-kv-cache-evaluation-3f4864c38c` | `useful_signal` |  |  |
| `small-transformer-confirmation-for-hybrid-spectral-adam-a484f816b0` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `small-transformer-kv-trace-replay-for-entropy-gated-exact-882d894cb9` | `useful_signal` |  |  |
| `small-transformer-perplexity-test-for-gradient-informed-re-53132be3e8` | `useful_signal` |  |  |
| `small-transformer-qa-test-for-exact-anchor-ledger-retrieva-30ed3725d5` | `useful_signal` |  |  |
| `small-transformer-shard-dropout-versus-routing-knowledge-a-22ae468db7` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `small-transformer-validation-of-sqrt-stabilized-blockwise-c0007cb542` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `sparse-activation-replay-for-byzantine-volunteer-gradient-verification-764c8c457dca` | `useful_signal` |  |  |
| `sparse-paged-execution-for-exact-segment-aware-content-anc-8669d434c6` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `sparse-structured-residual-channels-for-1-bit-quantization-recovery-fcdc80f5e0f8` | `useful_signal` |  |  |
| `spectral-adam-low-rank-optimizer-state-compression-586a5411c2ed` | `useful_signal` |  |  |
| `spectral-residual-decomposition-for-sub-2bit-weight-quantization-5547c307a409` | `useful_signal` |  |  |
| `sqlite-wal-local-quorum-ledger-prototype-b1bdfc12b1` | `useful_signal` |  |  |
| `sqlite-wal-quorum-ledger-with-prepare-commit-cleanup-580bb7741c` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `static-parameter-matched-residual-adapters-for-1-bit-recov-8ee68488ea` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `storage-matched-residual-channel-binary-transformer-ablati-65f8861a0b` | `useful_signal` |  |  |
| `storage-real-gpt-2-small-validation-of-tuned-nonzero-floor-04f091edf4` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `streaming-low-memory-adam-moments-on-a-small-language-mode-306e86668c` | `useful_signal` |  |  |
| `streaming-storage-saving-dplr-floor-adam-versus-adam-and-a-414ba530a2` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `strict-verifier-cpu-n-gram-drafting-serving-test-469c406314` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `structured-compression-objective-for-exact-anchor-retrieva-10ca845b4c` | `useful_signal` |  |  |
| `structured-evidence-ledger-for-tool-use-agents-851634d693f8` | `useful_signal` |  |  |
| `structured-evidence-ledger-reduces-hallucinated-tool-calls-in-small-agents-417a2250bb0c` | `useful_signal` |  |  |
| `structured-ledger-rejection-sampling-for-local-agents-75263160c1cb` | `promising_if_scaled` |  |  |
| `structured-tool-exact-anchor-replay-on-multi-seed-real-cod-28fd3cd21f` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `suffix-array-speculative-drafting-from-generation-history-eaa2278559d2` | `useful_signal` |  |  |
| `suffix-history-speculative-decoding-in-a-real-kv-cache-ser-f44e0013af` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `tail-stabilized-causal-anchor-selection-for-real-kv-landma-ef313763fc` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `tamper-evident-agent-action-ledgers-via-merkleized-kv-fingerprints-2559c9727f37` | `useful_signal` |  |  |
| `tamper-evident-agent-ledger-for-hallucination-detection-eff65c3bc538` | `useful_signal` |  |  |
| `tamper-evident-agent-ledger-via-inline-cryptographic-checksumming-a9735d105002` | `useful_signal` |  |  |
| `ternary-kv-cache-with-residual-error-feedback-for-long-context-c1c50fcb5949` | `useful_signal` |  |  |
| `ternary-weights-plus-per-layer-residual-codebook-recovery-71052a960214` | `promising_if_scaled` |  |  |
| `tiered-exact-anchor-kv-cache-with-cross-layer-compression-7411950a6bc9` | `promising_if_scaled` |  |  |
| `tiny-auditor-evidence-ledger-flags-reduce-agent-hallucinations-e5dcae51d722` | `useful_signal` |  |  |
| `tiny-prompt-router-for-local-1-5b-7b-cascade-9825621b040e` | `useful_signal` |  |  |
| `token-entropy-routed-speculative-decoding-a47708aa33a1` | `useful_signal` |  |  |
| `token-level-gpt-2-latency-test-for-suffix-copy-speculative-4980023e0f` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `token-level-ledger-constrained-decoding-on-1b-tool-agents-f623678536` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `token-level-ledger-constrained-decoding-vs-post-hoc-repair-d687163747` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `token-level-verifier-test-for-prompt-local-copy-speculatio-2c6ef887fd` | `useful_signal` |  |  |
| `token-suffix-speculative-drafting-without-kv-cache-reuse-6f3cc61086` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `token-superposition-for-long-context-anchor-compression-2e427b5fb840` | `useful_signal` |  |  |
| `tokenizer-level-suffix-match-drafter-integrated-with-a-sma-9396e3555b` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `tool-use-ledger-cuts-1b-agent-hallucinations-0bf8f8438dcf` | `useful_signal` |  |  |
| `trace-based-ledger-constrained-decoding-for-1b-tool-agents-8d68ea8865` | `promising_if_scaled` |  |  |
| `trace-driven-learned-kv-offload-admission-under-memory-pre-20fc2b74de` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `trace-driven-paged-kv-anchor-cache-serving-benchmark-5d60334321` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `trace-replay-validation-of-structured-ledger-rejection-sam-d667538718` | `useful_signal` |  |  |
| `train-a-calibrated-gpt-2-intermediate-head-for-self-specul-ab7b7bb3b5` | `useful_signal` |  |  |
| `train-gpt-2-small-early-exit-heads-for-exact-self-speculat-b13407a3ce` | `useful_signal` |  |  |
| `train-real-auxiliary-exit-heads-for-early-exit-speculative-a72b6570f4` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `trainable-dual-memory-anchor-recall-against-parameter-matc-9ba5e67c38` | `promising_if_scaled` |  |  |
| `transformer-scale-residual-hidden-state-router-for-frozen-6d36c9a4d8` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `true-4-gb-capped-fused-dplr-adam-validation-3f2b80a8d7` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `true-femnist-writer-partition-and-longer-cifar-10-lottery-276241cd81` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `true-fused-dynresact-route-scatter-kernel-for-gpt-2-small-b490e7dadf` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `ultra-low-budget-gradient-aware-text-coresets-2e11cea8fe` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `uncertainty-gated-anchor-kv-eviction-across-real-lms-and-c-49749d6603` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `validate-hybrid-snapshot-plus-evidence-ledger-rollback-in-e4cbdfb07e` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `variable-length-pointer-copy-transformer-for-length-robust-62bc618d59` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `variance-guided-data-selection-for-tiny-lm-pretraining-3c3146778b0c` | `useful_signal` |  |  |
| `vectorized-periodic-mass-aware-kv-clustering-budget-sweep-71f10f9e70` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `verifiable-gradient-lottery-for-home-volunteer-training-ceaa3f86f272` | `useful_signal` |  |  |
| `zero-floor-or-percentile-scaled-sqrt-int8-adam-v-state-par-af0d5936b2` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |

## Backfilled exportable

| Project | Outcome | Issues | Backfill |
|---|---|---|---|
| `4-gb-capped-rank-0-factored-optimizer-validation-96f718707f` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `acceptance-aware-gpt-2-small-early-exit-heads-for-exact-se-bc1a42be2d` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `activation-aware-calibration-for-static-residual-adapters-08e1f264dc` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `activation-selected-residual-channels-with-error-aware-2-b-ad5a87cb53` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `actual-head-identity-plus-recency-kv-gating-on-gpt-2-small-2bacb1c6e5` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `adaptive-or-periodically-corrected-low-rank-adamw-for-smal-afbae3b446` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `adaptive-rank-anchor-kv-compression-on-gpt-2-small-class-l-003174ac4a` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `adaptive-training-loop-validation-for-conditional-lottery-e6bb1c9086` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `adversarial-persistence-test-for-incremental-merkle-kv-age-e2048a7490` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `async-or-host-resident-streamed-adamw-backend-in-a-real-tr-5535bfa367` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `batched-larger-model-evidence-ledger-counterexample-sweep-ccaf21822f` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `behavior-aware-learned-kv-residual-prediction-for-exact-an-b76f7664e0` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `blinded-multi-agent-evidence-ledger-counterexample-benchma-eed79744df` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `block-aligned-learned-commitment-masks-for-real-sparse-att-fad58349e8` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `blockwise-stabilized-4-bit-adam-second-moment-on-a-small-t-d75abbd657` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `bounded-full-scale-commit-reveal-replay-auditing-on-a-real-3eddb3740f` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `bounded-full-scale-memory-pressure-validation-for-streamed-6f56b891a0` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `bounded-full-scale-validation-of-nonzero-floor-4-bit-adam-2d840742e7` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `bounded-production-style-strict-n-gram-drafting-cpu-servin-4ef349b27f` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `bounded-scale-gap-validation-of-calibrated-ppl-gates-for-n-08c789374b` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `calibrated-confidence-gated-local-llm-cascade-with-held-ou-b689674c75` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `calibrated-confidence-gates-for-stable-local-cascade-routi-4973719f64` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `calibrated-evidence-ledger-jury-with-larger-real-data-cove-0937d49bc3` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `calibrated-logprob-routing-with-a-stronger-qwen2-5-coder-f-cf6506eb83` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `calibrated-soft-source-diversity-for-cross-corpus-claim-ve-908672b271` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `calibrated-top-k-qwed-interpolation-on-a-second-real-corpu-658f7a5b78` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `calibration-trained-ternary-low-rank-residual-repair-for-g-0e07829031` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `causal-non-oracle-anchor-selection-for-real-kv-landmark-po-09956cac81` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `cheap-ranker-for-cache-aware-n-gram-candidate-selection-26a468c4ec` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `checkpointed-gpt-2-intermediate-kl-heads-for-actual-specul-9042abd5e4` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `cifar-10-calibrated-uncertainty-routed-cascades-with-laten-e93d3deda8` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `claim-ledger-audit-with-strong-independent-nli-verificatio-1b04378348` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `concurrent-atomic-rollback-ledger-recovery-under-external-f4ccb768a5` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `consistency-forced-verifier-repaired-ledger-state-tracking-e378de737a` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `constrained-model-authored-evidence-ledgers-for-sub-1b-qa-9b15f7fcd3` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `constrained-span-candidate-evidence-ledgers-for-sub-1b-qa-41c6554697` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `controlled-residualfp-channel-ablations-in-a-longer-tiny-l-d79bfcfb7c` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `controller-integrated-postgres-langgraph-hard-cutover-faul-77a07dc1a4` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `cost-aware-frozen-confidence-router-with-measured-overhead-787a704188` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `cost-matched-robust-lottery-versus-robust-top-k-at-boundar-ac22ab74d3` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `coverage-constrained-sampled-adamw-recomputation-on-the-sa-04a71608ba` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `cross-device-adamw-sampled-gradient-recomputation-on-a-sma-9de0074913` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `deployment-faithful-witness-gossip-replay-for-non-cancelab-d97c30da6c` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `depth-4-robustness-validation-of-top-k-qwed-interpolation-dc1d13dfd0` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `direct-llm-ledger-trace-replay-validation-8b9e7ec7a2` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `distribution-aware-calibration-for-residual-activation-ver-66be993511` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `durable-concurrent-agent-runtime-provenance-ledger-integra-649a141b48` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `durable-restart-validation-for-anchored-langgraph-checkpoi-9d1f914464` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `efficient-hybrid-low-rank-adamw-update-for-small-lm-traini-c8a1d93ce9` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `end-to-end-adaptive-ticket-routing-for-conditional-lottery-568f77571d` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `end-to-end-anchor-kv-cache-hit-rate-and-amortization-bench-ca58c29fb4` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `end-to-end-causal-tail-mass-landmark-pooling-without-stabi-bfc557c959` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `end-to-end-gpt-2-small-self-speculative-decoding-with-trai-f29c835448` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `end-to-end-prompt-local-copy-speculative-decoding-on-extra-8d842ef544` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `end-to-end-suffix-kv-reuse-in-a-real-speculative-decoding-29999772c3` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `enforced-4-gib-cuda-cap-gpt-2-small-adamw-boundary-test-1b0e42d018` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `entropy-coded-anchor-preprocessing-against-standard-compre-d69ad54fb5` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `equal-cost-adaptive-verifier-on-real-small-transformer-act-0b1d1d6116` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `exactness-audit-for-prompt-lookup-speculative-decoding-72282eb048` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `externally-enforced-ledger-react-with-semantic-source-veri-40002ab1d8` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `free-form-evidence-audit-reward-on-real-tool-agent-summari-c1cf194f11` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `frozen-gpt-2-small-native-kv-intervention-for-anchor-and-l-8d8f96fac8` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `frozen-rule-multi-dataset-confidence-router-package-with-s-626cd501b3` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `full-writer-femnist-sparsity-and-rewinding-gradient-audit-ec8edb7f50` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `fused-gpt-2-small-dynresact-latency-and-metadata-accountin-c5841e0478` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `fused-packed-2-bit-residual-channel-projection-kernel-on-g-d75620eff6` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `fused-real-kv-anchor-router-latency-validation-1c251337a8` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `gate-initialization-and-schedule-ablation-for-binary-resid-0c020311b6` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `generative-local-llm-confidence-cascade-with-actual-server-00a5434e21` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `gpt-2-small-class-bpe-validation-of-functional-ternary-low-b431ffc6df` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `gpt-2-small-class-detached-residual-split-q3-w-a-validatio-d08e69867d` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `gpt-2-small-class-dual-memory-anchor-recall-with-layout-ab-27f0e20420` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `gpt-2-small-class-memory-budget-validation-for-factored-ad-e65a948c12` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `gpt-2-small-class-tokenized-validation-of-sqrt-int8-adam-v-b236358172` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `gpt-2-small-inference-validation-of-key-addressed-anchorsl-2f16602be2` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `gpt-2-small-validation-of-activation-aware-residual-adapte-8a67fa3593` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `gradient-dot-audits-for-label-flip-anomaly-detection-063cd69498` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `hard-unsupported-claim-ledger-audit-across-models-bac6248a0f` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `held-out-adversarial-paraphrase-benchmark-for-hybrid-signe-9f09a96b0c` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `held-out-mbpp-humaneval-confirmation-for-minimum-token-log-13719bee3c` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `held-out-natural-copy-suffix-localization-benchmark-b1acbb1e92` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `held-out-sub-1b-generation-test-for-evidence-ledger-valida-be30b56387` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `hierarchical-shrinkage-local-cascade-gates-for-selective-r-18b0ed1fac` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `human-llm-paraphrase-memory-grounding-with-semantic-retrie-312e6bb9b1` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `hybrid-raw-context-plus-evidence-ledger-abstention-gate-0d6d88f6a0` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `hybrid-semantic-gradient-text-coresets-against-strong-sema-9e9439faf7` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `identity-biased-kv-trace-gates-with-measured-skip-savings-19e057074e` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `incremental-key-anchor-kv-cache-serving-validation-be5111575d` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `independent-label-evaluation-of-evidence-audit-rewards-on-08b7d9eb85` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `instrumented-serving-replay-for-learned-kv-offload-admissi-504dcc1afb` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `int4-kv-residual-window-validation-with-measured-memory-an-6c4762396d` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `integrated-commit-reveal-audit-on-a-real-gpt-2-small-train-44f22cfc92` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `internal-kv-cache-anchors-versus-prompt-token-anchors-on-e-55a2892ad1` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `kv-cache-suffix-history-speculative-decoding-on-mixed-prom-9c482497e8` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `langgraph-adapter-rollback-ledger-under-randomized-crash-a-b627e5b7ef` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `layer-and-objective-sweep-for-gpt-2-self-speculative-inter-feb8826fcb` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `layerwise-and-multi-layer-direct-fidelity-residual-substit-5e515aa9cc` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `learned-latent-kv-slots-versus-parameter-matched-prompt-to-5eccd0e9ee` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `learned-pre-attention-commitment-masks-for-trace-driven-la-d315aeeda5` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `live-agent-integration-replay-test-for-signed-tool-path-re-428259d2c6` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `live-agent-runtime-signed-provenance-ledger-integration-1b54de2acc` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `live-agent-tool-path-signed-recorder-with-crash-and-concur-d3d8173e93` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `live-append-restart-recovery-for-isolated-ledger-tailing-1e380a0ab2` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `live-llm-agent-failure-recall-with-append-only-evidence-le-aed02f6519` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `live-tool-trace-contradiction-recovery-without-last-mentio-f02b02654c` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `llm-agent-natural-language-evidence-ledger-counterexample-32dadf6f5e` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `long-context-copy-heavy-prompt-n-gram-speculative-decoding-9afd8b765d` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `long-context-model-integrated-candidate-ranking-for-cache-61d531a365` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `longer-streaming-real-trace-anchor-cadence-validation-for-1df80410a4` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `manually-audited-semantic-multi-trace-verification-for-rea-04d2330f8a` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `mass-aware-exact-anchor-clustered-kv-cache-decoding-on-gpt-22c14bdcc3` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-benchmark-of-executable-validation-on-llm-authored-0d662e79ce` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-confirmation-of-activation-selected-residual-channe-8da773aa9f` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-confirmation-of-direct-trace-auditing-on-multi-clai-12114ef815` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-confirmation-of-flop-matched-length-curriculum-with-46f1ae376e` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-confirmation-of-small-large-lm-entropy-cascade-rout-d1012a5de3` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-direct-confirmation-of-uncertainty-routed-cascades-72a499b232` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-gpt-2-class-residual-split-q3-w-a-confirmation-658dc44fcb` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-kv-cache-benchmark-for-prompt-n-gram-speculative-de-83b47bbef2` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-lottery-gradient-audit-confirmation-on-femnist-and-690ec03534` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-multi-corpus-cross-instance-evidence-verification-9ea0827de6` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-multi-model-contradiction-recovery-confirmation-43a57b2c44` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-multi-seed-key-addressed-anchorslot-kv-cache-confir-5cace3d1df` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-natural-long-context-validation-of-anchor-gated-kv-913bb4d635` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-neural-gradient-confirmation-for-distribution-prese-5ec91d2b4f` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-neural-shard-lottery-validation-under-adaptive-shar-ee7572f07e` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-non-iid-adaptive-validation-of-commit-reveal-volunt-7a8e1754ac` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-real-agent-provenance-ledger-integration-benchmark-c8aa9f7b11` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-real-kv-anchor-router-benchmark-73c2329123` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-real-lm-benchmark-for-confidence-gated-anchor-kv-ev-faabe119e5` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-real-task-repeated-vs-one-shot-hidden-volunteer-gra-0dd61c3177` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-real-trace-confirmation-for-evidence-ledger-auditin-3817c20ac4` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-scale-commit-reveal-replay-auditing-on-a-larger-opt-dd9c25b0da` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-scale-robustness-benchmark-for-hidden-canary-gradie-482e5b4759` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-tokenized-gpt-confirmation-of-low-rank-residuals-fo-e57c48b774` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-transformer-validation-of-neural-chunk-commitment-u-0962eea1a9` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-validation-of-deployable-ppl-uncertainty-gates-for-05dff99f7d` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `memory-accurate-gpt-2-small-class-validation-of-2-bit-kv-r-c2fef5b828` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `model-generated-copy-suffix-localization-with-controlled-e-b7a81ba63a` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `model-generated-ledger-trace-replay-validation-a5474fed54` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `model-integrated-cache-aware-n-gram-drafting-on-code-and-r-16dea29f32` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `multi-model-hakv-inference-fidelity-robustness-at-25--rete-563c210425` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `multi-model-held-out-exact-anchor-ledger-replay-on-real-ag-d3dd4b6cc9` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `multi-model-live-agent-validation-of-evidence-ledger-rollb-2bafcbdb12` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `multi-model-semi-real-evidence-ledger-hallucination-eval-36c7076304` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `multi-model-true-document-anchor-kv-retention-validation-5578b6c16f` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `multi-pair-fixed-answer-confidence-cascade-validation-b89dbd4689` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `multi-trace-evidence-ledger-verification-on-real-agent-fin-e0f0c3182b` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `multi-trace-external-witness-validation-for-anchored-merkl-600a7b18f0` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `native-evidence-ledger-poisoning-with-live-replay-agent-f76af5924e` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `natural-corpus-anchor-kv-retention-against-non-recency-con-14801e439d` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `natural-corpus-multi-anchor-exactness-with-coverage-rerank-01615747c2` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `natural-corpus-paraphrase-memory-grounding-with-equal-budg-d480d2d7bc` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `natural-evidence-claim-ledger-audit-with-independent-verif-071314f2ad` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `natural-tool-trace-ledger-react-with-independent-semantic-609daf2f66` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `naturalistic-copy-suffix-localization-without-explicit-quo-bc04d2807a` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `naturalistic-paraphrase-memory-grounding-with-end-to-end-a-45f563a044` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `neural-multiclass-cascade-validation-for-calibrated-entrop-91c266152d` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `neural-ppo-field-ablated-merkle-audit-reproduction-6ac380c201` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `neural-semantic-detector-ablation-for-signed-shard-paraphr-33d651ac24` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `nli-llm-evidence-ledger-jury-on-multi-dataset-fact-qa-3a7448a8d6` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `noisy-transaction-extraction-for-verifier-repaired-ledger-f7246743e3` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `nonlinear-adapter-hidden-volunteer-repetition-under-fresh-4fe051b828` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `nonlinear-residual-predictor-optimized-for-direct-cache-su-dd938b3461` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `nonlinear-shared-gradient-proxy-verifier-confirmation-15238b296a` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `online-isolated-ledger-tailing-during-live-multi-turn-tool-d1913d050e` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `optimized-exact-cache-path-for-gpt-2-intermediate-head-sel-0692caf722` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `optimized-long-context-real-kv-anchor-router-benchmark-e4b7adedbe` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `optimized-persistent-merkle-kv-ledger-with-crash-restart-a-9dcce7bc1b` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `optimized-suffix-copy-speculative-decoding-across-corpora-ad6443df25` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `organic-llm-authored-multi-source-evidence-ledger-validati-f6e85c3c36` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `organic-llm-authored-public-data-evidence-ledger-validatio-bc531a9fd7` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `packed-int2-kv-residual-window-validation-with-measured-me-c114b1bd71` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `parameter-matched-and-regularized-residualfp-fast-path-tes-fa722443e9` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `per-layer-attention-only-versus-adaptive-hakv-retention-at-9f783e5b95` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `pointer-head-small-transformer-test-for-exact-anchor-ledge-306a5a9bd4` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `post-mask-recovery-validation-for-gpt-2-bpe-residual-chann-17140c408e` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `practical-randomized-svd-hybrid-spectral-adamw-on-small-tr-e7c4eede14` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `pre-registered-conservative-confidence-router-validation-o-00e10bbdac` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `prefetch-aware-pytorch-dataloader-replay-state-for-multi-w-a94886129a` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `pretrained-small-lm-anchor-indexed-kv-cache-validation-5e2a72d80e` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `process-kill-rollback-ledger-validation-with-external-serv-9a2fc1f56f` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `process-kill-sqlite-wal-quorum-cleanup-under-concurrent-re-4b10ee88e8` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `process-level-exact-anchor-resume-in-a-1000-step-tool-usin-38fce41f14` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `production-baseline-crash-campaign-for-incremental-merkle-46d4f04fc4` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `production-cache-prompt-local-copy-speculative-decoding-on-5f15be9656` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `production-style-copy-on-write-kv-suffix-history-speculati-3ee4d280af` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `production-style-persistent-external-anchor-ledger-under-c-0a4f581633` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `production-trace-provenance-ledger-validation-against-matu-84b6cf9286` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `production-trace-strict-n-gram-drafting-cpu-serving-valida-6d3078dd22` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `profiler-matched-text-retrieval-length-curriculum-c00fda505f` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `prototype-hybrid-snapshot-plus-evidence-ledger-rollback-in-19becd2e73` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `rank-anchor-frontier-for-quality-bounded-low-rank-kv-compr-4a9a64cb1e` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-agent-evaluation-of-evidence-ledger-rollback-benchmar-138960146a` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-agent-runtime-batched-signed-provenance-ledger-integr-7e80aea690` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-agent-trace-replay-evidence-ledger-poisoning-validati-cd96859f9d` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-corpus-medium-validation-for-streamed-adam-moment-sto-3a0d2e995a` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-dataset-small-model-evidence-ledger-jury-benchmark-4e95f7d83d` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-fl-validation-of-commit-reveal-volunteer-training-c9fdba9e03` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-framework-deterministic-replay-with-dataloader-state-7b6cf748c0` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-kv-anchors-on-a-competent-learned-recall-model-1b68c0de0b` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-llm-tool-agent-provenance-ledger-validation-with-conc-e05539bbf7` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-llm-tool-trace-ledger-verification-under-constrained-3b450fcc17` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-lm-hidden-state-shuffled-error-validation-for-router-57eb325275` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-model-int3-kv-cache-with-online-attention-history-fp1-a957bb51dd` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-model-kv-trace-replay-for-content-aware-anchor-compre-91cf91e29c` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-report-validation-of-trace-specific-gains-in-multi-cl-afbbf95ada` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-serving-calibration-for-learned-kv-offload-admission-b385fd3a41` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-small-lm-kv-trace-test-for-2-bit-residual-block-gates-f8490ab41d` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-task-severe-scarcity-nonlinear-adapter-validation-2e407b5048` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-text-convergence-validation-for-gpt-2-small-factored-f2435c231e` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-text-exact-anchor-compression-confirmation-9611f5ce6a` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-text-exact-token-qwed-selection-with-loss-guardrail-f8e8bdcace` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-text-storage-matched-residual-channel-binary-mlp-swee-8c0ef44583` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-tool-agent-harness-evaluation-for-ledger-constrained-ea106e457e` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-trace-restart-recovery-for-isolated-ledger-tailing-422e23e008` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-trace-validation-of-append-only-failure-evidence-ledg-e2a52d3d02` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `recency-first-int3-kv-cache-fp16-exceptions-d11940a3d7` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `recency-protected-draft-scored-kv-eviction-38a039467f` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `recorded-agent-tool-trace-contradiction-recovery-benchmark-ceac3cc2cf` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `replay-evidence-ledger-poisoning-on-real-stored-agent-trac-ef8b48b380` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `replicated-hybrid-snapshot-versus-evidence-ledger-rollback-99d01e65ab` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `residual-channel-preservation-on-real-bpe-tokenizations-6d45bd8b4c` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `residual-channel-selection-on-top-of-gptq-awq-style-2-bit-7a72c2c121` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `residual-nonlinear-activation-verifier-with-actual-verifie-458ccb1b76` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `richer-calibration-for-entropy-routing-on-multiclass-casca-c34659b1bc` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `risk-controlled-local-cascade-gates-with-conformal-abstent-2c67ea84c6` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `robust-1024-token-mass-aware-kv-pooling-validation-with-op-8232bd5bcc` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `robust-commit-reveal-gradient-validation-with-public-refer-e07a20a294` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `robust-logprob-confidence-scores-for-qwen2-5-coder-cascade-75c3d70e9f` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `robust-residual-channel-preservation-with-tokenizer-lm-and-50ca57b25e` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `router-calibrated-kv-adapter-with-cache-integrated-error-f-41199327e2` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `routing-knowledge-ablation-for-neural-shard-lottery-robust-79097af03f` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `segment-aware-masking-for-content-anchor-kv-replay-353c198c3d` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `shuffled-error-and-multi-layer-validation-for-router-calib-2ce5778d6c` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `signed-recorder-on-real-multi-step-agent-tool-traces-3d0cea7dba` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `small-transformer-adapter-validation-for-residual-preservi-dfbb836955` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `small-transformer-confirmation-for-hybrid-spectral-adam-a484f816b0` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `small-transformer-shard-dropout-versus-routing-knowledge-a-22ae468db7` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `small-transformer-validation-of-sqrt-stabilized-blockwise-c0007cb542` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `sparse-paged-execution-for-exact-segment-aware-content-anc-8669d434c6` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `sqlite-wal-quorum-ledger-with-prepare-commit-cleanup-580bb7741c` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `static-parameter-matched-residual-adapters-for-1-bit-recov-8ee68488ea` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `storage-real-gpt-2-small-validation-of-tuned-nonzero-floor-04f091edf4` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `streaming-storage-saving-dplr-floor-adam-versus-adam-and-a-414ba530a2` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `strict-verifier-cpu-n-gram-drafting-serving-test-469c406314` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `structured-tool-exact-anchor-replay-on-multi-seed-real-cod-28fd3cd21f` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `suffix-history-speculative-decoding-in-a-real-kv-cache-ser-f44e0013af` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `tail-stabilized-causal-anchor-selection-for-real-kv-landma-ef313763fc` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `token-level-gpt-2-latency-test-for-suffix-copy-speculative-4980023e0f` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `token-level-ledger-constrained-decoding-on-1b-tool-agents-f623678536` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `token-level-ledger-constrained-decoding-vs-post-hoc-repair-d687163747` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `token-suffix-speculative-drafting-without-kv-cache-reuse-6f3cc61086` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `tokenizer-level-suffix-match-drafter-integrated-with-a-sma-9396e3555b` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `trace-driven-learned-kv-offload-admission-under-memory-pre-20fc2b74de` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `trace-driven-paged-kv-anchor-cache-serving-benchmark-5d60334321` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `train-real-auxiliary-exit-heads-for-early-exit-speculative-a72b6570f4` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `transformer-scale-residual-hidden-state-router-for-frozen-6d36c9a4d8` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `true-4-gb-capped-fused-dplr-adam-validation-3f2b80a8d7` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `true-femnist-writer-partition-and-longer-cifar-10-lottery-276241cd81` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `true-fused-dynresact-route-scatter-kernel-for-gpt-2-small-b490e7dadf` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `ultra-low-budget-gradient-aware-text-coresets-2e11cea8fe` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `uncertainty-gated-anchor-kv-eviction-across-real-lms-and-c-49749d6603` | `promising_if_scaled` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `validate-hybrid-snapshot-plus-evidence-ledger-rollback-in-e4cbdfb07e` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `variable-length-pointer-copy-transformer-for-length-robust-62bc618d59` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `vectorized-periodic-mass-aware-kv-clustering-budget-sweep-71f10f9e70` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |
| `zero-floor-or-percentile-scaled-sqrt-int8-adam-v-state-par-af0d5936b2` | `useful_signal` |  | missing_research_source_lineage; source_records:queue_project_metadata |

## Missing required evidence/fields

| Project | Outcome | Issues | Backfill |
|---|---|---|---|
| _none_ |  |  |  |

## Excluded because paper/corpus

| Project | Outcome | Issues | Backfill |
|---|---|---|---|
| `33ae3677f1c68190ae70e7500c5d92d9` | `` | paper_or_corpus_row |  |
| `343e3677f1c68122b7c2cc6fce46eed7` | `` | paper_or_corpus_row |  |
| `343e3677f1c681359dcfd06f1e39715f` | `` | paper_or_corpus_row |  |
| `343e3677f1c6813db1abd901cc2de78b` | `` | paper_or_corpus_row |  |
| `343e3677f1c6814fbb7fe04c32853c10` | `` | paper_or_corpus_row |  |
| `343e3677f1c681658e6fc0ad56320bf9` | `` | paper_or_corpus_row |  |
| `343e3677f1c6816897ded77cad7776f7` | `` | paper_or_corpus_row |  |
| `343e3677f1c6816bb1d8e27d6a6261f9` | `` | paper_or_corpus_row |  |
| `343e3677f1c6819189eef5403f25fcdc` | `` | paper_or_corpus_row |  |
| `343e3677f1c681a99ba9ed4202d98641` | `` | paper_or_corpus_row |  |
| `343e3677f1c681b9adf5c50c32ffcc30` | `` | paper_or_corpus_row |  |
| `343e3677f1c681c68453cdb4d49ceadd` | `` | paper_or_corpus_row |  |
| `343e3677f1c681ceb67ae65592582540` | `` | paper_or_corpus_row |  |
| `343e3677f1c681cf8e78ce50b14a86b4` | `` | paper_or_corpus_row |  |
| `343e3677f1c681dabc16deb34e24971d` | `` | paper_or_corpus_row |  |
| `343e3677f1c681f0935fc14c3429e78a` | `` | paper_or_corpus_row |  |
| `344e3677f1c68100992cd9c6921a439c` | `` | paper_or_corpus_row |  |
| `344e3677f1c68105887ce0f6e52e13f3` | `` | paper_or_corpus_row |  |
| `344e3677f1c681058c18e1cf53240dce` | `` | paper_or_corpus_row |  |
| `344e3677f1c68108971ee0110d16aea8` | `` | paper_or_corpus_row |  |
| `344e3677f1c6810f870ed8c22164767e` | `` | paper_or_corpus_row |  |
| `344e3677f1c6810f972ec9992d6b2b0b` | `` | paper_or_corpus_row |  |
| `344e3677f1c68116a5e6d9cf68387a55` | `` | paper_or_corpus_row |  |
| `344e3677f1c6811c96f7e46b84c15fd9` | `` | paper_or_corpus_row |  |
| `344e3677f1c6811ca1ebfef680313778` | `` | paper_or_corpus_row |  |
| `344e3677f1c6811fafefeaafc69c49fb` | `` | paper_or_corpus_row |  |
| `344e3677f1c68120bf8bfee01b898d6a` | `` | paper_or_corpus_row |  |
| `344e3677f1c6812b9f07e79d9efc09be` | `` | paper_or_corpus_row |  |
| `344e3677f1c68139829fc3f8b81ff446` | `` | paper_or_corpus_row |  |
| `344e3677f1c6813d8304fac29e0ebee2` | `` | paper_or_corpus_row |  |
| `344e3677f1c6813dbe5ecae2f8b6675a` | `` | paper_or_corpus_row |  |
| `344e3677f1c6814a845bd4259b0995f7` | `` | paper_or_corpus_row |  |
| `344e3677f1c681528c40eeb99d3c1104` | `` | paper_or_corpus_row |  |
| `344e3677f1c681569e42f01b8d7b7ff6` | `` | paper_or_corpus_row |  |
| `344e3677f1c6815791eee64b5b01e294` | `` | paper_or_corpus_row |  |
| `344e3677f1c6815a989eedc2019688dd` | `` | paper_or_corpus_row |  |
| `344e3677f1c6815bbf5fe8cd16abe7f0` | `` | paper_or_corpus_row |  |
| `344e3677f1c6815db2e3ef85b2ca9c33` | `` | paper_or_corpus_row |  |
| `344e3677f1c6816fb222d90f5bd8f145` | `` | paper_or_corpus_row |  |
| `344e3677f1c68172aa1ae2b24c1cdb8f` | `` | paper_or_corpus_row |  |
| `344e3677f1c681749c4cd1ebf846f64c` | `` | paper_or_corpus_row |  |
| `344e3677f1c68174a3cccf7a625e23a0` | `` | paper_or_corpus_row |  |
| `344e3677f1c6817ea601e7300cc1414e` | `` | paper_or_corpus_row |  |
| `344e3677f1c68181b405d8eba427e4b4` | `` | paper_or_corpus_row |  |
| `344e3677f1c681858490c82cfe211203` | `` | paper_or_corpus_row |  |
| `344e3677f1c681858e2dce8df69fd1d7` | `` | paper_or_corpus_row |  |
| `344e3677f1c68185b2e7ca7827fa8fde` | `` | paper_or_corpus_row |  |
| `344e3677f1c68186ba94d00a2ea93713` | `` | paper_or_corpus_row |  |
| `344e3677f1c6818abf8dc24b9ad2f7e0` | `` | paper_or_corpus_row |  |
| `344e3677f1c6818b9744cf067eedefcd` | `` | paper_or_corpus_row |  |
| `344e3677f1c6818ba522c0903e671c1d` | `` | paper_or_corpus_row |  |
| `344e3677f1c681998b5bdcc851326ec2` | `` | paper_or_corpus_row |  |
| `344e3677f1c6819eb5d1e308c7e01082` | `` | paper_or_corpus_row |  |
| `344e3677f1c6819f8262cf26d2d054b8` | `` | paper_or_corpus_row |  |
| `344e3677f1c681a6b089e4363bb508d6` | `` | paper_or_corpus_row |  |
| `344e3677f1c681ab9ff5ecbb8ccbce86` | `` | paper_or_corpus_row |  |
| `344e3677f1c681aea02fd410a244056f` | `` | paper_or_corpus_row |  |
| `344e3677f1c681aeb581d4ff2182ea08` | `` | paper_or_corpus_row |  |
| `344e3677f1c681b3ac65de59ba7747ce` | `` | paper_or_corpus_row |  |
| `344e3677f1c681b3b053e3f90caaf08a` | `` | paper_or_corpus_row |  |
| `344e3677f1c681b6942fc67a1fde5f41` | `` | paper_or_corpus_row |  |
| `344e3677f1c681b8baecc684e77c144c` | `` | paper_or_corpus_row |  |
| `344e3677f1c681b9967aefc0bb0e9fbf` | `` | paper_or_corpus_row |  |
| `344e3677f1c681bfa8c4c927bba7f98e` | `` | paper_or_corpus_row |  |
| `344e3677f1c681c5b503eaaf74548c61` | `` | paper_or_corpus_row |  |
| `344e3677f1c681d09572d90a8d2a1853` | `` | paper_or_corpus_row |  |
| `344e3677f1c681d09b14d4cdf4474467` | `` | paper_or_corpus_row |  |
| `344e3677f1c681d6a5a9d90fcbfcb3ee` | `` | paper_or_corpus_row |  |
| `344e3677f1c681d89671dc2e6635f67b` | `` | paper_or_corpus_row |  |
| `344e3677f1c681da9c3fe9231e6c2c7b` | `` | paper_or_corpus_row |  |
| `344e3677f1c681ddb56cec38e2ad35fd` | `` | paper_or_corpus_row |  |
| `344e3677f1c681e2ba63cb60d5e8543a` | `` | paper_or_corpus_row |  |
| `344e3677f1c681e49905ddf0604ac1eb` | `` | paper_or_corpus_row |  |
| `344e3677f1c681e59bb8eba485f90364` | `` | paper_or_corpus_row |  |
| `344e3677f1c681e7ba44c9bcc84acdc1` | `` | paper_or_corpus_row |  |
| `344e3677f1c681e88d85f06d853f95af` | `` | paper_or_corpus_row |  |
| `344e3677f1c681eda654e9f96466fdc7` | `` | paper_or_corpus_row |  |
| `344e3677f1c681f0bc1ed031d1ad81f7` | `` | paper_or_corpus_row |  |
| `344e3677f1c681f2a942eff1d3c0f5e3` | `` | paper_or_corpus_row |  |
| `344e3677f1c681f38cecc161070fc514` | `` | paper_or_corpus_row |  |
| `344e3677f1c681f6bffdd841c6469c39` | `` | paper_or_corpus_row |  |
| `344e3677f1c681f89078c61479b8a5d0` | `` | paper_or_corpus_row |  |
| `344e3677f1c681f9af4aed7b61bb2873` | `` | paper_or_corpus_row |  |
| `344e3677f1c681f9bd94fc27f0681a53` | `` | paper_or_corpus_row |  |
| `344e3677f1c681fd9e6be9b1577c98a8` | `` | paper_or_corpus_row |  |
| `344e3677f1c681fea3cfd6d369dcdb46` | `` | paper_or_corpus_row |  |
| `34ae3677f1c68103995af8c544810555` | `` | paper_or_corpus_row |  |
| `34ae3677f1c68108b14ae65134119940` | `` | paper_or_corpus_row |  |
| `34ae3677f1c68109b937c21cc0429820` | `` | paper_or_corpus_row |  |
| `34ae3677f1c6810d8203db5025383e49` | `` | paper_or_corpus_row |  |
| `34ae3677f1c6810f96eef0fa6b780220` | `` | paper_or_corpus_row |  |
| `34ae3677f1c6810fa259c9b1e25c80e2` | `` | paper_or_corpus_row |  |
| `34ae3677f1c6811080ddfb8234240d84` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681128590dc15d9f6d4ed` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681139d24da497e346fc9` | `` | paper_or_corpus_row |  |
| `34ae3677f1c68118aa39f9e3056deef7` | `` | paper_or_corpus_row |  |
| `34ae3677f1c6811b8307c4ea910b1c94` | `` | paper_or_corpus_row |  |
| `34ae3677f1c6811fa9b6ff343547a172` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681209c2de6a8095c6c7f` | `` | paper_or_corpus_row |  |
| `34ae3677f1c6812699affbac847675e6` | `` | paper_or_corpus_row |  |
| `34ae3677f1c68132ad5bc495c8c5e6f9` | `` | paper_or_corpus_row |  |
| `34ae3677f1c6813399c1f18d5f44d477` | `` | paper_or_corpus_row |  |
| `34ae3677f1c6813895c4ec43b7b02217` | `` | paper_or_corpus_row |  |
| `34ae3677f1c6813cac16f20c5c83bac3` | `` | paper_or_corpus_row |  |
| `34ae3677f1c6813fa97af30aece225a9` | `` | paper_or_corpus_row |  |
| `34ae3677f1c68146a201f3c785e7b8a3` | `` | paper_or_corpus_row |  |
| `34ae3677f1c6814ca56feba08399f189` | `` | paper_or_corpus_row |  |
| `34ae3677f1c6814f84a6e59ecd5ed2fc` | `` | paper_or_corpus_row |  |
| `34ae3677f1c6814f9103ee35f80aff26` | `` | paper_or_corpus_row |  |
| `34ae3677f1c6814fbd14d648aeac20ac` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681518f7bf81e380f0780` | `` | paper_or_corpus_row |  |
| `34ae3677f1c68153a64dffabdd95f30e` | `` | paper_or_corpus_row |  |
| `34ae3677f1c68153bd3fcdc3d8823120` | `` | paper_or_corpus_row |  |
| `34ae3677f1c68157a585fe37d6f1881a` | `` | paper_or_corpus_row |  |
| `34ae3677f1c6815b8d9cdab97ac7de6c` | `` | paper_or_corpus_row |  |
| `34ae3677f1c6815cb9b4df40b50ca26c` | `` | paper_or_corpus_row |  |
| `34ae3677f1c68161b511e630ed5a6a0e` | `` | paper_or_corpus_row |  |
| `34ae3677f1c68162abd0dda8f93b6cf0` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681639e38da3f3c94831d` | `` | paper_or_corpus_row |  |
| `34ae3677f1c68167a0a9f3fe3df7ff9e` | `` | paper_or_corpus_row |  |
| `34ae3677f1c6816a8e85d67ea136e760` | `` | paper_or_corpus_row |  |
| `34ae3677f1c6816cbabbc12849980507` | `` | paper_or_corpus_row |  |
| `34ae3677f1c6816da75af18ac8a6b5d3` | `` | paper_or_corpus_row |  |
| `34ae3677f1c6816eb353ce701cf3c487` | `` | paper_or_corpus_row |  |
| `34ae3677f1c6816fb2eae1b1c962bcdb` | `` | paper_or_corpus_row |  |
| `34ae3677f1c6817a8f63caebeca868cf` | `` | paper_or_corpus_row |  |
| `34ae3677f1c6817bbf8bdbdf8fe26b14` | `` | paper_or_corpus_row |  |
| `34ae3677f1c6817eb38ef75ba3907e86` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681829eace0ecd2832594` | `` | paper_or_corpus_row |  |
| `34ae3677f1c68187b283c657ccb14b4b` | `` | paper_or_corpus_row |  |
| `34ae3677f1c6819ca335c2565ab5305e` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681a0b477e6823ab74591` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681a48994f81c846a8c63` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681a4be98c2bb79434ee2` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681aa9b1ed20f1bac8191` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681abb6a2e958385d8f88` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681ae987dee5024145afe` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681b0a084f0868d54a756` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681b5919bf2da62617553` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681b5ab58fedb1e2cf178` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681b6a1fccf7ec230d502` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681b79946c47e583e43ba` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681bb894bf578ec19706b` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681c98a1bfd20d182b120` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681c997d8db187f4de23b` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681cb871beeafc5ee683d` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681cbaaaee804d129bbfa` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681ccbc1be5eaa11afac2` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681cdbae7cc83aaf0a433` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681cfa2e4db3f03f506b0` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681cfb8b7dd90be415f23` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681d1931ad384336ff8b3` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681d7a6c9f7aae28bdf55` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681dc993ef48dbb239f63` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681dcba6dd964d2412bc0` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681dd8eabc6d7ecc15970` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681df8e36dbc9cbc34af6` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681e0892cf0b22c4e0df3` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681e0b395d470420d9ad2` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681e49a11f55107cb70aa` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681e79f2adcbb2144246b` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681e8b1cdfb0048ce56cf` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681ea97f3db13171dae16` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681f0ab62cf3062b01912` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681f0bd1ce5af03ae91a2` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681f2ab27e86c496ca7d9` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681f2ab3bcc8e0324f9b6` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681faa6e0f7827752b4e5` | `` | paper_or_corpus_row |  |
| `34ae3677f1c681fe9322edd51b705249` | `` | paper_or_corpus_row |  |
| `34be3677f1c6810d94bbccb1033ffedd` | `` | paper_or_corpus_row |  |
| `34be3677f1c6811bbe48d61378caf5f5` | `` | paper_or_corpus_row |  |
| `34be3677f1c6811fb099f15ea2a94a4a` | `` | paper_or_corpus_row |  |
| `34be3677f1c6813c9990f918a4e1179a` | `` | paper_or_corpus_row |  |
| `34be3677f1c6815a9f29cbbce67b721d` | `` | paper_or_corpus_row |  |
| `34be3677f1c6815eaec6d5eedbdc4648` | `` | paper_or_corpus_row |  |
| `34be3677f1c6815f82abcea244d7d392` | `` | paper_or_corpus_row |  |
| `34be3677f1c6817bbcb7cb0d48048bd7` | `` | paper_or_corpus_row |  |
| `34be3677f1c681959ef9ffc095a8fd20` | `` | paper_or_corpus_row |  |
| `34be3677f1c6819ca38ef342f3c2e8d1` | `` | paper_or_corpus_row |  |
| `34be3677f1c681a0abcfd660be74778c` | `` | paper_or_corpus_row |  |
| `34be3677f1c681bebf8dda40e36b93b1` | `` | paper_or_corpus_row |  |
| `34be3677f1c681d2b98bee54c75ee477` | `` | paper_or_corpus_row |  |
| `34be3677f1c681d4a983dd0c12e414eb` | `` | paper_or_corpus_row |  |
| `34be3677f1c681e0aa50f9ac03ec8743` | `` | paper_or_corpus_row |  |
| `34be3677f1c681e497ddf089b09b0228` | `` | paper_or_corpus_row |  |
| `34be3677f1c681ebbbbbf3b0f6f04102` | `` | paper_or_corpus_row |  |
| `34ce3677f1c6812e93d5f9a573a98992` | `` | paper_or_corpus_row |  |
| `34ce3677f1c681329516d6eca8402554` | `` | paper_or_corpus_row |  |
| `34ce3677f1c6813f965ed6f6b7e323f3` | `` | paper_or_corpus_row |  |
| `34ce3677f1c681469bc9f7e13c412490` | `` | paper_or_corpus_row |  |
| `34ce3677f1c68146ad48f61d20b92f74` | `` | paper_or_corpus_row |  |
| `34ce3677f1c68148851af43e956d8cf1` | `` | paper_or_corpus_row |  |
| `34ce3677f1c6814e8b16d5b674c75674` | `` | paper_or_corpus_row |  |
| `34ce3677f1c68190b58be9e500f809a3` | `` | paper_or_corpus_row |  |
| `34ce3677f1c6819fb1ceda35277fecb6` | `` | paper_or_corpus_row |  |
| `34ce3677f1c681abad36c924d8fa35d1` | `` | paper_or_corpus_row |  |
| `34ce3677f1c681b29408e8c2b3a328d2` | `` | paper_or_corpus_row |  |
| `34ce3677f1c681bbb4e2c2dc30cd047b` | `` | paper_or_corpus_row |  |
| `34ce3677f1c681cbb473c7685ffb838b` | `` | paper_or_corpus_row |  |
| `34ce3677f1c681d293bec0ab2ee09802` | `` | paper_or_corpus_row |  |
| `34ce3677f1c681d48d3aee9b5378cb06` | `` | paper_or_corpus_row |  |
| `34ce3677f1c681e1a636d3e39929280d` | `` | paper_or_corpus_row |  |
| `34ce3677f1c681e38e64d3e905e64429` | `` | paper_or_corpus_row |  |
| `34ce3677f1c681e78dbdd01b67c52385` | `` | paper_or_corpus_row |  |
| `34de3677f1c681318de7c58cd3ed9090` | `` | paper_or_corpus_row |  |
| `34de3677f1c681369725e090daecb983` | `` | paper_or_corpus_row |  |
| `34de3677f1c6816cab88d8a228869569` | `` | paper_or_corpus_row |  |
| `34de3677f1c681798e09d02bc10676b2` | `` | paper_or_corpus_row |  |
| `34de3677f1c68187ab9bfa03f1c80ee1` | `` | paper_or_corpus_row |  |
| `34de3677f1c681918e3bf413d2a66664` | `` | paper_or_corpus_row |  |
| `34de3677f1c6819c8945d090c90febec` | `` | paper_or_corpus_row |  |
| `34de3677f1c681b1b762d8e44d965f14` | `` | paper_or_corpus_row |  |
| `34de3677f1c681c0a7e5e69ffc08e8f0` | `` | paper_or_corpus_row |  |
| `34de3677f1c681fd9335f4123ec2adcd` | `` | paper_or_corpus_row |  |
| `34de3677f1c681fdbf8fc45014057e4f` | `` | paper_or_corpus_row |  |
| `34ee3677f1c68123b52efb4492c9ecac` | `` | paper_or_corpus_row |  |
| `34ee3677f1c68132b1c0f828bb6b6118` | `` | paper_or_corpus_row |  |
| `34ee3677f1c6813394edfc4493def5e2` | `` | paper_or_corpus_row |  |
| `34ee3677f1c68137945bc43bbd8c49d9` | `` | paper_or_corpus_row |  |
| `34ee3677f1c6813a8fd7de53f518d226` | `` | paper_or_corpus_row |  |
| `34ee3677f1c6813d83d7ea14aa31ad92` | `` | paper_or_corpus_row |  |
| `34ee3677f1c6814795d3db9e5bd98020` | `` | paper_or_corpus_row |  |
| `34ee3677f1c68154bf31ea8ee0659836` | `` | paper_or_corpus_row |  |
| `34ee3677f1c68172b42cee4c1588390d` | `` | paper_or_corpus_row |  |
| `34ee3677f1c6817c808dfe50d017765f` | `` | paper_or_corpus_row |  |
| `34ee3677f1c68195814ddfe2a54a3cd0` | `` | paper_or_corpus_row |  |
| `34ee3677f1c6819a9a3af20f5a4951f0` | `` | paper_or_corpus_row |  |
| `34ee3677f1c681a2a9b3f42f8a7a78f6` | `` | paper_or_corpus_row |  |
| `34ee3677f1c681a380e3e7ed49139688` | `` | paper_or_corpus_row |  |
| `34ee3677f1c681b19247e55242080a2f` | `` | paper_or_corpus_row |  |
| `34ee3677f1c681c7a679d3e785b5f118` | `` | paper_or_corpus_row |  |
| `34ee3677f1c681cba177c55ef63e8812` | `` | paper_or_corpus_row |  |
| `34ee3677f1c681d6b965c325fbfc25a6` | `` | paper_or_corpus_row |  |
| `34ee3677f1c681eba829fc0476368e1e` | `` | paper_or_corpus_row |  |
| `34ee3677f1c681ee8b43eece1fb7e3f1` | `` | paper_or_corpus_row |  |
| `356e3677f1c6814eaf84fb31a5e51dd2` | `` | paper_or_corpus_row |  |
| `356e3677f1c68174a9e9c6ee0b7c3721` | `` | paper_or_corpus_row |  |
| `356e3677f1c6817aa5c1ecec951cdd8e` | `` | paper_or_corpus_row |  |
| `356e3677f1c6819daa20e942e0dffc60` | `` | paper_or_corpus_row |  |
| `356e3677f1c681a29b4adfbe3ddc9bbf` | `` | paper_or_corpus_row |  |
| `356e3677f1c681e6b289f63c7c7619c7` | `` | paper_or_corpus_row |  |
| `357e3677f1c681069f81cea3a71804a3` | `` | paper_or_corpus_row |  |
| `357e3677f1c6812e8dd7c28de403acee` | `` | paper_or_corpus_row |  |
| `357e3677f1c68138a086dc952bec0041` | `` | paper_or_corpus_row |  |
| `357e3677f1c6813bb641d2bc9ec9f5f0` | `` | paper_or_corpus_row |  |
| `357e3677f1c681428571c9c61dfe348b` | `` | paper_or_corpus_row |  |
| `357e3677f1c68154b97ee2968a323a6d` | `` | paper_or_corpus_row |  |
| `357e3677f1c6815a81abf96e0909456b` | `` | paper_or_corpus_row |  |
| `357e3677f1c68160806af0c5502ae102` | `` | paper_or_corpus_row |  |
| `357e3677f1c6816aab9ac3ac049ec654` | `` | paper_or_corpus_row |  |
| `357e3677f1c68174ac8edebbeda227ac` | `` | paper_or_corpus_row |  |
| `357e3677f1c68191bc98cae0082260f6` | `` | paper_or_corpus_row |  |
| `357e3677f1c6819d8218c830ef01cc52` | `` | paper_or_corpus_row |  |
| `357e3677f1c681c0a296c76a6dc089f9` | `` | paper_or_corpus_row |  |
| `357e3677f1c681cb9f29f9a5bf30b5fb` | `` | paper_or_corpus_row |  |
| `357e3677f1c681d1a874e1990afabbcf` | `` | paper_or_corpus_row |  |
| `357e3677f1c681e89953d73add4fa5bf` | `` | paper_or_corpus_row |  |
| `357e3677f1c681e9b5fce8a1a29f9069` | `` | paper_or_corpus_row |  |
| `357e3677f1c681eb9d22de3f0da0c94c` | `` | paper_or_corpus_row |  |
| `357e3677f1c681f0a6b5e159c44aad85` | `` | paper_or_corpus_row |  |
| `canonical-positive-smoke-fsm-mask-20260507` | `` | paper_or_corpus_row |  |
| `concurrent-postgres-backed-anchored-langgraph-restart-vali-6072ebb35f` | `useful_signal` | paper_or_corpus_row |  |
| `context-derived-n-gram-trie-speculative-decoding-8eda2cd41f63` | `` | paper_or_corpus_row |  |
| `controlled-lifecycle-drill-20260507t084447z` | `` | paper_or_corpus_row |  |
| `llm-generated-ledger-trace-replay-benchmark-bd1376c064` | `useful_signal` | paper_or_corpus_row |  |
| `natural-corpus-suffix-copy-speculative-decoding-latency-fo-01ca330f56` | `useful_signal` | paper_or_corpus_row |  |
| `subq-ssa-ssm-retrieval-probe-20260506` | `` | paper_or_corpus_row |  |
| `supabase-drill-20260506t143658z` | `` | paper_or_corpus_row |  |
| `supabase-full-runtime-drill-20260506t153855z` | `` | paper_or_corpus_row |  |

## Hard negative or stale

| Project | Outcome | Issues | Backfill |
|---|---|---|---|
| `1-58-bit-residual-channel-routing-for-70b-local-inference-01cb4bc52426` | `` | research_outcome:not_export_status |  |
| `1-58-bit-residual-codebook-fine-tuning-for-4gb-gpus-d16ae2c292e9` | `` | research_outcome:not_export_status |  |
| `1-58-bit-residual-ladder-for-tiny-vram-fine-tuning-f48b7aa81b4e` | `` | research_outcome:not_export_status |  |
| `1-58-bit-ternary-fine-tuning-with-learned-residual-codebook-on-6gb-vram-54ef6c327f06` | `` | research_outcome:not_export_status |  |
| `1-58-bit-ternary-residual-lora-on-4gb-vram-f4015484bb96` | `` | research_outcome:not_export_status |  |
| `1-58-bit-weights-with-learned-full-precision-residual-codebooks-febcf118ea72` | `` | research_outcome:not_export_status |  |
| `1-bit-async-adam-with-cpu-sharded-states-for-sub-8gb-volunteer-nodes-ade1f3eb26f5` | `` | research_outcome:not_export_status |  |
| `1-bit-kv-cache-with-principled-residual-reconstruction-acd703ae3160` | `` | research_outcome:not_export_status |  |
| `1-bit-kv-cache-with-rotating-residual-heads-ee09e3941edf` | `` | research_outcome:not_export_status |  |
| `1-bit-learned-codebook-kv-cache-for-128k-context-on-6gb-vram-de3efd7467f5` | `` | research_outcome:not_export_status |  |
| `1-bit-mamba-with-learned-residual-lattice-77f0de904b89` | `` | research_outcome:not_export_status |  |
| `1-bit-residual-lora-for-tiny-vram-home-fine-tuning-9718378c5eb7` | `` | research_outcome:not_export_status |  |
| `1-bit-weights-with-fp16-residual-channels-for-gpt-2-small-13d9b10a7f0a` | `` | research_outcome:not_export_status |  |
| `1-bit-weights-with-learned-fp4-residual-channels-for-7b-home-inference-70e349e34deb` | `` | research_outcome:not_export_status |  |
| `2-bit-factorized-adam-with-blockwise-error-feedback-for-6gb-fine-tuning-c99c46dbcf57` | `` | research_outcome:not_export_status |  |
| `2-bit-signadam-with-layerwise-lr-for-8gb-1b-param-training-c3aa7ded742f` | `` | research_outcome:not_export_status |  |
| `32ae3677f1c6817aba40cf2de2e195d9` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `343e3677f1c681378d07f31411b49d20` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `343e3677f1c6814ba37df54c741eecc1` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `343e3677f1c6814cad63fdbb809e9e14` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `343e3677f1c6814fb994e9bfb6bfd77b` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `343e3677f1c6815194efc9a7f25fbb25` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `343e3677f1c68151a615d34ccf867dab` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `343e3677f1c68152a9c8eab3604f98f8` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `343e3677f1c68157b8e2ff08e46b9835` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `343e3677f1c6815b9e81ca9c89d0ae2b` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `343e3677f1c681638bc0f34ac358d89d` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `343e3677f1c68178b841fdb8b85870be` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `343e3677f1c6819a9339c8b796354e96` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `343e3677f1c6819da620f321331adae7` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `343e3677f1c681b08107e003b1fae123` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `343e3677f1c681bd8da3eeee3173ebc2` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `343e3677f1c681e2b8f0e57c717ea350` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `343e3677f1c681f1a51adf5137a2f359` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c68103ae90dfb07db392f8` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c6810a883dfda11b2f8fae` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c6810b930ed457e228de23` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c6810d8761e72e82c0d4e6` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c6810d8b3add19c3ca4704` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c68120acb4dc57b8a76efe` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c68122bf93fbf366e5f99a` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c6812380a8f58348050efd` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c68123aa0cdf6fb8bcc5d5` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c6812995e7f98d3fd889a3` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c6812b815cc51240bbbdad` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c6812fb550d498a826a026` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c68132abf0dcf8ffc9398e` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c6813ba7b5f9f01adcffb9` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c68140a2a6ec4414e295ec` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c681449fa2fddd258a52b5` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c68148a43cdd945d7fe277` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c6814ab21ac3f66dce1509` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c6814b99a7c8c21d4c9cd4` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c6814d8052ed44ab017bdf` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c6814d9b90fcd6e9421aaa` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c6814eb061d917061dd649` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c6814eb57ce8c6cd65e4ef` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c68157b20de29c8b94663c` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c6815c8a1bc410bf170a67` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c6816188bdfd975d57b0ae` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c681699dabe79f8fc47b7f` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c6817089f5e4ff7f5e1e7b` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c68170a07cea34b7c2b127` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c68170a705f0984ae0be2c` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c68170b4dbce28568f87fc` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c681718ba2ddfa648eefa0` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c681758705f4a3cd5853a7` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c6817cb0ffddfbccdff0d3` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c6817f9b5bf269ee05c06e` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c6818481b7d44fb9d4771a` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c68188a4dbd142628cb8ac` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c68188a8bcf4d800084cc5` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c6818993ddf91d5cba72e1` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c6818fb74dcba16cf56776` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c68192a186c269ca60f692` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c6819497c4f2b17c2f7aac` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c68195bef6d6235236a423` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c6819b8540c6c205cd4052` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c6819b97dde212f8b4a8b8` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c6819bb2f1eeae919473ac` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c681a39c5af80bc852f8f7` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c681a3be00c06dbd38d41e` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c681a88c1af4d23b529205` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c681a88da1d7257d04d5d9` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c681b191bfc3c07ffb19cf` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c681baa8c7f796f76e41d3` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c681c1beb9e37200ee2b4d` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c681c2be54dd3dafefe220` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c681c58199cc69674eacf9` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c681c6ae63fb25964f8f41` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c681cbbc15f1292509ad7b` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c681cdadf4c3e00057dc7b` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c681d193cbdd476f446970` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c681e08649e4f5f46a5f3d` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c681e08ba8c3693eb663e1` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c681e09f8de45a311d2504` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c681e3b6c8d6358c8bb50c` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c681ecb02ac3a1418a757d` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c681ee92dbdf0ddbe8e970` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c681f2b519e5e31211edd8` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c681fbb329d3ea55a23a29` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c681fc8a3acf651ab3bc3f` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `344e3677f1c681fe8baad01da13c2983` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c681039c4ae3384120f6c0` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c681039deaefd994d2c4dc` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c6810e9168db02de429a31` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c6811494bff2a6f96e14b2` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c68114ae5eda9c34169acd` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c6811bb42ef7dc764781e9` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c6811e8954f0e2758e1417` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c6811e9b2ffa7b788bef44` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c6811eb579f3ad9c800e7d` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c68125a012d9d443bd08ae` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c68127950ad0ae32fcd693` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c68133a780ccba692008ef` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c6813ea7fdddaa9fd09483` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c681499911e78b23f03b60` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c68149ac47c622507a166d` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c6814c8391e8f83b151478` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c6815ea194c656b96bfe51` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c68162b3f0e20eb28b9dd4` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c681768e73cc3f1ef9a7cb` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c68176bb7bd6094c65e64b` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c6817a9da5e61427c27fe6` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c681829a11e296780787ea` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c681848932c4ea5f1c5d1b` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c681868b82ea8888370ea4` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c681889621d586d40701cc` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c6818cb617e24ecec5b5d7` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c6818f9b90e9f53941007f` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c681978355d941e822a999` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c6819797e2ee676a8e63e2` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c681a182d0f63daad963d5` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c681ad8167e5061a064e78` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c681b0809fe86f5a52acca` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c681b4baa4fc8241bd188a` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c681bcb61df121306f4197` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c681bd8e01ee76134b1e20` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c681c18484f5c6e1d86e00` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c681c68320dfa0f3ca6133` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c681d08a35fcee4cb6673f` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c681d58130ff9e3d14bba3` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c681dab9e1e50d92f2d199` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c681dba874eb3c96b51a67` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c681f3a0e4e5955bdf02ee` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c681f7befedb013aea9bf0` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ae3677f1c681fca5fccd8b9b524811` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34be3677f1c68109920be0ec484a4e60` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34be3677f1c6811bacd3e0cab1e4024f` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34be3677f1c6813aa780ecba6bda984b` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34be3677f1c6813bbbcbe78fed8bb6f0` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34be3677f1c68189b461ee0d8c3908e7` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34be3677f1c681959833d0b31e7bb419` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34be3677f1c6819b90e6c3a027e11b3d` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34be3677f1c681abbdcae8ccbebcbf83` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34be3677f1c681ca8418e7bd099bab11` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ce3677f1c6810c9f1be33193bf8f00` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ce3677f1c68112b60ec0a13e839f48` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ce3677f1c6811aa779f322f2301ec4` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ce3677f1c68120a273e322942df843` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ce3677f1c6812e88b8e3b4e091bf74` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ce3677f1c681359df3d1124aa21dbb` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ce3677f1c6813d9194ebdb05ba5cca` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ce3677f1c68159a8c7f05075482827` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ce3677f1c6815fbdcfd9919d2598ae` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ce3677f1c6819ab4b7f7a66b49a8bc` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ce3677f1c6819daceef410761f71f9` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ce3677f1c681b9b80ee4a2338c43f7` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ce3677f1c681bc9125ca463207ee19` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34de3677f1c681069a22f6e9b0dbb50b` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34de3677f1c681109fbcf4be4e1ad3f2` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34de3677f1c6811a9a70cd4a2243a207` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34de3677f1c6811ca836e1f2380a1040` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34de3677f1c68141b109f46746cb446e` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34de3677f1c6818580d7fbfa2b6602b7` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34de3677f1c681958c81cbbaf8d7a6fb` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34de3677f1c6819d9a95d2636b9142cb` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34de3677f1c681b29afcdb0c5aa8d64a` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34de3677f1c681b393b5eb4c5b190058` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34de3677f1c681c18e44e7f1c714eccc` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34de3677f1c681c3a85fea3b0f01fd76` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34de3677f1c681ccb02af5122eefd639` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34de3677f1c681dd965edc1d217dfe1e` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34de3677f1c681ec95dcda5cc1614274` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34de3677f1c681ef900bfe9f7f89a8d0` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ee3677f1c6810b906af71a710a01ae` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ee3677f1c6810c9810d0cf61b1580f` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ee3677f1c681128286c98313af08b4` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ee3677f1c68117b734c1123587caba` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ee3677f1c681428a74d1863dc87dfe` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ee3677f1c68143a14cec47c399e1f5` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ee3677f1c681498526f6db75fc6168` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ee3677f1c681768be8defda8287c01` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ee3677f1c68189a3f9edf8c2607d24` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ee3677f1c681a3a3e5dca0aaf9deaf` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ee3677f1c681a6b023c709a9f65c52` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `34ee3677f1c681bcbdadef50c89c2d38` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `355e3677f1c681ba98eff8e9e863a114` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `356e3677f1c68105b97ac80b9ae265b0` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `356e3677f1c68127a61af05dd6e5c2a5` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `356e3677f1c68162ba40f1e38b313c5d` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `356e3677f1c6816e822ffc1cd43866a9` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `356e3677f1c68186b7ecf3dcb5e391c0` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `356e3677f1c681c782fbcf57f9c3d427` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `357e3677f1c681138c91c6f2bad06c5c` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `357e3677f1c6811a9259d7ef28b712a1` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `357e3677f1c6811ca679c49f2d750c15` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `357e3677f1c6812295fecd04b34df7cd` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `357e3677f1c68124858ef5731555d30a` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `357e3677f1c68131bbb4ecbff72a1541` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `357e3677f1c6813db41bf1a68238fd76` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `357e3677f1c6813e9604c385068632af` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `357e3677f1c68142a355ed342a8a4e6f` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `357e3677f1c68152bd17c0f2ebc26ca4` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `357e3677f1c681589c82fabdd33edca4` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `357e3677f1c68168ba62ebc442fef530` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `357e3677f1c6816d8e40e673cb1d69a9` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `357e3677f1c68176b694d7fd3ec0ed61` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `357e3677f1c68178b7afed9cc699cd23` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `357e3677f1c6817d824be50e3d4e0151` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `357e3677f1c68185a486e63cee3d55c0` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `357e3677f1c68189bfc9ead0d81bfa47` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `357e3677f1c68196bc3ef214b05d3fb4` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `357e3677f1c681aabc97c0e5b50bfe1a` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `357e3677f1c681cc8c7eccb2e272e683` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `357e3677f1c681d8a5deee677418bb67` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `357e3677f1c681dba331d4dad8e3feba` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `357e3677f1c681e0afdecfd76ea09648` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `4-bit-adam-optimizer-states-for-4gb-lora-finetuning-c6268f325c8c` | `` | research_outcome:not_export_status |  |
| `acceptance-cost-user-drafter-spec-decoding-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `activation-aware-residual-directions-for-3-bit-gpt-2-quant-1515e7335a` | `` | research_outcome:not_export_status |  |
| `activation-calibrated-rcc-perplexity-evaluation-3084c221b0` | `` | research_outcome:not_export_status |  |
| `activation-clustered-int2-residuals-20260508-night12` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `activation-drift-galore-qlora-hybrid-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `activation-outlier-residuals-with-layer-wise-reconstructio-13bd0e1c95` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `activation-proof-lora-auditing-for-trustless-home-swarms-e7e1dc5e7e0d` | `` | research_outcome:not_export_status |  |
| `adapter-paged-moe-for-sub8gb-home-models-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `adapter-thrash-detector-20260508-night18` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `adaptive-2-bit-kv-cache-with-residual-attention-heads-df3115b99be4` | `` | research_outcome:not_export_status |  |
| `adaptive-bag-size-curriculum-for-token-superposition-training-95f1fdc75c2a` | `` | research_outcome:not_export_status |  |
| `adaptive-difficulty-router-for-home-model-cascades-09c9c0c82894` | `` | research_outcome:not_export_status |  |
| `adaptive-draft-rejection-for-home-speculative-decoding-1265ccd4a32f` | `` | research_outcome:not_export_status |  |
| `adaptive-kv-critic-for-speculative-verification-20260507` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `adaptive-local-model-cascade-router-9f578b5de4d4` | `` | research_outcome:not_export_status |  |
| `adaptive-n-gram-vs-small-model-draft-router-for-speculative-decoding-7c3893497227` | `` | research_outcome:not_export_status |  |
| `adaptive-residual-channel-routing-with-token-level-gating-arcr-67ef959664c5` | `` | research_outcome:not_export_status |  |
| `adaptive-residual-sideband-1-58-bit-weights-d2235dd7ec5c` | `` | research_outcome:not_export_status |  |
| `adaptive-saliency-anchors-for-compressed-kv-cache-on-train-3c11fca9ed` | `` | research_outcome:not_export_status |  |
| `adaptive-self-speculative-decoding-via-dynamic-layer-exit-178dfeb444cc` | `` | research_outcome:not_export_status |  |
| `adaptive-self-speculative-decoding-with-entropy-gated-early-exit-685a91484cf3` | `` | research_outcome:not_export_status |  |
| `adaptive-transition-rate-conflict-aware-episodic-replay-f7bdd5b8ac` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `adaptive-transition-rate-episodic-replay-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `adaptive-verifier-gating-for-exact-transaction-recovery-9902c12034` | `negative` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `adaptive-withholding-accountability-test-for-commit-reveal-31e9696f2f` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `adversarial-poisoning-of-agent-evidence-ledgers-ec399a9a5cc5` | `` | research_outcome:not_export_status |  |
| `agreement-gated-kv-eviction-20260508-night05` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `anchor-backed-recurrent-memory-failure-followup-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `anchor-compressed-kv-cache-for-exact-long-context-retrieval-520b5c7f0b66` | `` | research_outcome:not_export_status |  |
| `anchor-compressed-kv-cache-for-long-context-eca7b5c42113` | `` | research_outcome:not_export_status |  |
| `anchor-gated-kv-cache-compression-with-exact-recall-points-9e394b646597` | `` | research_outcome:not_export_status |  |
| `anchor-gated-kv-cache-compression-with-exact-retrieval-markers-eb4c6f12916e` | `` | research_outcome:not_export_status |  |
| `anchor-gated-kv-compression-for-exact-long-context-recall-f77a9fbde8b9` | `` | research_outcome:not_export_status |  |
| `anchor-gated-kv-compression-with-exact-retrieval-anchors-099334616888` | `` | research_outcome:not_export_status |  |
| `anchor-gated-kv-compression-with-exact-retrieval-positions-76992948cd29` | `` | research_outcome:not_export_status |  |
| `anchor-gated-selective-kv-retention-for-long-context-compression-0c229355837f` | `` | research_outcome:not_export_status |  |
| `anchor-indexed-compressed-state-for-long-context-retrieval-4031f41bc8d3` | `` | research_outcome:not_export_status |  |
| `anchor-indexed-kv-compression-for-exact-long-context-recall-74dc53aeb4ff` | `` | research_outcome:not_export_status |  |
| `anchor-indexed-kv-compression-with-exact-recall-gates-8f4712459277` | `` | research_outcome:not_export_status |  |
| `anchor-indexed-sparse-kv-compression-for-long-context-274662544e12` | `` | research_outcome:not_export_status |  |
| `anchor-only-local-span-kv-preservation-under-real-streamin-0aa3d8f347` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `anchor-plus-recent-kv-preservation-on-realistic-multi-depe-41fbd3be57` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `anchor-preserved-compressed-kv-cache-for-long-context-inference-89ee96c7c374` | `` | research_outcome:not_export_status |  |
| `anchor-preserving-kv-quantization-for-needle-retrieval-3cb1626f6d5c` | `` | research_outcome:not_export_status |  |
| `anchor-ssm-million-token-memory-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `anchored-checkpoint-ledger-for-real-local-agent-tool-trace-fdb0a38cba` | `` | research_outcome:not_export_status |  |
| `anchored-ledger-recovery-with-independent-repair-archive-6de9385c62` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `anchored-sparse-kv-cache-exact-landmark-tokens-with-inter-anchor-compression-836eed4e9c06` | `` | research_outcome:not_export_status |  |
| `annealed-recovery-schedule-for-token-superposition-training-86c82c37cf62` | `` | research_outcome:not_export_status |  |
| `append-only-evidence-ledger-for-local-tool-use-agents-706011bf2a7f` | `` | research_outcome:not_export_status |  |
| `append-only-evidence-ledger-reduces-unreported-tool-failures-deb1018678ed` | `` | research_outcome:not_export_status |  |
| `append-only-ledger-agent-for-tool-use-consistency-403147f9c5df` | `` | research_outcome:not_export_status |  |
| `arhq-subbit-binary-residual-branch-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `artifact-first-negative-run-summarizer-20260508-night30` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `attention-head-subsampling-draft-for-zero-vram-speculative-decoding-ee15f59aa09e` | `` | research_outcome:not_export_status |  |
| `attention-trace-speculative-drafting-zero-param-draft-from-kv-cache-e0aeb3b57ca1` | `` | research_outcome:not_export_status |  |
| `automatic-counterclaim-ledger-extraction-from-enoch-run-no-1a4ae78c01` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `autotuned-gb10-fused-2-bit-projection-with-end-to-end-resi-b89fe46fb3` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `backend-backed-merkle-rollback-audit-with-switch-threshold-46c3355e93` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `batched-merkle-checkpoint-rollback-audit-without-switch-re-4535df7c26` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `batched-shared-suffix-draft-amortization-benchmark-daa311c13a` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `binary-high-noise-gradient-dot-audit-validation-e89d0bac1f` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `bit-packed-gpu-to-cpu-sharded-adam-training-control-801be58f85` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `bitnet-style-matmul-emulation-20260508-night13` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `block-diffusion-drafter-cache-reuse-20260508-night04` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `block-indexed-residual-codebooks-for-1-58-bit-ternary-quantization-with-0-5-ppl-loss-5ee003e65f72` | `` | research_outcome:not_export_status |  |
| `block-streaming-4-bit-adamw-with-cpu-resident-second-moments-b312e34f0c7e` | `` | research_outcome:not_export_status |  |
| `blockwise-8-bit-adam-with-error-feedback-for-6gb-full-parameter-fine-tuning-f8cf5828fb5f` | `` | research_outcome:not_export_status |  |
| `blockwise-cpu-offloaded-8-bit-adamw-for-12gb-home-gpu-fine-tuning-ed73482d32c2` | `` | research_outcome:not_export_status |  |
| `bounded-direct-volunteer-gradient-replay-harness-aa38cefce0` | `` | research_outcome:not_export_status |  |
| `bounded-full-scale-compressed-volunteer-replay-on-gpt-2-sm-f56480972e` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `bounded-larger-model-recency-residual-int3-kv-cache-valida-0d5af6d8f9` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `bounded-serving-stack-validation-of-cpu-suffix-drafting-b22386e1cc` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `bounded-transformer-lora-test-of-peer-committee-loss-under-6387f37470` | `` | research_outcome:not_export_status |  |
| `byzantine-resilient-home-swarm-ledger-d7fed086d5f5` | `` | research_outcome:not_export_status |  |
| `cache-depth-sentinel-for-compressed-reasoning-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `cache-reuse-early-exit-speculative-decode-benchmark-2ef45d1e4a` | `` | research_outcome:not_export_status |  |
| `cached-gpt-2-small-acceptance-focused-mid-layer-self-specu-10715c0769` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `calibrated-entropy-routing-for-small-large-transformer-cas-b7530d7528` | `` | research_outcome:not_export_status |  |
| `calibrated-residual-scaling-for-sub-2bit-spectral-residual-a0e06fff94` | `negative` | research_outcome:not_export_status |  |
| `calibration-triggered-tiny-vram-adapter-scheduler-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `causal-event-sketch-memory-counterfactual-deletion-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `challenge-batch-proof-for-volunteer-updates-9d6f2edce2d9` | `` | research_outcome:not_export_status |  |
| `challenge-conditioned-response-decoding-for-volunteer-trai-7c6afb4533` | `` | research_outcome:not_export_status |  |
| `cheap-verifier-prefilter-cache-rehydration-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `cheating-resistant-volunteer-gradient-validation-via-sparse-recompute-7393e745e228` | `` | research_outcome:not_export_status |  |
| `checksum-verification-for-tampered-agent-observations-d9a07be83fe7` | `` | research_outcome:not_export_status |  |
| `chunk-reset-or-value-only-residual-feedback-for-ternary-kv-e6b2723c3d` | `negative` | research_outcome:not_export_status |  |
| `cifar-10-100-calibrated-cascades-versus-early-exit-baselin-70b51f666a` | `negative` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `claim-ledger-evidence-byte-budget-20260508-night25` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `coherent-document-chaining-for-long-context-tiny-pretraining-0ff62906709c` | `` | research_outcome:not_export_status |  |
| `collision-rich-natural-query-coverage-reranking-5385d2f257` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `commit-reveal-gradient-nullspace-audit-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `commit-reveal-gradient-validation-for-cheating-resistant-volunteer-training-7ff16ba8d3dd` | `` | research_outcome:not_export_status |  |
| `commit-reveal-gradient-validation-for-volunteer-distributed-training-12ddb2d1e04a` | `` | research_outcome:not_export_status |  |
| `compiler-selected-kv-kernel-policy-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `composable-ssm-state-capsules-for-local-log-memory-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `compressed-binary-append-only-ledger-against-clickhouse-op-d4dbdadad0` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `compressed-multi-process-volunteer-gradient-replay-on-a-la-d51ee722b0` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `compressed-state-memory-with-exact-anchor-index-b6074c2776b5` | `` | research_outcome:not_export_status |  |
| `compressed-state-ring-buffer-with-exact-anchor-overlay-for-infinite-context-312ba20a23a1` | `` | research_outcome:not_export_status |  |
| `compressibility-guided-data-pruning-for-local-pretraining-7838da48b48e` | `` | research_outcome:not_export_status |  |
| `compression-ratio-curriculum-for-tiny-local-pretraining-454482459f7c` | `` | research_outcome:not_export_status |  |
| `conditional-serving-benchmark-for-entropy-versus-confidenc-4d922ee725` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `confidence-gated-mmlu-router-persistence-test-8ccac3744a` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `confidence-gated-shared-suffix-draft-reuse-92b7063bad` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `confidence-gated-suffix-replay-on-code-specialized-prompts-227064412b` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `confidence-routed-three-tier-speculative-cascade-7aba8ae4f368` | `` | research_outcome:not_export_status |  |
| `conflict-aware-episodic-state-replay-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `conflict-indexed-recurrent-memory-map-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `constrained-evidence-ledger-for-sub-3b-agent-self-correction-9521b6d89455` | `` | research_outcome:not_export_status |  |
| `content-addressable-compressed-memory-tokens-895af7bc99d6` | `` | research_outcome:not_export_status |  |
| `content-addressable-episodic-memory-bank-b532b56580d0` | `` | research_outcome:not_export_status |  |
| `content-aware-exact-anchor-kv-selection-86f468adba` | `` | research_outcome:not_export_status |  |
| `context-internal-suffix-array-speculative-decoding-with-sub-1-vram-overhead-befffbc61a24` | `` | research_outcome:not_export_status |  |
| `context-n-gram-cache-drafting-ee34da850e64` | `` | research_outcome:not_export_status |  |
| `context-reuse-n-gram-speculative-drafting-2a16ab1cff3d` | `` | research_outcome:not_export_status |  |
| `context-suffix-speculative-decoding-without-draft-model-vram-d6a67573c06e` | `` | research_outcome:not_export_status |  |
| `contradiction-aware-anchor-pruning-20260508-night07` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `contradiction-triggered-rollbacks-via-evidence-ledgers-e72fdc2d74ee` | `` | research_outcome:not_export_status |  |
| `controller-gate-evaluation-for-counterclaim-ledgers-be8b3da503` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `cost-accounted-tcdrc-on-real-dnn-gradient-traces-4159756617` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `counterclaim-ledger-for-agent-results-20260508-night22` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `counterclaim-minimal-reproducer-evidence-ledger-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `covariance-aware-residual-error-channel-selection-on-real-b844f4c6db` | `` | research_outcome:not_export_status |  |
| `cpu-gpu-mutual-exclusion-cascade-router-eea361126d42` | `` | research_outcome:not_export_status |  |
| `cpu-gpu-speculative-cascade-for-local-inference-c9d4bfa649f8` | `` | research_outcome:not_export_status |  |
| `cpu-offloaded-draft-model-with-pipelined-async-verification-e8216c392903` | `` | research_outcome:not_export_status |  |
| `cpu-offloaded-ultra-quantized-self-draft-speculative-decoding-b1676d00a256` | `` | research_outcome:not_export_status |  |
| `cpu-resident-1-58-bit-self-drafting-for-zero-vram-speculative-decoding-3454c1446a14` | `` | research_outcome:not_export_status |  |
| `cpu-resident-micro-draft-for-zero-vram-speculation-a846e6efc3ac` | `` | research_outcome:not_export_status |  |
| `cpu-suffix-array-agentic-speculative-decoding-03cad8448183` | `` | research_outcome:not_export_status |  |
| `crash-atomic-external-side-effects-versus-langgraph-sqlite-2fbdacb7a7` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `critical-path-evidence-pruning-for-resource-constrained-agent-ledgers-d73d591069cf` | `` | research_outcome:not_export_status |  |
| `critical-path-sparse-evidence-ledger-for-efficient-agent-auditing-39023f2da579` | `` | research_outcome:not_export_status |  |
| `cross-agent-ledger-consensus-for-home-swarms-9064b459caa4` | `` | research_outcome:not_export_status |  |
| `cross-layer-kv-sharing-with-exact-anchor-bypass-7f75d2a0dcd9` | `` | research_outcome:not_export_status |  |
| `cross-model-naturalistic-replication-of-direct-anchor-kv-c-a8ede9ff47` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `cryptographic-gradient-commitment-for-cheating-resistant-volunteer-training-c6a797463732` | `` | research_outcome:not_export_status |  |
| `decision-gate-counterexample-miner-20260508-night31` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `decision-reproducer-fuzzer-for-enoch-gates-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `delta-state-anchor-router-20260507` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `density-first-data-selection-for-sub-billion-pretraining-f87c014c8e72` | `` | research_outcome:not_export_status |  |
| `density-weighted-selection-for-tiny-pretraining-21bc04398713` | `` | research_outcome:not_export_status |  |
| `deterministic-dropout-fingerprinting-for-cheat-resistant-volunteer-gradient-validation-e2abfed2f995` | `` | research_outcome:not_export_status |  |
| `dflash-style-local-block-drafter-distillation-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `differentiable-anchor-memory-bank-07f11a1c3281` | `` | research_outcome:not_export_status |  |
| `direct-cgroup-io-max-validation-of-coalesced-pretokenized-9b1644dc22` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `direct-critical-path-pruning-on-real-agent-trace-ledgers-c4967b240d` | `` | research_outcome:not_export_status |  |
| `direct-federated-nlp-lora-benchmark-for-peer-committee-agg-d11dbd71be` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `direct-femnist-mnist-cnn-hidden-audit-threshold-validation-1add3585a7` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `direct-gpt-2-small-mid-layer-lora-self-speculation-through-bc1de88092` | `` | research_outcome:not_export_status |  |
| `direct-kv-cache-patching-and-robustness-test-for-anchor-ro-849b8e15bd` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `direct-layer-11-reuse-timing-for-early-exit-speculative-de-2fadd14971` | `` | research_outcome:not_export_status |  |
| `direct-llm-dual-trail-failure-prediction-benchmark-1555602946` | `` | research_outcome:not_export_status |  |
| `direct-llm-evaluation-of-evidence-ledger-constrained-agent-0e464cbdcb` | `` | research_outcome:not_export_status |  |
| `direct-llm-test-of-non-oracle-exact-position-kv-compressio-dfeedcda44` | `` | research_outcome:not_export_status |  |
| `direct-local-llm-quantization-tier-router-benchmark-15f5a2938e` | `` | research_outcome:not_export_status |  |
| `direct-local-llm-test-of-density-plus-diversity-corpus-sel-b371164a5f` | `` | research_outcome:not_export_status |  |
| `direct-protocol-test-for-challenge-batch-proofs-on-volunte-d0facb4109` | `` | research_outcome:not_export_status |  |
| `direct-random-projection-gradient-audits-in-a-federated-tr-c9346ba600` | `` | research_outcome:not_export_status |  |
| `direct-serving-benchmark-for-context-suffix-speculative-de-f0806c7578` | `` | research_outcome:not_export_status |  |
| `direct-serving-benchmark-for-cpu-gated-gpu-cascade-7844a4b801` | `` | research_outcome:not_export_status |  |
| `direct-trace-replay-validation-of-agent-evidence-ledger-po-d10f4ee6ce` | `` | research_outcome:not_export_status |  |
| `direct-transcript-validation-for-local-evidence-ledger-cla-c622e5ccdd` | `` | research_outcome:not_export_status |  |
| `direct-transformer-block-swap-training-validation-2eda2efee9` | `` | research_outcome:not_export_status |  |
| `direct-transformer-routing-recall-for-learned-anchor-index-1de9f42715` | `` | research_outcome:not_export_status |  |
| `disagreement-aware-kv-bitplane-compressor-20260507` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `disagreement-sensitive-kv-cache-compressor-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `disagreement-sensitive-sparse-cache-rehydration-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `distributed-consensus-ledger-for-multi-agent-home-swarms-4600f57768b6` | `` | research_outcome:not_export_status |  |
| `distributed-evidence-ledger-for-swarm-agents-on-edge-devices-e54b276baa6d` | `` | research_outcome:not_export_status |  |
| `distributed-falsification-swarm-for-home-agent-safety-fce9b77ad0f1` | `` | research_outcome:not_export_status |  |
| `distributed-gradient-norm-data-selection-for-volunteer-pretraining-616add0382ac` | `` | research_outcome:not_export_status |  |
| `distributed-pytorch-tcdrc-vs-dgc-style-top-k-on-cifar-scal-9db6317e20` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `diversity-curriculum-pretraining-for-sub-1b-models-on-consumer-gpus-22ea6a9fe456` | `` | research_outcome:not_export_status |  |
| `diversity-uncertainty-double-ranking-for-tiny-pretraining-data-selection-a54d633093b5` | `` | research_outcome:not_export_status |  |
| `domain-limited-suffix-retrieval-for-repetitive-decoding-tr-5632fa4b58` | `` | research_outcome:not_export_status |  |
| `draftless-grammar-cache-speculative-decoding-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `dynamic-reachability-labels-for-counterfactual-event-memor-78f9c0dc17` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `early-exit-self-speculative-decoding-162f69e31de3` | `` | research_outcome:not_export_status |  |
| `early-exit-self-speculative-decoding-with-activation-resume-dcbfe19e385f` | `` | research_outcome:not_export_status |  |
| `early-exit-speculative-decoding-873d18fc3785` | `` | research_outcome:not_export_status |  |
| `early-exit-speculative-decoding-via-shared-weights-40b229e726b4` | `` | research_outcome:not_export_status |  |
| `easy-to-hard-curriculum-with-random-mix-consolidation-5b7847f00e` | `` | research_outcome:not_export_status |  |
| `edu-score-data-selection-for-tiny-local-pretraining-4f81015e5f49` | `` | research_outcome:not_export_status |  |
| `embedding-guided-diversity-filtering-for-tiny-pretraining-06c969daa6ab` | `` | research_outcome:not_export_status |  |
| `end-to-end-adaptive-saliency-anchor-kv-pruning-on-gpt-2-sm-4d7f8ca221` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `end-to-end-auxiliary-training-for-gpt-2-early-exit-self-sp-deaa2d7df2` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `end-to-end-coalesced-pretokenized-shard-loader-under-kerne-4a868fc098` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `end-to-end-gpt-2-kv-cache-evaluation-for-attention-aware-1-fb361f5dcc` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `end-to-end-gpt-2-self-speculative-decoding-with-trained-ea-692d10bd58` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `end-to-end-gpt-2-small-mtp-speculative-decoder-benchmark-0bace5709c` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `end-to-end-kl-and-perplexity-test-for-covariance-aware-mlp-a694c0bd14` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `end-to-end-long-context-decoding-benchmark-for-exact-ancho-1e16c4023d` | `` | research_outcome:not_export_status |  |
| `end-to-end-prompt-lookup-suffix-drafting-benchmark-on-copy-dd2fdceef3` | `` | research_outcome:not_export_status |  |
| `end-to-end-serving-replay-for-domain-limited-suffix-retrie-8fc04b01cc` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `end-to-end-tiny-cpu-ternary-draft-acceptance-test-1da97e5920` | `` | research_outcome:not_export_status |  |
| `end-to-end-transparency-log-validation-for-non-cancelable-77444cdbf5` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `entropy-budgeted-eagle-depth-20260508-night03` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `entropy-density-gated-data-selection-for-sub-1b-local-pretraining-eaed476262ac` | `` | research_outcome:not_export_status |  |
| `entropy-gated-local-cascade-routing-26b201cee26d` | `` | research_outcome:not_export_status |  |
| `entropy-gradient-gated-data-selection-for-tiny-pretraining-bdc8ef4f73fe` | `` | research_outcome:not_export_status |  |
| `entropy-weighted-pouw-for-volunteer-gradient-validation-7005fae19b67` | `` | research_outcome:not_export_status |  |
| `entropygated-model-cascade-4912017156e9` | `` | research_outcome:not_export_status |  |
| `evaluate-counterclaim-minimal-reproducer-ledgers-on-real-e-8a4e2d0c8c` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `evidence-audit-reward-for-tool-agents-e5992f711a97` | `` | research_outcome:not_export_status |  |
| `evidence-derived-kv-count-controller-versus-answer-token-k-752035810e` | `negative` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `evidence-ledger-constrained-agent-decoding-926d056eee97` | `` | research_outcome:not_export_status |  |
| `exact-anchor-gated-kv-compression-for-long-context-retrieval-1cec9478a0aa` | `` | research_outcome:not_export_status |  |
| `exact-anchor-kv-compression-via-trainable-landmark-gating-c5ceaa8f5232` | `` | research_outcome:not_export_status |  |
| `exact-anchor-kv-compression-with-sparse-retention-4823073670d3` | `` | research_outcome:not_export_status |  |
| `exact-anchor-kv-lossless-retrieval-points-in-compressed-long-context-55c1e2a1ce55` | `` | research_outcome:not_export_status |  |
| `exact-anchor-state-compression-for-retrieval-ba755e347bed` | `` | research_outcome:not_export_status |  |
| `exact-long-context-kv-cache-validation-of-saliency-anchors-8a9710c670` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `exact-n-gram-cache-speculative-decoding-for-code-7510b5813f` | `` | research_outcome:not_export_status |  |
| `externally-anchored-agent-ledger-replay-on-real-long-run-t-a9cecef577` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `failure-contrast-synthetic-data-filter-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `falsifiable-evidence-ledger-for-tool-calling-agents-15b6e5842911` | `` | research_outcome:not_export_status |  |
| `falsifiable-structured-logging-for-tool-use-agents-18aa59729edd` | `` | research_outcome:not_export_status |  |
| `falsification-first-agent-evidence-ledger-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `final-depth-gpt-2-medium-aware-residual-quantization-versu-795de82994` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `fixed-prefix-anchors-versus-sliding-kv-cache-on-long-conte-8479cfb7df` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `fixed64-gb10-kv-decode-kernel-specialization-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `framework-level-deterministic-checkpoint-replay-with-fault-fc40c59501` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `galore-rank-switch-under-vram-cap-20260508-night15` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `gated-anchor-preprocessing-for-fast-compression-only-6dfe9a28ad` | `negative` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `gb10-uma-mincut-qlora-activation-ledger-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `goldilocks-perplexity-filtering-for-tiny-local-pretraining-41236825a3fa` | `` | research_outcome:not_export_status |  |
| `gpt-2-small-class-token-superposition-training-reproductio-7e37e98dea` | `` | research_outcome:not_export_status |  |
| `gpt-2-small-low-rank-mtp-speculative-decoding-validation-f9b81810e8` | `` | research_outcome:not_export_status |  |
| `gpt-2-small-natural-text-auxiliary-early-exit-self-specula-2e5ab1f34f` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `gradient-conflict-filtering-for-tiny-pretraining-736547b9932e` | `` | research_outcome:not_export_status |  |
| `gradient-diversity-greedy-coreset-for-home-pretraining-865e265bc109` | `` | research_outcome:not_export_status |  |
| `gradient-guided-data-pruning-for-sub-billion-parameter-pretraining-12eab93717c1` | `` | research_outcome:not_export_status |  |
| `gradient-influence-data-pruning-for-sub-1b-local-pretraining-0d78153f6836` | `` | research_outcome:not_export_status |  |
| `gradient-informed-residual-channel-selection-for-1-bit-quantization-387378ffb89c` | `` | research_outcome:not_export_status |  |
| `gradient-puzzle-consensus-for-volunteer-training-c874f8ded664` | `` | research_outcome:not_export_status |  |
| `gradient-sketch-coreset-for-tiny-pretraining-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `gradient-sketch-data-coreset-20260508-night26` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `gradient-trajectory-data-distillation-for-tiny-pretraining-0dbf40d2f233` | `` | research_outcome:not_export_status |  |
| `gradient-variance-gated-mixed-precision-optimizer-states-b1a99315c5b4` | `` | research_outcome:not_export_status |  |
| `grammar-fsm-non-neural-speculative-decoding-for-code-d3b0e2c4eac2` | `` | research_outcome:not_export_status |  |
| `hard-gated-residual-hidden-state-router-for-frozen-local-l-0eabc6fd5d` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `hash-chained-evidence-ledger-for-verifiable-agent-reasoning-1ce4970a4e9c` | `` | research_outcome:not_export_status |  |
| `hash-provenance-evidence-ledger-delta-replay-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `head-role-kv-paging-for-vision-language-local-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `head-saliency-fp8-int2-kv-mix-20260508-night06` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `held-out-cheap-predictor-for-budget-regularized-perplexity-b181ff116b` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `held-out-real-trace-dual-trail-failure-prediction-benchmar-b64f5b4c58` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `hessian-trace-residual-channels-for-stable-2-bit-quantization-2e4151dbce91` | `` | research_outcome:not_export_status |  |
| `hessian-trace-residual-channels-for-sub-2-bit-weight-quantization-5a5b8e6fd3a0` | `` | research_outcome:not_export_status |  |
| `hessian-trace-residual-channels-for-sub-2bit-average-quantization-128d70949767` | `` | research_outcome:not_export_status |  |
| `hessian-trace-residual-channels-for-sub-2bit-quantization-bd43e82ffe7a` | `` | research_outcome:not_export_status |  |
| `hf-corpus-delta-sync-verifier-20260508-night34` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `hidden-audit-commit-reveal-validation-on-real-federated-be-6398f63b32` | `` | research_outcome:not_export_status |  |
| `hidden-validation-beacons-diloco-20260508-night20` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `hierarchical-compressed-memory-with-exact-anchor-retrieval-via-learned-sparse-codes-4a533e156ee6` | `` | research_outcome:not_export_status |  |
| `hierarchical-exact-anchor-kv-compression-3105d3719d60` | `` | research_outcome:not_export_status |  |
| `hierarchical-kv-anchor-compression-54226b10dcbb` | `` | research_outcome:not_export_status |  |
| `hierarchical-kv-anchor-compression-5e590f8b7b55` | `` | research_outcome:not_export_status |  |
| `hierarchical-kv-cache-with-exact-anchor-preservation-871bb86d6118` | `` | research_outcome:not_export_status |  |
| `hierarchical-ssm-state-compression-for-100k-context-on-4gb-vram-bd6468ea7a9e` | `` | research_outcome:not_export_status |  |
| `hierarchical-ssm-state-offload-for-sub-4gb-128k-context-adeb56fe9df0` | `` | research_outcome:not_export_status |  |
| `hierarchical-ssm-state-paging-for-1m-context-on-8gb-vram-f7a6cfce0efa` | `` | research_outcome:not_export_status |  |
| `hierarchical-ssm-state-snapshots-for-1m-token-context-on-8gb-vram-29d9fa30a823` | `` | research_outcome:not_export_status |  |
| `high-perplexity-tail-rejection-with-diversity-preserving-s-71e57a006c` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `home-agent-tamper-evident-ledger-45890eadf16d` | `` | research_outcome:not_export_status |  |
| `home-cascade-router-with-dynamic-quantization-tiers-afd670e7c30d` | `` | research_outcome:not_export_status |  |
| `home-cascade-router-with-latency-gated-speculation-4940025e2d68` | `` | research_outcome:not_export_status |  |
| `human-label-replication-of-evidence-audit-reward-selection-942c6ab1c5` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `human-labeled-natural-final-claim-audit-for-real-agent-tra-75b4760ea2` | `needs_review` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `hybrid-rank0-momentum-under-a-4-gib-optimizer-state-cap-88a10462fc` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `idea-343e3677f1c6815b9e81ca9c89d0ae2b` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `idea-343e3677f1c681f1a51adf5137a2f359` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `idea-344e3677f1c68105887ce0f6e52e13f3` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `idea-34ae3677f1c681139d24da497e346fc9` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `idea-34ae3677f1c68127950ad0ae32fcd693` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `idea-34ae3677f1c6816da75af18ac8a6b5d3` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `idea-34ae3677f1c681bcb61df121306f4197` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `idea-34ae3677f1c681d7a6c9f7aae28bdf55` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `idea-34ae3677f1c681dab9e1e50d92f2d199` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `idea-34be3677f1c68109920be0ec484a4e60` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `importance-weighted-sparse-gradient-validation-against-top-55788147ce` | `` | research_outcome:not_export_status |  |
| `independent-failed-trajectory-validation-of-tool-boundary-577d75176e` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `independent-real-agent-claim-receipt-validation-43ac7958d6` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `information-density-filtering-for-sub-billion-pretraining-a1428e42b919` | `` | research_outcome:not_export_status |  |
| `information-theoretic-residual-channel-selection-for-1-58-bit-quantization-58b47fd87ad5` | `` | research_outcome:not_export_status |  |
| `int2-weight-only-residual-bypass-090a4dfed1f4` | `` | research_outcome:not_export_status |  |
| `int8-blockwise-factorized-adam-for-6gb-vram-training-b2daa15f40d4` | `` | research_outcome:not_export_status |  |
| `iterative-high-loss-resampling-for-tiny-pretraining-d408e45b16a5` | `` | research_outcome:not_export_status |  |
| `jacobi-fixed-point-decoding-without-draft-model-12079cd6752e` | `` | research_outcome:not_export_status |  |
| `kivi-style-channelwise-int3-residual-kv-cache-validation-4f777a97a1` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `kv-cache-attention-derived-tree-drafting-for-zero-model-spec-decoding-872552b6bd76` | `` | research_outcome:not_export_status |  |
| `kv-cache-aware-model-cascade-router-922d1f01376d` | `` | research_outcome:not_export_status |  |
| `kv-cache-driven-non-parametric-speculative-drafting-95d163ff9e4d` | `` | research_outcome:not_export_status |  |
| `kv-cache-n-gram-drafting-for-zero-overhead-speculative-decoding-fba1fc7738f0` | `` | research_outcome:not_export_status |  |
| `kv-cache-n-gram-drafting-zero-model-speculative-decoding-9ed0f86dadb2` | `` | research_outcome:not_export_status |  |
| `kv-cache-parity-fingerprint-20260508-night39` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `kv-cache-prefix-reuse-across-cascade-levels-bc30643583b2` | `` | research_outcome:not_export_status |  |
| `kv-cache-serving-benchmark-for-tokenizer-level-suffix-matc-edeee8b2e1` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `kv-cache-suffix-array-drafting-for-zero-extra-vram-speculative-decoding-1a8c7f9eef42` | `` | research_outcome:not_export_status |  |
| `kv-cache-suffix-array-speculative-decoding-145d3d67ad1f` | `` | research_outcome:not_export_status |  |
| `kv-cache-suffix-tree-speculative-decoding-6abd7c649628` | `` | research_outcome:not_export_status |  |
| `kv-preserving-local-cascade-router-4121f5ba1e3c` | `` | research_outcome:not_export_status |  |
| `kvsculpt-distilled-pocket-cache-20260507` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `lan-speculative-mesh-for-cross-device-cascade-inference-5b99ec5317cd` | `` | research_outcome:not_export_status |  |
| `landmark-exact-kv-cache-with-delta-compression-24494ab1b860` | `` | research_outcome:not_export_status |  |
| `larger-cost-aware-hidden-state-cascade-router-with-stronge-32ee9f7213` | `` | research_outcome:not_export_status |  |
| `larger-equal-token-diversity-filtering-with-stronger-embed-c8c386faf4` | `` | research_outcome:not_export_status |  |
| `larger-target-calibrated-cpu-gate-cascade-validation-aa0e641b78` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `latest-and-historical-fact-router-20260508-night10` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `layer-adaptive-optimizer-state-eviction-via-gradient-variance-tracking-dc86c1864a0b` | `` | research_outcome:not_export_status |  |
| `learned-anchor-gated-kv-compression-in-a-small-transformer-1741ddd97e` | `negative` | research_outcome:not_export_status |  |
| `learned-mmlu-meta-router-against-stronger-local-llm-baseli-8f5adfb788` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `learned-residual-gate-for-dynamic-mixed-precision-channels-4e8266a71caa` | `` | research_outcome:not_export_status |  |
| `learned-robust-addressing-for-compressed-memory-tokens-be227ad364` | `` | research_outcome:not_export_status |  |
| `ledger-grounded-react-for-small-agent-reliability-7012a851e041` | `` | research_outcome:not_export_status |  |
| `length-curriculum-pointer-copy-anchor-ledger-retrieval-at-8a9fed3a7c` | `negative` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `linear-shared-gradient-verifier-downstream-training-effici-1fb61f0884` | `negative` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `linguistic-complexity-curriculum-for-tiny-pretraining-d7705fd87293` | `` | research_outcome:not_export_status |  |
| `live-agent-claim-ledger-decision-path-validation-ff45793e23` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `live-external-anchor-replay-on-long-agent-traces-81117d1191` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `live-memory-replay-admission-for-real-small-local-transfor-85eecba84d` | `` | research_outcome:not_export_status |  |
| `llm-multiple-choice-prompt-router-with-local-expert-on-mml-c96baf9dd7` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `local-cascade-router-with-tiny-gating-model-e8c50c60686f` | `` | research_outcome:not_export_status |  |
| `local-coherence-filtering-for-tiny-model-pretraining-84a815a02f53` | `` | research_outcome:not_export_status |  |
| `local-confidence-router-with-verifier-budget-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `local-embedding-consensus-for-distributed-data-selection-eb8d9f0db3e2` | `` | research_outcome:not_export_status |  |
| `local-evidence-ledger-for-small-agent-claims-a9e8f83726ff` | `` | research_outcome:not_export_status |  |
| `local-latency-router-cpu-gating-for-gpu-cascade-849e7228abaf` | `` | research_outcome:not_export_status |  |
| `local-merkle-judge-for-small-agent-hallucination-detection-0d9ffa308a19` | `` | research_outcome:not_export_status |  |
| `local-skeptic-verifier-evidence-ledger-72b29b0341c9` | `` | research_outcome:not_export_status |  |
| `local-volunteer-gradient-replay-validation-bf2cb56563de` | `` | research_outcome:not_export_status |  |
| `lofos-low-rank-factored-optimizer-states-for-sub-4gb-training-a0c828a9fbf2` | `` | research_outcome:not_export_status |  |
| `long-run-anchored-agent-ledger-validation-on-gb10-e2dba12f8f` | `` | research_outcome:not_export_status |  |
| `longflow-reasoning-budget-switch-20260507` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `lora-rank-bit-auction-20260507` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `loropt-low-rank-factored-optimizer-states-for-vram-reduction-e9e2408e7232` | `` | research_outcome:not_export_status |  |
| `loss-slope-gated-resampling-for-tiny-transformer-pretraini-5f649bd0d7` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `loss-spike-aware-qlora-checkpointing-20260508-night14` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `loss-trajectory-early-stop-predictor-20260508-night28` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `lottery-based-checkpoint-reproduction-for-volunteer-auditing-77d342e3736c` | `` | research_outcome:not_export_status |  |
| `low-rank-factored-adam-optimizer-states-for-sub-4gb-training-737fd91b6763` | `` | research_outcome:not_export_status |  |
| `low-rank-factored-adam-subspace-optimizer-states-for-tiny-vram-59825aa32df5` | `` | research_outcome:not_export_status |  |
| `low-rank-factored-optimizer-states-with-error-feedback-lofos-8fd4afc94d22` | `` | research_outcome:not_export_status |  |
| `low-rank-factorized-adam-for-4x-optimizer-memory-reduction-3025dcde0c87` | `` | research_outcome:not_export_status |  |
| `low-rank-factorized-adam-states-for-sub-6gb-llm-training-a0e3a8c94d50` | `` | research_outcome:not_export_status |  |
| `low-rank-residual-channels-for-sub-4bit-quantization-dd67f385246e` | `` | research_outcome:not_export_status |  |
| `low-rank-state-replay-for-code-context-20260508-night37` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `mamba-chunked-state-offload-128k-context-on-4gb-vram-c4e133431591` | `` | research_outcome:not_export_status |  |
| `mamba-state-paging-128k-context-on-4gb-vram-via-recurrent-state-swap-f8daed045af3` | `` | research_outcome:not_export_status |  |
| `mamba-state-reuse-as-kv-cache-replacement-for-128k-context-on-edge-ac1480b475d0` | `` | research_outcome:not_export_status |  |
| `mamba-state-swap-paging-for-128k-context-on-4gb-vram-4360a600f6f0` | `` | research_outcome:not_export_status |  |
| `matched-bit-gpt-2-residual-codebook-quantization-against-s-b484508b9c` | `` | research_outcome:not_export_status |  |
| `measured-multi-token-exact-gpt-2-small-self-speculative-de-9ccc342d85` | `negative` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-confirmation-of-anchor-gated-kv-compression-across-7393d04c3d` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-confirmation-of-evidence-ledger-constrained-decodin-dd511d1e94` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-confirmation-of-hierarchical-landmark-memory-on-rob-ac636e1706` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-confirmation-of-rank-4-ternary-residual-gpt-2-small-d567109703` | `negative` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-confirmation-of-retention-aware-random-mix-curricul-5979fd3857` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-gpt-2-activation-aware-residual-quantization-valida-58777210ec` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `medium-scale-deterministic-checkpoint-replay-with-coverage-2b232c5801` | `` | research_outcome:not_export_status |  |
| `merkle-anchored-agent-evidence-ledgers-for-hallucination-detection-deff884e2282` | `` | research_outcome:not_export_status |  |
| `merkle-audited-diloco-volunteer-training-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `merkle-chain-evidence-ledgers-for-verifiable-agent-reasoning-97651358bebc` | `` | research_outcome:not_export_status |  |
| `merkle-chain-proof-of-training-for-volunteer-lora-swarms-3f2461446ebe` | `` | research_outcome:not_export_status |  |
| `merkle-checkpoint-gradient-auditing-for-volunteer-swarms-7ca94f3a979e` | `` | research_outcome:not_export_status |  |
| `merkle-commit-gradient-lottery-for-volunteer-training-a4c683c0101a` | `` | research_outcome:not_export_status |  |
| `merkle-dag-agent-action-ledger-with-streaming-verifier-0a3fa0e117a5` | `` | research_outcome:not_export_status |  |
| `merkle-gradient-slice-replay-20260508-night19` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `merkle-gradient-witness-cheating-resistant-volunteer-training-a31397a25315` | `` | research_outcome:not_export_status |  |
| `merkle-ledger-for-local-agent-rollback-89394e2225ed` | `` | research_outcome:not_export_status |  |
| `merkle-ledger-rollback-agent-93c0a8a8b57e` | `` | research_outcome:not_export_status |  |
| `merkle-ledger-tamper-detection-for-edge-agents-b0f061fc4bc2` | `` | research_outcome:not_export_status |  |
| `mi-guided-residual-channels-for-sub-2bit-quantization-77f65efdde58` | `` | research_outcome:not_export_status |  |
| `mid-layer-lora-head-self-speculation-4d6c8374585f` | `` | research_outcome:not_export_status |  |
| `mild-high-loss-resampling-in-tiny-transformer-pretraining-d2dad15f79` | `` | research_outcome:not_export_status |  |
| `minimal-reproducer-gate-20260508-night23` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `mixed-precision-kv-residual-gates-7a5356cc3a5d` | `` | research_outcome:not_export_status |  |
| `model-in-the-loop-suffix-replay-drafting-on-code-prompts-418513d620` | `` | research_outcome:not_export_status |  |
| `model-integrated-suffix-match-drafter-on-code-log-corpora-902839b70a` | `` | research_outcome:not_export_status |  |
| `model-judged-entailment-replay-for-critical-path-ledger-pr-b9139fe345` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `model-level-observed-anchor-kv-retention-against-same-budg-6d671f6fe4` | `` | research_outcome:not_export_status |  |
| `model-level-superposed-anchor-compression-on-long-context-063615e993` | `` | research_outcome:not_export_status |  |
| `multi-process-sub-8gb-cpu-sharded-1-bit-async-adam-validat-502dca71f3` | `` | research_outcome:not_export_status |  |
| `multi-task-bounded-validation-of-sink-aware-exact-position-f13730b70a` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `multi-trace-real-agent-claim-receipt-benchmark-105739cf96` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `natural-language-qa-validation-of-evidence-ledger-constrai-4ac5aad895` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `natural-language-sub-1b-gradient-influence-pruning-benchma-4f1a43c17c` | `` | research_outcome:not_export_status |  |
| `natural-long-context-draft-scored-kv-eviction-benchmark-41b1eb9757` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `natural-selective-qa-validation-of-evidence-ledger-abstent-9ec15a6f76` | `negative` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `near-duplicate-relay-kv-agent-cache-20260507` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `negative-result-cluster-dashboard-20260508-night36` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `negative-result-cost-aware-idea-triage-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `network-bottlenecked-gpt-2-small-compressed-volunteer-repl-ab143d5b3b` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `neural-held-out-cheap-predictor-for-budgeted-perplexity-ga-2763e0605e` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `neural-lm-test-of-budget-regularized-perplexity-gap-select-ba46658854` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `nf4-quantized-adam-states-with-on-demand-dequantization-for-sub-6gb-training-581b7a4aad10` | `` | research_outcome:not_export_status |  |
| `no-oracle-gpt-2-small-class-dual-memory-layout-recall-5bb026b60b` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `no-svd-diagonal-plus-low-rank-adam-under-a-hard-4-gb-memor-7bee4e525f` | `` | research_outcome:not_export_status |  |
| `non-cancelable-per-volunteer-batch-proof-implementation-an-53d4c1ff38` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `non-neural-speculative-decoding-with-adaptive-verification-scheduling-21ed6377ceef` | `` | research_outcome:not_export_status |  |
| `non-resident-llm-cascade-with-paged-offloaded-large-model-9d45dde6a9` | `` | research_outcome:not_export_status |  |
| `nontrivial-long-context-anchor-gated-kv-compression-with-s-cb3c7baa0d` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `novel-n-gram-coverage-selection-for-long-context-tiny-lm-pretraining-9f9af8170ddf` | `` | research_outcome:not_export_status |  |
| `nvme-kv-prefill-scheduler-20260507` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `observed-anchor-kv-retention-on-pretrained-long-context-re-91fab89e61` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `offline-kv-library-for-repeated-home-workflows-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `on-device-merkle-ledger-for-sub-3b-agent-policy-verification-21e921f569df` | `` | research_outcome:not_export_status |  |
| `one-bit-critical-gradient-sketch-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `online-anchor-detector-for-exact-kv-recall-points-4d4514f57a` | `` | research_outcome:not_export_status |  |
| `online-low-rank-factorization-of-adam-optimizer-states-lorf-adam-65d01dbf1a3e` | `` | research_outcome:not_export_status |  |
| `oom-risk-microbatch-planner-20260508-night29` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `oomb-home-qlora-activation-ledger-20260507` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `optimized-long-context-anchor-gated-kv-eviction-against-pu-9495244d73` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `optimized-merkle-rollback-with-partial-proof-and-external-e080ab42ed` | `` | research_outcome:not_export_status |  |
| `optimized-saliency-anchor-kv-retention-against-published-k-e5c76d5776` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `optimizer-state-replay-compression-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `packed-recency-only-int3-kv-cache-without-fp16-exceptions-80ed81b852` | `negative` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `paged-lora-adapter-hotset-20260508-night16` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `parameter-weighted-low-variance-optimizer-state-retention-6581157b88` | `` | research_outcome:not_export_status |  |
| `peer-committee-loss-reproduction-for-lora-updates-2dfff1059d3a` | `` | research_outcome:not_export_status |  |
| `peer-to-peer-residual-error-compensation-for-2-bit-federated-layers-9d9cba3cf7d1` | `` | research_outcome:not_export_status |  |
| `perplexity-band-data-selection-for-tiny-local-pretraining-a7fcd134accf` | `` | research_outcome:not_export_status |  |
| `perplexity-curriculum-data-filtering-for-tiny-pretraining-685f32b061b4` | `` | research_outcome:not_export_status |  |
| `perplexity-gap-data-selection-for-tiny-local-pretraining-2ac9dd0e49b0` | `` | research_outcome:not_export_status |  |
| `perplexity-gated-local-cascade-router-8253e9172db2` | `` | research_outcome:not_export_status |  |
| `perplexity-spike-filtering-for-high-density-pretraining-data-e359b8af7b43` | `` | research_outcome:not_export_status |  |
| `perplexity-stratified-curriculum-for-tiny-pretraining-e0723ea2a9ee` | `` | research_outcome:not_export_status |  |
| `persistent-anchored-ledger-across-multiple-real-agent-sess-6053e0da9d` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `pipeline-shard-audits-via-commit-reveal-forward-passes-4aac3838c19c` | `` | research_outcome:not_export_status |  |
| `positive-factored-second-moment-optimizer-for-sub-6gb-llm-c2565c74ad` | `` | research_outcome:not_export_status |  |
| `predictive-block-swap-training-enabling-2x-vram-models-on-single-gpus-96c0f5e3c181` | `` | research_outcome:not_export_status |  |
| `prefix-kv-pocket-dedup-sweep-20260508-night01` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `preregistered-multi-beir-safety-margin-tinyembeddingrouter-5e448aab01` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `pretrained-decoder-anchor-gated-kv-compression-evaluation-e8e8cb0f56` | `` | research_outcome:not_export_status |  |
| `pretrained-gpt-2-small-detached-residual-split-q3-w-a-robu-09175aea00` | `negative` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `pretrained-small-lm-1-58-bit-residual-adapter-validation-u-784e49dfdd` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `probe-guided-adaptive-cascade-routing-for-local-serving-16d35eca10f4` | `` | research_outcome:not_export_status |  |
| `production-hessian-aware-sub-2-bit-quantizer-with-activati-0aaf05cc3d` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `production-style-anchor-kv-preservation-on-a-stronger-long-36d8df641a` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `production-style-quality-gated-prompt-lookup-with-concurre-27a6a660d7` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `production-trace-larger-model-pocket-cache-ce-validation-0dbc04c266` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `production-trace-replay-for-domain-limited-suffix-retrieva-a83788efaa` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `prompt-anchored-n-gram-retrieval-drafting-9af9b073e17a` | `` | research_outcome:not_export_status |  |
| `prompt-bound-n-gram-suffix-cache-for-zero-vram-speculation-f5165c9d7d71` | `` | research_outcome:not_export_status |  |
| `prompt-embedding-router-for-local-llm-cascade-83f424b9590f` | `` | research_outcome:not_export_status |  |
| `prompt-embedding-router-with-a-stronger-local-expert-on-a-bd133eeee2` | `` | research_outcome:not_export_status |  |
| `proof-of-gradient-commitment-for-volunteer-training-1669ed0798c4` | `` | research_outcome:not_export_status |  |
| `proof-of-gradient-slice-volunteer-training-20260507` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `proof-of-gradient-work-cheating-resistant-volunteer-training-via-stochastic-checkpoint-verificat-77b56d99db48` | `` | research_outcome:not_export_status |  |
| `proof-of-sample-challenge-data-cheating-resistance-for-volunteer-training-d5e278c0068b` | `` | research_outcome:not_export_status |  |
| `proof-of-useful-work-lora-slice-market-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `prospective-runtime-cost-annotated-idea-ranking-a-b-test-588bd2d641` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `provenance-aware-candidate-generation-for-verifier-gated-c-cec799fa4a` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `provider-budget-aware-idea-generation-scheduler-68321272e6` | `` | research_outcome:not_export_status |  |
| `proxy-learnability-coresets-for-tiny-pretraining-900dc20ce700` | `` | research_outcome:not_export_status |  |
| `proxy-size-matched-data-selection-for-sub-500m-models-fa0095808018` | `` | research_outcome:not_export_status |  |
| `public-corpus-missing-result-reconstructor-20260508-night33` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `qadam-4bit-4-bit-quantized-second-moment-for-ultra-low-vram-training-05e7d90d452d` | `` | research_outcome:not_export_status |  |
| `qjl-error-check-kv-spec-drafter-20260507` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `quality-aware-coverage-selection-for-tiny-lm-pretraining-0ccb96a1ab` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `quality-classifier-selection-beats-perplexity-filtering-for-tiny-pretraining-67903e26b35b` | `` | research_outcome:not_export_status |  |
| `quality-gated-prompt-lookup-on-real-copy-heavy-serving-tra-48e303e8c5` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `quality-gated-prompt-lookup-serving-benchmark-on-larger-co-452497741c` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `random-controlled-educational-data-selection-with-direct-e-5178181768` | `` | research_outcome:not_export_status |  |
| `random-probe-gradient-audits-for-volunteer-swarms-1d034664e39a` | `` | research_outcome:not_export_status |  |
| `rank-1-incremental-optimizer-factorization-for-sub-linear-memory-training-2b60861f3032` | `` | research_outcome:not_export_status |  |
| `rank-1-optimizer-state-recycling-for-sub-4gb-training-500f90ad0e43` | `` | research_outcome:not_export_status |  |
| `rank-1-streaming-optimizer-replace-adam-m-v-with-layer-factored-rank-1-approximations-7d9df81aafc8` | `` | research_outcome:not_export_status |  |
| `rank-decomposed-optimizer-states-for-sub-10gb-training-cd85e565470e` | `` | research_outcome:not_export_status |  |
| `rare-skill-token-budgeter-20260508-night27` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `raw-observation-ppo-merkle-audit-with-supervised-and-symbo-b66427ded7` | `negative` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-activation-2-bit-residual-routing-benchmark-039d9e0235` | `` | research_outcome:not_export_status |  |
| `real-agent-claim-receipt-evaluation-for-tool-use-trace-fal-c748da4742` | `` | research_outcome:not_export_status |  |
| `real-agent-verifier-gated-cache-rehydration-benchmark-4d24059103` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-cited-span-audit-for-local-evidence-ledger-transcript-60d641b156` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-conversation-extraction-for-text-free-state-delta-mem-51c3455fa9` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-corpus-auxiliary-position-weighted-multi-hot-objectiv-3308d871d1` | `` | research_outcome:not_export_status |  |
| `real-corpus-band-pass-self-perplexity-filtering-for-local-3c97f088b6` | `` | research_outcome:not_export_status |  |
| `real-corpus-perplexity-gap-selection-with-target-loss-cont-5f3dcd9f2c` | `` | research_outcome:not_export_status |  |
| `real-corpus-tiny-lm-validation-of-spike-window-filtering-47d6f80cce` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-corpus-tiny-pretraining-comparison-of-quality-classif-79a0d6fe4d` | `` | research_outcome:not_export_status |  |
| `real-early-exit-speculative-decoding-trace-test-with-layer-f0bf00370f` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-framework-self-attesting-checkpoint-recovery-eb57ff12d2` | `` | research_outcome:not_export_status |  |
| `real-llm-evidence-ledger-tool-calling-benchmark-de606219a4` | `` | research_outcome:not_export_status |  |
| `real-llm-tool-trace-evaluation-of-append-only-observation-1530f63eae` | `` | research_outcome:not_export_status |  |
| `real-model-cpu-gate-cascade-serving-validation-5443094f64` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-model-evaluation-of-anchor-preserved-pooled-kv-cache-0f0f97601b` | `` | research_outcome:not_export_status |  |
| `real-model-gb10-fixed64-decode-integration-with-profiler-c-558e3c83f0` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-model-kv-trace-validation-for-recency-residual-int3-625678b5d2` | `` | research_outcome:not_export_status |  |
| `real-model-query-aware-exact-top-b-kv-validation-de09c6f379` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-model-serving-validation-of-anchor-gated-kv-compressi-5a054ac8ac` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-output-learned-cascade-router-versus-calibrated-stati-083894b466` | `negative` | research_outcome:not_export_status |  |
| `real-pretokenized-loader-test-under-slow-storage-regime-c831c75d57` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-repeated-prefix-ce-workload-pocket-cache-validation-70368283e7` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-request-level-offloaded-llm-cascade-validation-on-gb1-3d62e50f4b` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-serving-validation-for-cpu-gated-gpu-cascade-7211bd4ca1` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-serving-validation-of-kv-cache-aware-cascade-routing-bd3c222f57` | `` | research_outcome:not_export_status |  |
| `real-small-transformer-1-58-bit-residual-adapter-test-unde-acd08f0c9a` | `` | research_outcome:not_export_status |  |
| `real-small-transformer-ce-pocket-cache-benchmark-146590b335` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-system-quorum-evidence-ledger-under-edge-network-loss-14c5cd1233` | `` | research_outcome:not_export_status |  |
| `real-trace-append-only-observation-ledger-benchmark-agains-8c1eb67019` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-trace-claim-ledger-byte-budget-evaluation-6d3d99cf4c` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-trace-latency-validation-for-domain-limited-suffix-re-c9e840a797` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-trace-live-anchor-replay-with-in-flight-decisions-9272cc4898` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-trace-provenance-patch-replay-for-verifier-gated-kv-c-9dfad437e6` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-trace-validation-of-causal-critical-path-semantic-rep-1dbcbac9ac` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-trace-validation-of-support-counter-deletion-for-agen-99f213c462` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `real-transformer-anchor-preserving-kv-quantization-needle-74568a2676` | `` | research_outcome:not_export_status |  |
| `real-transformer-kv-trace-anchor-routing-recall-test-78a60db3b6` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `realistic-multi-tool-trace-benchmark-for-append-only-obser-275c6a0b59` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `recency-controlled-suffix-replay-on-stronger-code-models-fa1d7c1af7` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `recency-residual-kv-int3-cache-f9be6c060687` | `` | research_outcome:not_export_status |  |
| `recovery-capable-anchored-ledger-with-external-checkpoints-9a597003d9` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `repeated-prefix-ce-pocket-cache-validation-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `replay-enoch-worker-traces-with-idle-proof-heartbeat-cutov-e79588c646` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `residual-anchored-kv-quantization-for-10gb-long-context-4a10b05cfc2d` | `` | research_outcome:not_export_status |  |
| `residual-channel-compensation-for-sub-2bit-quantization-975d8cb8cb92` | `` | research_outcome:not_export_status |  |
| `residual-channel-preserving-extreme-quantization-rcpeq-402d97255e77` | `` | research_outcome:not_export_status |  |
| `residual-channel-quantization-with-learned-error-routing-ea9d36c9dff3` | `` | research_outcome:not_export_status |  |
| `residual-gated-sub-2bit-quantization-04953a9c4782` | `` | research_outcome:not_export_status |  |
| `residual-high-precision-channel-quantization-0e7228e22d02` | `` | research_outcome:not_export_status |  |
| `residual-precision-preserving-1-bit-quantization-de3bc4abe26e` | `` | research_outcome:not_export_status |  |
| `residual-split-int2-fp16-hybrid-quantization-for-local-llm-inference-ce5c23ace5fd` | `` | research_outcome:not_export_status |  |
| `residual-ternary-weights-with-learned-error-channels-a2a5ee0315d4` | `` | research_outcome:not_export_status |  |
| `retrieval-conditioned-fsm-speculative-drafter-20260507` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `ring-allreduce-sharded-optimizer-states-across-home-pcs-for-7b-finetuning-0c8acc18fbb0` | `` | research_outcome:not_export_status |  |
| `risk-controlled-conservative-quantile-gates-for-no-kv-gpt-165c0f1406` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `robust-hidden-audit-thresholds-on-canonical-federated-benc-05da55118e` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `robust-realistic-validation-of-rope-aware-attention-select-6ad2d22965` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `rollback-agent-with-contradiction-ledger-16bc50d59451` | `` | research_outcome:not_export_status |  |
| `rollback-ledger-detector-on-real-structured-autoregressive-b8fcc9d233` | `` | research_outcome:not_export_status |  |
| `rope-aware-and-attention-selected-anchor-retention-for-pre-8308c895c1` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `runtime-cost-annotated-idea-ranking-20260508-night35` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `saliency-coded-int2-kv-activation-codec-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `sampling-stable-kv-reserve-20260507` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `secret-influence-probes-for-diloco-volunteers-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `secret-probe-aggregation-defenses-on-opendiloco-language-m-824363c515` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `seeded-gpt-tokenizer-confirmation-of-low-perplexity-filter-34209f89c9` | `` | research_outcome:not_export_status |  |
| `selective-layer-mixed-precision-activation-aware-residual-f78272d1aa` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `selective-layer-training-aware-2-bit-activation-routing-on-468b751219` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `self-adversarial-failure-prediction-via-dual-evidence-trails-008e6c1b6d6a` | `` | research_outcome:not_export_status |  |
| `self-attesting-agent-checkpoints-for-rollback-recovery-658722f9e22a` | `` | research_outcome:not_export_status |  |
| `self-draft-speculative-decoding-via-early-exit-intermediate-layers-e04416362074` | `` | research_outcome:not_export_status |  |
| `self-draft-via-layer-truncation-same-model-speculative-decoding-a81426a04507` | `` | research_outcome:not_export_status |  |
| `self-falsifying-agent-evidence-ledger-20260507` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `self-perplexity-quality-filtering-for-local-pretraining-e405b343b840` | `` | research_outcome:not_export_status |  |
| `self-speculative-decoding-via-adaptive-early-exit-with-kv-cache-reuse-1515300c85e9` | `` | research_outcome:not_export_status |  |
| `self-speculative-decoding-via-adaptive-layer-early-exit-ceaaf09f7b5a` | `` | research_outcome:not_export_status |  |
| `self-speculative-decoding-via-dynamic-early-exit-from-shared-weights-a387814f0cbe` | `` | research_outcome:not_export_status |  |
| `self-speculative-decoding-via-early-exit-drafting-with-zero-extra-vram-bb6bb5270e28` | `` | research_outcome:not_export_status |  |
| `self-speculative-decoding-via-layer-early-exit-draft-4d289e5763f5` | `` | research_outcome:not_export_status |  |
| `self-speculative-decoding-via-layer-subnetwork-drafting-cd0d61001b6e` | `` | research_outcome:not_export_status |  |
| `self-speculative-decoding-via-shallow-layer-drafting-56e627f4cb48` | `` | research_outcome:not_export_status |  |
| `self-speculative-decoding-via-systematic-layer-skipping-5462e55f1ebd` | `` | research_outcome:not_export_status |  |
| `self-speculative-early-exit-drafting-4ac212d39daf` | `` | research_outcome:not_export_status |  |
| `self-speculative-early-exit-drafting-b970bfe04ae9` | `` | research_outcome:not_export_status |  |
| `semantic-deduplication-for-tiny-local-pretraining-671796fb8861` | `` | research_outcome:not_export_status |  |
| `semantic-exemplar-pretraining-via-local-clustering-a57043f07c03` | `` | research_outcome:not_export_status |  |
| `semantic-pin-longflow-kv-20260507` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `semantic-real-agent-claim-receipt-benchmark-1f7f69042e` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `semantic-replay-validation-of-causal-critical-path-ledger-790fd595b4` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `semantic-text-free-slot-deltas-for-realpersonachat-memory-80732c0737` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `sensitivity-guided-2-bit-mlp-activation-routing-on-gpt-2-s-d83734860a` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `sensitivity-weighted-activation-offloading-for-sub-10gb-training-ee91f29f719a` | `` | research_outcome:not_export_status |  |
| `serving-level-donor-matched-shared-suffix-draft-reuse-a22d3b7cac` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `shardcast-weight-delta-dedup-20260508-night21` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `signed-gradient-residual-channel-selection-on-pretrained-m-50505edbe5` | `` | research_outcome:not_export_status |  |
| `singular-vector-residual-channels-for-sub-4bit-llms-35416d5ac790` | `` | research_outcome:not_export_status |  |
| `soft-evidence-ledger-citation-constraints-with-full-contex-d732f25157` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `sparse-coverage-first-selection-for-tiny-neural-lm-pretrai-5d57319c95` | `` | research_outcome:not_export_status |  |
| `sparse-kv-cascade-with-lazy-materialization-4e2b13f51ab3` | `` | research_outcome:not_export_status |  |
| `sparse-layer-self-drafting-dbb32167d823` | `` | research_outcome:not_export_status |  |
| `sparse-optimizer-states-via-dynamic-top-k-gradient-masking-c2bf5dcacb6a` | `` | research_outcome:not_export_status |  |
| `speckv-gamma-router-real-serving-harness-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `spectral-residual-extreme-quantization-for-sub-3gb-vram-ca9a6baff59f` | `` | research_outcome:not_export_status |  |
| `speculative-decoding-rollback-heatmap-20260508-night38` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `speculative-decoding-via-low-rank-multi-token-prediction-heads-8939e2c9ab84` | `` | research_outcome:not_export_status |  |
| `speculative-kv-residual-dual-use-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `speculative-routing-with-draft-model-coalition-8a262a4d474f` | `` | research_outcome:not_export_status |  |
| `split-device-qlora-activation-ledger-20260507` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `ssm-drafter-speculative-decoding-with-confidence-adaptive-verifier-scheduling-aa70aa8f9627` | `` | research_outcome:not_export_status |  |
| `ssm-ghost-kv-compression-for-o-1-long-context-on-tiny-vram-9c8bcd4f9a7d` | `` | research_outcome:not_export_status |  |
| `ssm-recurrence-kv-cache-compression-for-sub-8gb-long-context-inference-f6fa816ba93b` | `` | research_outcome:not_export_status |  |
| `ssm-recurrent-state-tiered-offload-for-128k-context-on-4gb-vram-292d8666f9f4` | `` | research_outcome:not_export_status |  |
| `ssm-rolling-state-anchors-for-1m-context-on-8gb-1957c93c9ffa` | `` | research_outcome:not_export_status |  |
| `ssm-shadow-kv-cache-mamba-compressed-offload-for-local-inference-35471b446475` | `` | research_outcome:not_export_status |  |
| `ssm-state-as-compressed-kv-mamba-hidden-states-as-kv-cache-replacement-for-long-context-on-4gb-v-0596c2220e51` | `` | research_outcome:not_export_status |  |
| `ssm-state-compression-for-128k-context-on-sub-4gb-vram-5fd84a97ac5b` | `` | research_outcome:not_export_status |  |
| `ssm-state-compression-for-long-context-on-tiny-vram-780f70292353` | `` | research_outcome:not_export_status |  |
| `ssm-state-distillation-for-million-token-local-inference-09abbe6a572f` | `` | research_outcome:not_export_status |  |
| `ssm-state-entropy-bound-probe-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `ssm-state-offload-for-1m-context-on-8gb-vram-65e6d80c896b` | `` | research_outcome:not_export_status |  |
| `ssm-state-ring-buffer-offload-for-2m-token-local-context-d17847feffc2` | `` | research_outcome:not_export_status |  |
| `ssm-state-streaming-for-2m-context-on-6gb-vram-c7bf4452d746` | `` | research_outcome:not_export_status |  |
| `ssm-surprise-anchor-write-ablation-20260508-night08` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `ssm-transition-memory-bridge-20260507` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `stability-sweep-for-peer-committee-lora-under-heterogeneou-89e7eff141` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `stabilized-4-bit-adam-second-moment-with-nonzero-floors-or-edf4b768b1` | `` | research_outcome:not_export_status |  |
| `standard-benchmark-suffix-replay-validation-on-7b-and-30b-7b8c09de7d` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `state-delta-memory-without-text-20260508-night09` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `strict-large-bank-low-disclosure-proof-of-sample-protocol-f0b63db75a` | `` | research_outcome:not_export_status |  |
| `stronger-model-natural-task-validation-of-non-oracle-exact-216cfc1fdb` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `stronger-projected-gradient-audit-with-attacked-no-audit-b-087ac08513` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `structural-skeleton-ssm-cache-router-20260507` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `structured-gate-encoding-for-residual-sub-2bit-quantizatio-4779ec3772` | `` | research_outcome:not_export_status |  |
| `sub-1gb-8b-model-quantization-for-consumer-gpus-9062beb1f386` | `` | research_outcome:not_export_status |  |
| `subbit-residual-gate-quantizer-20260507` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `suffix-array-context-local-drafting-for-zero-vram-speculative-decoding-1f316db52786` | `` | research_outcome:not_export_status |  |
| `suffix-automaton-json-drafter-20260508-night02` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `suffix-tree-kv-reuse-for-multi-turn-cascade-c507bae0e1b8` | `` | research_outcome:not_export_status |  |
| `surprisal-predicted-kv-delta-cache-20260507` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `surprise-gated-ssm-delta-memory-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `svd-guided-residual-channels-for-sub-2bit-quantization-c32afb7a3802` | `` | research_outcome:not_export_status |  |
| `synthetic-core-set-distillation-for-tiny-local-pretraining-610108d4ac55` | `` | research_outcome:not_export_status |  |
| `synthetic-difficulty-ranking-for-home-pretraining-9ca99a624036` | `` | research_outcome:not_export_status |  |
| `synthetic-reasoning-dense-corpus-selection-for-local-llms-f7d0b67d4a1a` | `` | research_outcome:not_export_status |  |
| `tamper-evident-agent-action-ledger-via-merkle-proofs-on-device-a47ee477e35a` | `` | research_outcome:not_export_status |  |
| `tamper-evident-agent-action-ledger-with-on-device-merkle-proofs-0f9329079564` | `` | research_outcome:not_export_status |  |
| `tamper-evident-agent-ledger-for-3b-home-gpus-1980a7c1693f` | `` | research_outcome:not_export_status |  |
| `tamper-evident-agent-reasoning-chains-f8a26358ed79` | `` | research_outcome:not_export_status |  |
| `task-level-structured-gate-residual-quantization-validatio-f4c808ca89` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `temporal-tiered-home-kv-offload-20260507` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `ternary-critical-direction-residual-compression-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `ternary-critical-subspace-residual-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `ternary-critical-subspace-residuals-20260507` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `ternary-gradients-with-residual-momentum-for-home-distributed-training-3af2e550dde5` | `` | research_outcome:not_export_status |  |
| `ternary-mamba-residuals-with-outlier-protected-gates-1420ac3e610a` | `` | research_outcome:not_export_status |  |
| `ternary-outlier-residual-sweep-20260508-night11` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `ternary-residual-codebook-quantization-for-4gb-vram-fine-tuning-6d8b604da5cb` | `` | research_outcome:not_export_status |  |
| `ternary-residual-quantization-for-tiny-vram-mamba-fine-tuning-e46948b84ee4` | `` | research_outcome:not_export_status |  |
| `ternary-weights-with-fp8-residual-channels-2505b22ee77d` | `` | research_outcome:not_export_status |  |
| `tiered-ssm-state-compression-for-128k-context-on-4gb-vram-14663793804f` | `` | research_outcome:not_export_status |  |
| `tiny-agent-evidence-ledger-with-falsification-first-consensus-497be82d003a` | `` | research_outcome:not_export_status |  |
| `tiny-agent-evidence-ledger-with-falsification-first-verifier-16b1da960aac` | `` | research_outcome:not_export_status |  |
| `tiny-diloco-next-token-backdoor-test-for-secret-probe-aggr-dfd2b1cb34` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `tiny-lm-opendiloco-validation-beacons-under-partial-worker-e46fa31cf0` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `tiny-pretraining-validation-of-spike-window-data-filtering-d30b742996` | `` | research_outcome:not_export_status |  |
| `tiny-vram-heterogeneous-offload-scheduler-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `tinyembeddingrouter-cascade-006798891afc` | `` | research_outcome:not_export_status |  |
| `tinyembeddingrouter-cascade-on-a-real-retrieval-benchmark-f427708516` | `` | research_outcome:not_export_status |  |
| `token-landmark-state-machine-9b0979fe6fac` | `` | research_outcome:not_export_status |  |
| `token-level-cpu-suffix-drafting-in-real-llm-serving-650a4441b3` | `` | research_outcome:not_export_status |  |
| `token-level-safety-cascade-for-local-agents-ff60f18e4160` | `` | research_outcome:not_export_status |  |
| `token-suffix-speculative-drafting-with-kv-cache-verificati-4db43c19d6` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `tokenwise-int3-residual-kv-cache-packed-kernel-validation-b0a19afd0e` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `tool-boundary-failure-signature-cache-20260508-night24` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `tool-boundary-failure-signature-distillation-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `tool-call-rollback-ledger-validation-on-stronger-live-agen-07857492a9` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `trace-based-home-cascade-router-evaluation-2733aaeb13` | `` | research_outcome:not_export_status |  |
| `trace-driven-batched-merkle-rollback-audit-against-batch-v-c33c91ad41` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `trained-early-exit-heads-for-self-speculative-gpt-2-drafti-b1278a21e1` | `` | research_outcome:not_export_status |  |
| `trajectory-early-stop-prediction-on-real-learning-curve-be-2ea4a20cd0` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `transformer-federated-lora-peer-committee-robustness-bench-e545fe7144` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `transformer-scale-hessian-residual-channel-validation-unde-cdc21bfa12` | `` | research_outcome:not_export_status |  |
| `transformer-scale-residual-preserving-binary-quantization-771ad80e42` | `` | research_outcome:not_export_status |  |
| `trap-batch-gradient-verification-for-cheating-resistant-volunteer-training-4d88bebe84ca` | `` | research_outcome:not_export_status |  |
| `triattention-cpu-prefetch-bridge-20260507` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `true-femnist-writer-partitioned-hidden-audit-persistence-t-73cd818f5e` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `uncertainty-gated-local-model-cascade-for-vram-efficient-serving-5f724c9e1097` | `` | research_outcome:not_export_status |  |
| `uncertainty-triggered-adapter-paging-20260507` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `universal-subbit-codebook-threshold-20260507` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `validate-adapter-thrash-detection-on-real-adapter-serving-5dbba968dd` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `validate-tuned-tail-diverse-sampling-on-stronger-open-mode-d1d503c6d5` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `validation-impact-constrained-audit-for-in-subspace-malici-7355020930` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `verification-aware-cache-rehydration-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `verifier-budget-local-router-20260508-night17` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `volunteer-gradient-sketch-validation-protocol-20260508` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `volunteer-lordo-gradient-receipts-20260507` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `volunteer-node-residual-codebook-for-extreme-int2-distributed-training-e6189947ab5f` | `` | research_outcome:not_export_status |  |
| `vram-aware-adaptive-cascade-routing-for-local-model-serving-9e2ace9a229b` | `` | research_outcome:not_export_status |  |
| `wall-clock-kv-cache-validation-of-layer-1-auxiliary-specul-d98f2cad62` | `negative` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `whole-model-gpt-2-sub-2-bit-activation-residual-validation-3f4005b310` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `window-level-entropy-router-across-independent-corpora-5c872700d2` | `negative` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `worker-idle-proof-heartbeat-20260508-night32` | `` | research_outcome:not_export_status | missing_research_source_lineage; source_records:queue_project_metadata |
| `zero-knowledge-evidence-compression-for-long-context-agent-audits-b4ff294d8f60` | `` | research_outcome:not_export_status |  |
| `zero-overhead-speculative-decoding-via-adaptive-n-gram-drafting-from-output-history-05a7f18af9db` | `` | research_outcome:not_export_status |  |
| `zero-vram-speculative-decoding-via-context-suffix-retrieval-and-attention-guided-prediction-fc8adc5bf297` | `` | research_outcome:not_export_status |  |
| `zstd-density-selection-for-cpu-bound-tiny-pretraining-96819a9549c0` | `` | research_outcome:not_export_status |  |
| `zstd-density-selection-for-data-loader-bound-pretokenized-47dc98063d` | `` | research_outcome:not_export_status |  |

