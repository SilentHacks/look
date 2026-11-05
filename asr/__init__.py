"""In-process Apple-silicon speech recognition for hermes-gaze.

``coreml_model`` is a pyobjc-based ``CompiledMLModel`` replacement (no
coremltools, no sidecar interpreter); ``parakeet_coreml`` is the Parakeet TDT
greedy decode loop vendored from silicon-asr and rewired onto it.
"""
