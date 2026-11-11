# Personal-calibration estimator research — 2026-11-08

## 1. Outcome

Saved eye-appearance features support substantially better fresh personal calibration: nine-point strict-rejection ridge reached **79.9% / 71.0% 3×3 hits without / with glasses**, versus **69.6% / 21.3% baseline**, on reserved end validation. Keep nine points, treat webcam as experimental broad-region input, and recalibrate after posture or eyewear changes; no live defaults changed.

## 2. Changes and scope

Branch: `research/gaze-tuning`. Evaluation-only files:

- `benchmark/gaze_research.py`: finite two-rung estimator search, frozen choices, aggregate final reporting.
- `benchmark/gaze_research_safety.py`: fixed strict-rejection and baseline-bias ablations; no reselection.
- `scripts/gaze.py`: `research` and `research-safety` commands.
- `tests/test_gaze_research.py`: five behavior regressions.
- `docs/GAZE_EVAL.md` and this report: protocol, reproduction and evidence.

No changes to `tracker/webcam_gaze.py`, live calibration, registration, assets or dependencies. No Chrome, webcam, microphone or speakers were opened. No recordings/frames, live calibration directories, `.env` or Hermes state were read or modified. The missing worktree `.venv` was linked to the existing project environment; no installation.

Local outputs: `~/.cache/look-eval/p-a7c4-tuning/` (existing tuning), with new research aggregates under `research/`. Existing tuning writes its normal private traces there; **none are included in Git or this report**. Research output contains only per-session aggregates and configuration metadata, not features, predictions or fitted weights.

## 3. Verification and separation

### Runs actually completed

- Existing tool first: `.venv/bin/python scripts/gaze.py tune FEATURES --points 9 16 25 --out ~/.cache/look-eval/p-a7c4-tuning` — **792 rows**, **6.98 s**.
- Research `--stage select` — **329 distinct specifications**, **869 point/protocol configurations**, **5,214 development fit/target rows**, **656 failed fits retained as zero hits**; **18 frozen choices**, **61.13 s**.
- Research `--stage report` — **108 final per-session rows**, **36 aggregate comparisons**, **1.59 s**.
- `research-safety` — **126 fixed per-session ablation rows**, **1.10 s**; no new search.
- `.venv/bin/python -m unittest tests.test_gaze_research` — **5 tests, 0.028 s, OK**.
- `.venv/bin/python -m unittest discover -s tests -t .` — final run **204 tests, 2.916 s, OK**. The suite's simulated CoreML failure printed its expected fallback diagnostic.
- Python syntax compilation passed for `benchmark/gaze_research.py`, `benchmark/gaze_research_safety.py`, `scripts/gaze.py` and `tests/test_gaze_research.py`; both research CLIs were also executed successfully.
- Ruff was unavailable (`No module named ruff`); no dependency was installed to run it.

The initial `.venv/bin/python` attempt failed because this worktree lacked the environment; it did not run tuning. All successful runs used the existing environment after linking it.

### Data and leakage boundary

Eight sessions, one person, one camera/display, one day; 4,814 extracted frames, stride 2 from 15fps. Only the supplied features file and aggregate existing scores were read; no pixels or recordings were accessed.

1. Spatial 9/16/25 selection reuses `split_frames`: initial calibration only, label-only farthest-point selection before gating. Normalization and estimator weights use only those calibration frames, at least 45 valid samples, distinct targets/movement, and normalized training RMSE ≤ .20.
2. **Every `validation-end` frame is removed before selection.** Fixed/moving/reading phases are development data, with exact selected-calibration coordinates excluded. Those development scores are not claimed as held-out performance. The required existing tuning command also computes built-in validation diagnostics; those fields were not consulted for selection.
3. Search objective: equal-session mean of 3×3/4×4/5×5 full-denominator hits. Missing faces, gates, off-screen rejection and failed fits are misses. Fits are personal and never pool observations across sessions or eyewear; reuse explicitly applies an earlier same-eyewear fit.
4. Candidate families: baseline/individual/both/mean eyes, head-local pose and pose eyes, full/individual-eye appearance and appearance without head inputs; ridge λ=.1/1/10/100/1000; polynomial and RBF terms. Top three development candidates per stratum then try Huber fitting, loose/tight blink gates, EMA 60/120/240ms, edge tolerances .02/.05/.10, and 1/3/5-point bias refresh on reuse.
5. Bias refresh uses only selected labelled **validation-start** locations, with equal target weighting and median residuals. It corrects raw predictions **before** screen rejection; otherwise zero-coverage fits cannot be rescued. Start labels are calibration cost, never final test labels. Both the development interval and final end probe occur after refresh.
6. Choices were frozen to `selection.json` before final reporting. Feature-file and research-source SHA256 checks prevent accidental input changes/reselection. Fixed safety ablations remove edge tolerance or add baseline bias refresh; they do not optimize on end validation.
7. Final figures use **validation-end only**. Fresh fits cover three sessions per eyewear; reuse covers distance/head/no-recalibration, using the earlier upright source of the same eyewear. These evaluations overlap target sessions and are not independent repetitions.

