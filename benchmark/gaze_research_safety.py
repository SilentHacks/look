"""Fixed safety ablations of frozen research choices; no search or reselection.

Run scripts/gaze.py research-safety FEATURES --out SAME_RESEARCH_DIRECTORY.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path

from . import gaze_research
from .gaze_eval import evaluation_pairs, private_directory, save_json
from .gaze_research import Candidate, run


def safety_ablations(data, selection):
    rows = []
    for protocol in ("same-session", "cross-condition"):
        pairs = [(a, b) for a, b in evaluation_pairs(data, protocol) if a is not None
                 and (protocol != "same-session" or a is b)]
        for points in (9, 16, 25):
            for source, target in pairs:
                choices = [c for c in selection["choices"] if c["protocol"] == protocol and c["points"] == points
                           and c["glasses"] in ("all", target["glasses"])]
                for choice in choices:
                    candidate = replace(Candidate(**choice["candidate"]), tolerance=0.)
                    label = ("global" if choice["glasses"] == "all" else "eyewear") + "-strict"
                    rows.append(dict(run(candidate, points, source, target, {"validation-end"}),
                                     protocol=protocol, label=label))
                if protocol == "cross-condition":
                    for count in (1, 3, 5):
                        rows.append(dict(run(Candidate(bias_points=count), points, source, target, {"validation-end"}),
                                         protocol=protocol, label=f"baseline-bias{count}"))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("features", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = private_directory(args.out)
    selection = json.loads((out / "selection.json").read_text())
    if selection["features_sha256"] != hashlib.sha256(args.features.read_bytes()).hexdigest():
        parser.error("Features changed since selection")
    if selection["code_sha256"] != hashlib.sha256(Path(gaze_research.__file__).read_bytes()).hexdigest():
        parser.error("Research code changed since selection")
    rows = safety_ablations(json.loads(args.features.read_text()), selection)
    save_json(out / "safety-ablations.json", rows)
    print(f"Reported {len(rows)} fixed safety-ablation rows; no reselection")


if __name__ == "__main__":
    main()
