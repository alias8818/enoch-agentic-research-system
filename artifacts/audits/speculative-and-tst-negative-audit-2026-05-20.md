# Speculative/TST Project Negative Audit — 2026-05-20

Live source: enoch-core local Postgres and `/var/lib/enoch-control-plane/projects` inspected on 2026-05-20 UTC.

## Scope

This audit covers the manually admitted/speculative-decoding and token-superposition/TST chain that started from:

- `spec-decoding-oracle-trace-ranker-20250519`
- `tst-branch-oracle-ranking-experiment-4f7a2b8c1e3d`

The goal was to verify whether the completed projects were genuinely non-paper/negative rather than accidentally hidden positives.

## Result

All five inspected runs are currently `completed` with `decision_gate_state=negative` and `decision_summary="finalize_negative (project decision is not positive)"`.

None is currently paper-writable:

- `bounded_paper_ready=false` in each decision payload.
- No inspected row has a positive paper gate.
- Local artifact roots contain `run_notes.md` plus `.enoch/project_decision.json` and `.omx/project_decision.json`; no separate `results/*.json` files were present in these five local roots.

## Project-by-project audit

| Depth | Project | Outcome | Hypothesis | Evidence | Follow-up | Paper-ready? | Audit read |
|---:|---|---|---|---|---|---|---|
| 0 | `spec-decoding-oracle-trace-ranker-20250519` | useful_signal | mixed | moderate | `Real DFlash Trace Ranking Against Cost-Adjusted Survival` | no | Synthetic DFlash-like ranker found cost-adjusted survival to be strong, but learned trace ranking did not beat the simple heuristic. This is useful baseline evidence, not a direct DFlash paper claim. |
| 1 | `real-dflash-trace-ranking-against-cost-adjusted-survival-13c27b8e4d` | useful_signal | unsupported | moderate | `Calibrated Survival Ranking on Actual DFlash Trace Logs` | no | Small GPT-2/distilgpt2 stand-in falsified uncalibrated survival ranking; static train-best recovered more oracle score. Not actual DFlash. |
| 0 | `tst-branch-oracle-ranking-experiment-4f7a2b8c1e3d` | useful_signal | mixed | moderate | `Mixed-Regime Calibration for Robust TST Branch Proxy Ranking` | no | Synthetic TST analogue showed in-distribution signal but failed stress robustness versus a cheap heuristic. |
| 1 | `mixed-regime-calibration-for-robust-tst-branch-proxy-ranki-68ffe6cb36` | useful_signal | supported | moderate | `Real-Trace Mixed-Regime Calibration for TST Branch Ranking` | no | Mixed-regime calibration worked in controlled synthetic TST-like simulation, but remained synthetic and explicitly no-paper. |
| 2 | `real-trace-mixed-regime-calibration-for-tst-branch-ranking-c01417d330` | negative | unsupported | moderate | none | no | Real Markdown trace/n-gram branch test showed mixed-regime calibration slightly harmed top-1 and regret versus raw proxy/global calibration. This falsified the local success threshold. |

## Conclusion

The chain did not hide a paper-positive result under the current deterministic gates. It produced several useful local signals and follow-up breadcrumbs, then ended with a real-trace negative on the TST calibration branch. The speculative/DFlash branch remains potentially interesting only if actual DFlash traces become available; the current local evidence is not sufficient for a paper.

## Follow-up recommendation

Keep these as preserved useful signals, not paper candidates. If revisited, require actual DFlash/DFlash-like traces or real transformer TST branch traces before spending more GB10 time.
