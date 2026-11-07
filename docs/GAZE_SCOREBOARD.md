# Gaze dataset scoreboard

No human results from our own dataset have been recorded and scored yet.
Fake-device checks prove collection, portability and scoring plumbing only; they
are not human gaze accuracy. Previous public-data scores have been removed.

Keep the live nine-point MediaPipe iris/head ridge λ=1 unchanged. No tuning fit,
smoothing choice or larger calibration experiment is installed into the tracker.

After collecting both glasses rounds, run the commands in [GAZE_RECORDING.md](GAZE_RECORDING.md).
Private outputs are `results.json`, `summary.json`, `SCOREBOARD.md` and held-out
traces. Report 3×3 / 4×4 / 5×5 exact-cell hits, coverage and end-validation drift
per person, condition and glasses. Cross-person summaries weight people equally;
all models are still personally calibrated, not trained across people.

Do not select a winner on one person's aggregate alone. Compare calibrated
within-session, baseline-to-changed-condition without recalibration and
cross-glasses transfer separately. Add real observed results here only with the
protocol, calibration budget, people/session counts and held-out denominators.
