# Dataset decision

Public gaze datasets were surveyed and are not used by this project. Available
releases had research-only or unclear reuse terms, access agreements, large disk
requirements, cropped eyes rather than full faces, or sparse stills without the
continuous timing and controlled camera/posture/glasses changes we need.

All tuning now uses our own consented, pseudonymous local recordings. Keep original
camera video and target timestamps so future extractors can reuse the evidence.
No public dataset loader, download recipe, public-data scoreboard, pretrained gaze
checkpoint or public-data fit is part of the evaluation path. The Apache-2.0
MediaPipe face localizer is unchanged. It is not a pretrained gaze estimator.

See [the recording guide](GAZE_RECORDING.md) and [evaluation protocols](GAZE_EVAL.md).