**Uncertainty:** phase separation, not independent-session generalization or nested LOSO. End probes are stationary, near edges, and repeat some calibration coordinates; they do not establish moving-target or unseen-location performance. The same-session recording and person are shared with development; physiology, session order and protocol are not controlled. Three sessions per stratum are too few for useful population confidence intervals; session ranges are given instead. No final score was used to choose or revise configurations.

### Primary final comparisons: baseline versus shared selected estimator, STRICT rejection

All hits/coverage are percentages. Equal-session weighting; missing predictions remain misses. Pixel means and p95 are conditional on prediction. Aggregate error columns are **mean session mean / mean session p95**, not pooled quantiles; exact per-session p95 follows below and is retained for every candidate in JSON. Jitter is adjacent stationary-target RMS displacement (≤250ms gaps); sampled cadence is about 7.5Hz, not measured live jitter.

For fresh fits, shared choices are left-eye appearance + its iris coordinates, linear ridge λ10 at 9/25 points; full appearance + original eight features, λ10 at 16 points. Strict variants disable only the development-selected edge tolerance. For posture reuse, shared choices are both-eye coordinates with RBF ridge λ1 (9/16) or λ10 (25), plus **five labelled refresh points**, strict screen rejection. Thus reuse candidate costs include refresh; baseline has none.

| Use | Eyewear | Points | Candidate | 3×3 | 4×4 | 5×5 | Coverage | px mean / mean session p95 | Jitter px | Python CPU ms |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| Fresh fit | none | 9 | baseline | 69.6 | 43.9 | 29.3 | 93.8 | 160.8 / 298.4 | 70.2 | 0.013 |
| Fresh fit | none | 9 | global-strict | 79.9 | 59.7 | 58.4 | 97.0 | 117.5 / 244.7 | 89.6 | 0.014 |
| Fresh fit | none | 16 | baseline | 79.4 | 47.0 | 39.6 | 100.0 | 146.2 / 294.3 | 68.9 | 0.015 |
| Fresh fit | none | 16 | global-strict | 90.1 | 57.8 | 62.1 | 98.3 | 103.2 / 219.0 | 84.0 | 0.015 |
| Fresh fit | none | 25 | baseline | 80.1 | 53.5 | 39.1 | 100.0 | 140.6 / 287.2 | 67.9 | 0.012 |
| Fresh fit | none | 25 | global-strict | 90.9 | 58.5 | 59.3 | 98.9 | 98.1 / 198.7 | 83.5 | 0.013 |
| Fresh fit | glasses | 9 | baseline | 21.3 | 12.3 | 9.3 | 60.8 | 437.9 / 622.9 | 113.8 | 0.010 |
| Fresh fit | glasses | 9 | global-strict | 71.0 | 31.8 | 30.7 | 87.7 | 136.8 / 227.1 | 83.0 | 0.013 |
| Fresh fit | glasses | 16 | baseline | 19.1 | 9.9 | 5.6 | 45.6 | 498.3 / 614.8 | 94.1 | 0.008 |
| Fresh fit | glasses | 16 | global-strict | 44.2 | 10.8 | 16.1 | 79.5 | 190.0 / 284.5 | 97.4 | 0.014 |
| Fresh fit | glasses | 25 | baseline | 9.3 | 8.6 | 3.7 | 44.8 | 457.1 / 589.3 | 140.6 | 0.009 |
| Fresh fit | glasses | 25 | global-strict | 72.0 | 36.0 | 34.0 | 85.7 | 125.3 / 200.5 | 79.1 | 0.013 |
| Posture reuse | none | 9 | baseline | 0.0 | 0.0 | 0.0 | 8.6 | 918.2 / 981.5 | 59.0 | 0.007 |
| Posture reuse | none | 9 | global-strict | 73.8 | 48.7 | 38.4 | 97.6 | 136.8 / 250.2 | 70.4 | 0.017 |
| Posture reuse | none | 16 | baseline | 0.0 | 0.0 | 0.0 | 11.1 | 895.5 / 989.4 | 52.6 | 0.007 |
| Posture reuse | none | 16 | global-strict | 74.8 | 44.0 | 34.0 | 98.1 | 135.8 / 264.3 | 67.8 | 0.017 |
| Posture reuse | none | 25 | baseline | 0.0 | 0.0 | 0.0 | 17.3 | 630.7 / 753.2 | 49.0 | 0.008 |
| Posture reuse | none | 25 | global-strict | 79.2 | 44.0 | 29.5 | 100.0 | 141.2 / 261.5 | 66.9 | 0.019 |
| Posture reuse | glasses | 9 | baseline | 0.0 | 0.0 | 0.0 | 20.4 | 1063.1 / 1186.9 | 79.1 | 0.010 |
| Posture reuse | glasses | 9 | global-strict | 33.3 | 16.0 | 25.3 | 96.9 | 262.4 / 513.5 | 80.5 | 0.015 |
| Posture reuse | glasses | 16 | baseline | 1.2 | 1.2 | 0.6 | 28.4 | 470.6 / 661.7 | 105.2 | 0.007 |
| Posture reuse | glasses | 16 | global-strict | 33.3 | 11.7 | 18.5 | 98.8 | 280.1 / 525.9 | 77.2 | 0.017 |
| Posture reuse | glasses | 25 | baseline | 0.0 | 0.0 | 0.0 | 24.7 | 533.8 / 701.0 | 99.2 | 0.010 |
| Posture reuse | glasses | 25 | global-strict | 38.9 | 23.5 | 15.4 | 98.8 | 288.1 / 585.8 | 66.2 | 0.018 |

### Eyewear-specific selection, as frozen (includes selected tolerance)

This is a second candidate policy, selected on development by eyewear, not fitted cross-session weights. It is not consistently better than the shared policy. Fresh choices: no glasses full appearance λ10; glasses left appearance λ1 at 9, appearance without head λ10 at 16, left appearance λ100 at 25. All fresh choices selected .10 normalized edge tolerance; their clamping is **not recommended for shipping**. Reuse choices: no glasses the shared RBF; glasses right appearance λ1000 + one refresh point (9), appearance without head λ1 + five refresh points + EMA120ms (16), eyes-only linear λ100 + five refresh points (25).

| Use | Eyewear | Points | Candidate | 3×3 | 4×4 | 5×5 | Coverage | px mean / mean session p95 | Jitter px | Python CPU ms |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| Fresh fit | glasses | 9 | eyewear-selected | 67.4 | 40.7 | 36.2 | 93.7 | 144.1 / 239.7 | 97.0 | 0.015 |
| Fresh fit | none | 9 | eyewear-selected | 85.0 | 57.2 | 57.3 | 100.0 | 115.9 / 233.4 | 91.0 | 0.015 |
| Fresh fit | glasses | 16 | eyewear-selected | 60.1 | 23.7 | 29.5 | 93.5 | 169.7 / 274.1 | 95.5 | 0.019 |
| Fresh fit | none | 16 | eyewear-selected | 91.8 | 57.8 | 62.7 | 100.0 | 104.7 / 219.7 | 84.7 | 0.030 |
| Fresh fit | glasses | 25 | eyewear-selected | 79.5 | 41.5 | 43.8 | 96.7 | 133.2 / 219.9 | 80.7 | 0.015 |
| Fresh fit | none | 25 | eyewear-selected | 96.6 | 63.9 | 63.9 | 100.0 | 98.5 / 194.9 | 83.0 | 0.019 |
| Posture reuse | glasses | 9 | eyewear-selected | 48.8 | 10.5 | 11.7 | 100.0 | 232.2 / 364.2 | 66.9 | 0.015 |
| Posture reuse | none | 9 | eyewear-selected | 76.2 | 51.1 | 40.7 | 100.0 | 136.0 / 249.6 | 70.2 | 0.016 |
| Posture reuse | glasses | 16 | eyewear-selected | 45.7 | 29.6 | 27.2 | 75.3 | 198.0 / 348.7 | 79.8 | 0.020 |
| Posture reuse | none | 16 | eyewear-selected | 76.6 | 45.9 | 35.8 | 100.0 | 135.3 / 263.4 | 67.1 | 0.018 |
| Posture reuse | glasses | 25 | eyewear-selected | 51.2 | 32.1 | 19.8 | 100.0 | 209.8 / 392.3 | 66.8 | 0.012 |
| Posture reuse | none | 25 | eyewear-selected | 79.2 | 44.0 | 29.5 | 100.0 | 141.2 / 261.5 | 66.9 | 0.018 |

The standard `FINAL.md` additionally reports the shared policy with its development-selected tolerance, and `final.json` retains every per-session error quantile, CPU, wall time, saved inference and rejection count. `safety-ablations.json` retains all strict and baseline-refresh comparisons.

### Exact per-session errors: nine-point shared STRICT candidate

Fresh = appearance ridge λ10. Reuse = RBF eyes λ1 plus five labelled refresh points. This table gives actual per-session p95, not averaged p95.

| Use | Eyewear | Condition | 3×3 | 4×4 | 5×5 | Coverage | px mean | px p95 | Jitter px |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| Fresh | glasses | upright | 66.7 | 27.0 | 25.4 | 87.3 | 137.1 | 242.1 | 104.6 |
| Fresh | glasses | distance | 87.0 | 48.1 | 46.3 | 90.7 | 103.7 | 172.8 | 66.0 |
| Fresh | glasses | head | 59.3 | 20.4 | 20.4 | 85.2 | 169.7 | 266.4 | 78.5 |
| Fresh | none | upright | 96.3 | 74.1 | 68.5 | 100.0 | 91.6 | 181.2 | 86.2 |
| Fresh | none | distance | 59.3 | 57.4 | 46.3 | 92.6 | 154.2 | 333.3 | 89.0 |
| Fresh | none | head | 84.1 | 47.6 | 60.3 | 98.4 | 106.8 | 219.5 | 93.7 |
| Reuse + 5-point refresh | glasses | distance | 33.3 | 11.1 | 33.3 | 100.0 | 279.4 | 648.2 | 45.6 |
| Reuse + 5-point refresh | glasses | head | 42.6 | 11.1 | 27.8 | 100.0 | 250.3 | 469.2 | 102.8 |
| Reuse + 5-point refresh | glasses | no-recalibration | 24.1 | 25.9 | 14.8 | 90.7 | 257.3 | 423.3 | 93.2 |
| Reuse + 5-point refresh | none | distance | 75.9 | 55.6 | 35.2 | 100.0 | 140.6 | 249.0 | 69.0 |
| Reuse + 5-point refresh | none | head | 71.4 | 46.0 | 42.9 | 98.4 | 130.2 | 264.2 | 74.0 |
| Reuse + 5-point refresh | none | no-recalibration | 74.1 | 44.4 | 37.0 | 94.4 | 139.5 | 237.5 | 68.2 |

Fresh strict nine-point 3×3 ranges: **59.3–96.3% without glasses**, **59.3–87.0% with glasses**. Reuse strict nine-point + five labels: **71.4–75.9% without**, **24.1–42.6% with glasses**. These broad ranges matter more than a decimal-place difference between candidates.

### Calibration time, latency, CPU and smoothing

- 9/16/25 points imply nominal **10.8 / 19.2 / 30.0 s active dwell** at the recorder's 1.2s/point, plus transitions. However, these are subsets of one randomized 25-point acquisition, not measured standalone shorter calibrations. The live nine-point UI uses .1/.5/.9 coordinates and user-triggered 1.1s holds; offline subsets use the recorder's wider .04-to-.96 grid. A later live cutover must validate that geometry/cadence difference.
- 1/3/5 refresh labels nominally add **1.2 / 3.6 / 6.0 s dwell**. Here those locations were selected from the existing full start-validation block, not acquired as a standalone short interaction. All selected initial/refresh observations and costs are counted; none use end labels.
- Shared nine-point appearance predictor: Python CPU **.018ms/frame**, versus roughly **.010–.013ms** baseline in the same evaluator. Nine-point fitting was about **.27–2.11ms CPU**. These microsecond differences are noisy and include Python evaluation overhead, not just linear algebra.
- Saved appearance inference averaged **17.61ms with glasses / 17.78ms without** on final probes. The recorded marginal patch-extraction wall time averaged **2.53 / 2.58ms**, p95 **2.9 / 3.0ms**, versus iris extraction. Whole saved extractor CPU averaged **20.50 / 21.00ms/frame**, and cannot isolate patch-only CPU. No new camera-to-answer latency, live process CPU, power or thermal measurement was made.
- Raw ridge adds no temporal buffering. A 120ms EMA lowered development jitter **80.3→53.0px**, but lowered 3×3/4×4/5×5 hits **62.5/55.9/38.9→61.9/53.9/37.3%** for the shared nine-point appearance model at strict rejection. Estimated discrete low-frequency delay was **65.5ms** at sampled cadence; 60ms/240ms EMA delays were **16.3/179.6ms**. This is added filter delay, not device latency. No causal filter fills missing samples or crosses >250ms gaps. The fresh final selection stayed unsmoothed; jitter without glasses rose relative to baseline despite better accuracy.

## 4. Surprises and plan changes

- **Appearance, not more iris/head algebra, is the useful next direction.** Existing default appearance ridge at 25 points improved development 3×3 from 61.6→70.8% without glasses and 36.6→65.8% with glasses. These are exploratory fixed/moving/reading results, not the final figures above. Polynomial/head-local variants, Huber reweighting and blink gates did not consistently win. Normalization stayed calibration-only; no new normalizer or external weights were justified.
- **The first glasses session is not the only failure.** At nine points the later glasses/head baseline had only 9.3% end coverage and 0% 3×3 hits, versus 85.2% coverage / 59.3% hits for strict appearance. The older upright session remains confounded by protocol/order/interruption; these data cannot attribute its weakness to glasses alone.
- **More points are not reliably better.** Shared strict glasses 3×3: 71.0% at nine, 44.2% at sixteen, 72.0% at twenty-five. Without glasses: 79.9%, 90.1%, 90.9%. Twenty-five improves no-glasses mean error by about 19px but triples nominal dwell; sixteen has a poor glasses failure. Do not replace nine as the general default from this evidence.
- **Tolerance can disguise coverage loss.** The selected .10 tolerance allows up to 144px horizontally / 81px vertically beyond the collection viewport, then clamps. Shared nine-point glasses 3×3 becomes 80.6% with tolerance versus 71.0% strict, and coverage 97.4% versus 87.7%. Much of that gain is edge assignment, not better calibration; it can put unrelated edge controls under gaze. Keep strict rejection for a shipping candidate.
- **A tiny labelled refresh rescues some reuse but is not universal correction.** Original nine-point ridge + one label raised no-glasses end coverage 8.6→94.5%, 3×3 0→67.6%, but glasses reached only 32.7% 3×3 and 293px conditional mean error. The frozen five-label RBF policy reaches 73.8% no-glasses versus 33.3% glasses with strict rejection. An eyewear-specific nine-point one-label model reaches 48.8% glasses 3×3 but only 10.5% 4×4 and 11.7% 5×5; that is not robust reuse.

## 5. Recommendation and remaining decisions

**Next shipping candidate:** nine-point personal **left-eye appearance + iris, standardized linear ridge λ10, strict off-screen rejection, no EMA**, exposed as experimental, opt-in broad-region gaze. The current live collector does not supply appearance features; implementing/auditing that cutover is a separate shipping task, not accomplished or installed by this branch. Do not promise button precision or unattended posture reuse. No extra library, checkpoint, hosted service or eyewear-specific model is justified.

**Keep nine points.** Twenty-five can be an optional longer calibration only after a separate user-run live comparison confirms its no-glasses benefit; sixteen is not supported as a universal upgrade. Keep calibration matched to eyewear and tell users: **recalibrate after leaning back, changing head/lid/camera position or changing glasses; recalibrate if delivery drops.** A pointer-anchor problem is different and still requires pointer movement, not eye calibration.

Before the later shipping decision, the user should run the candidate on the actual live runtime and measure delivered coverage, perceived jitter and end-to-end delay. Then collect another day with eyewear order reversed and repeat the old upright condition. That addresses session/day/order confounding better than more search on these eight recordings. The milestone itself has no unresolved implementation dependency; production cutover and whether an optional longer calibration is worth its cost remain controller decisions.

## 6. Spend and boundary incident

**$0.0000 new spend reported by tools; no successful hosted inference, no installs.** One repository-only semantic-search helper unexpectedly attempted hosted judging; all requests were rejected with HTTP403 and its result reported $0.0000. It received repository search context, not personal features or recordings; it was not used again. All estimator fitting, selection and scoring ran locally on already-extracted features.

## Reproduction and retained outputs

From repository root, using the existing project environment:

```bash
CACHE="$HOME/.cache/look-eval"
FEATURES="$CACHE/p-a7c4-features/features.json"
OUT="$CACHE/p-a7c4-tuning"
.venv/bin/python scripts/gaze.py tune "$FEATURES" --points 9 16 25 --out "$OUT"
.venv/bin/python scripts/gaze.py research "$FEATURES" --out "$OUT/research" --stage select
.venv/bin/python scripts/gaze.py research "$FEATURES" --out "$OUT/research" --stage report
.venv/bin/python scripts/gaze.py research-safety "$FEATURES" --out "$OUT/research"
.venv/bin/python -m unittest discover -s tests -t .
```

The completed selection intentionally refuses overwrite; to repeat selection, choose a new child directory under `p-a7c4-tuning`. Reporting and fixed ablations can be rerun against frozen choices; timings will vary. `research/selection.json`, `development.json`, `final.json`, `final-summary.json`, `FINAL.md`, `safety-ablations.json` and this `REPORT.md` retain aggregates only. No push, PR or merge.
