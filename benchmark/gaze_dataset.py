"""Private participant inventory and portable, path-checked recording bundles."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import zipfile

from .gaze_eval import CACHE, load_recording, private_directory, save_json

FILES = {"recording.json", "camera.webm", "targets.jsonl"}


def pseudonym(value):
    if not re.fullmatch(r"p-[a-z0-9]{4,24}", value):
        raise ValueError("Use an anonymous ID like p-a7c4, not a real name (p- plus 4–24 lowercase letters/digits)")
    return value


def inventory(root, person=None):
    root = Path(root).expanduser()
    if person is not None:
        pseudonym(person)
    rows = []
    for path in sorted(root.glob((person or "p-*") + "/*/recording.json")):
        if any(p.is_symlink() for p in (path, path.parent, path.parent.parent)):
            raise ValueError("Dataset entries must not be symlinks")
        meta = json.loads(path.read_text())
        if meta["person"] != path.parent.parent.name or meta["session"] != path.parent.name:
            raise ValueError("Recording identity does not match its directory")
        rows.append((path.parent, meta))
    return sorted(rows, key=lambda row: row[1].get("epoch", 0))


def export_person(root, person, archive):
    pseudonym(person)
    source = private_directory(Path(root) / person)
    rows = inventory(root, person)
    if not rows:
        raise ValueError("No sessions for this pseudonym")
    archive = Path(archive).expanduser()
    private_directory(archive.parent)
    if (source / "consent.json").is_symlink() or not (source / "consent.json").is_file():
        raise ValueError("Participant consent must be a regular local file")
    # Exclusive output: a mistyped path cannot replace an existing bundle.
    with archive.open("xb") as output:
        os.chmod(archive, 0o600)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as bundle:
            bundle.write(source / "consent.json", f"{person}/consent.json")
            for directory, meta in rows:
                if not meta.get("finished"):
                    continue
                for name in sorted(FILES):
                    path = directory / name
                    if path.is_symlink():
                        raise ValueError("Refusing a symlink in a recording")
                    bundle.write(path, f"{person}/{directory.name}/{name}")
    return archive


def import_person(archive, root):
    root = private_directory(Path(root))
    with zipfile.ZipFile(archive) as bundle, tempfile.TemporaryDirectory(prefix=".import-", dir=root) as tmp:
        entries = bundle.infolist()
        if not entries or sum(e.file_size for e in entries) > 4 * 1024 ** 3:
            raise ValueError("Empty bundle or bundle exceeds 4 GiB")
        names, people = set(), set()
        for entry in entries:
            parts = entry.filename.split("/")
            if entry.filename in names or any(p in ("", ".", "..") for p in parts):
                raise ValueError("Duplicate or unsafe bundle path")
            names.add(entry.filename)
            if len(parts) not in (2, 3) or parts[-1] not in FILES | {"consent.json"}:
                raise ValueError("Unexpected file in participant bundle")
            bounds = {"camera.webm": 512 * 1024 ** 2, "targets.jsonl": 8 * 1024 ** 2,
                      "recording.json": 65536, "consent.json": 8192}
            if entry.file_size > bounds[parts[-1]]:
                raise ValueError("Bundle member exceeds its private size bound")
            if len(parts) == 2 and parts[-1] != "consent.json" or len(parts) == 3 and parts[-1] not in FILES:
                raise ValueError("Invalid participant bundle layout")
            person = pseudonym(parts[0]); people.add(person)
            if len(parts) == 3 and not re.fullmatch(r"[a-zA-Z0-9-]{1,100}", parts[1]):
                raise ValueError("Invalid session ID")
            mode = entry.external_attr >> 16
            if mode and stat.S_IFMT(mode) not in (0, stat.S_IFREG):
                raise ValueError("Bundle may contain regular files only")
            dest = Path(tmp).joinpath(*parts)
            dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with bundle.open(entry) as src, dest.open("xb") as dst:
                dest.chmod(0o600); shutil.copyfileobj(src, dst)
        if len(people) != 1:
            raise ValueError("Import one person per bundle")
        person = people.pop()
        staged = Path(tmp) / person
        consent = json.loads((staged / "consent.json").read_text())
        if consent.get("person") != person or consent.get("accepted") is not True:
            raise ValueError("Missing participant consent")
        rows = inventory(Path(tmp), person)
        if not rows or {p.name for p in staged.iterdir() if p.is_dir()} != {d.name for d, _ in rows}:
            raise ValueError("Bundle has missing session metadata")
        for directory, meta in rows:
            if not meta.get("finished") or {p.name for p in directory.iterdir()} != FILES:
                raise ValueError("Bundle contains an unfinished session")
            source = meta.get("calibration_source")
            if source and source not in {d.name for d, _ in rows}:
                raise ValueError("Referenced calibration is missing from the bundle")
        dest = root / person
        if dest.is_symlink():
            raise ValueError("Participant directory must not be a symlink")
        # Validate all collisions before writing any session; identical imports are idempotent.
        for path in staged.rglob("*"):
            existing = dest / path.relative_to(staged)
            if existing.is_symlink():
                raise ValueError("Import destination contains a symlink")
            if existing.exists() and path.is_dir() != existing.is_dir():
                raise ValueError("Pseudonym/session collision: file and directory types differ")
            if path.is_file() and existing.exists():
                with path.open("rb") as a, existing.open("rb") as b:
                    if hashlib.file_digest(a, "sha256").digest() != hashlib.file_digest(b, "sha256").digest():
                        raise ValueError("Pseudonym/session collision; use a different ID on the source machine")
        private_directory(dest)
        for path in staged.rglob("*"):
            target = dest / path.relative_to(staged)
            if path.is_file() and not target.exists():
                private_directory(target.parent)
                shutil.move(str(path), target)
        return person


def load_dataset(root, out, person=None, stride=2):
    out = private_directory(Path(out))
    sessions = []
    for directory, meta in inventory(root, person):
        if meta.get("finished") and meta.get("complete"):
            data = load_recording(directory, out / meta["person"] / meta["session"], stride)
            sessions.extend(data["sessions"])
    if not sessions:
        raise ValueError("No complete sessions; unfinished recordings are retained but not scored")
    result = dict(version=1, dataset="owned-recordings", licence="Private participant recordings; local use only", sessions=sessions)
    save_json(out / "manifest.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=CACHE / "recordings")
    subs = parser.add_subparsers(dest="command", required=True)
    listing = subs.add_parser("list")
    listing.add_argument("--person")
    export = subs.add_parser("export")
    export.add_argument("--person", required=True)
    export.add_argument("--out", type=Path, required=True)
    importing = subs.add_parser("import")
    importing.add_argument("archive", type=Path)
    load = subs.add_parser("load")
    load.add_argument("--person")
    load.add_argument("--out", type=Path, required=True)
    load.add_argument("--stride", type=int, default=2)
    args = parser.parse_args()
    if args.command == "list":
        for directory, m in inventory(args.root, args.person):
            print(f"{m['person']}\t{m['session']}\t{m['condition']}\t{m['glasses']}\t{m['device']}\t"
                  f"{'complete' if m.get('complete') else 'partial'}\t{directory}")
    elif args.command == "export":
        print(export_person(args.root, args.person, args.out))
    elif args.command == "import":
        print("Imported " + import_person(args.archive, args.root))
    else:
        if args.stride < 1:
            parser.error("--stride must be positive")
        result = load_dataset(args.root, args.out, args.person, args.stride)
        print(f"Loaded {len(result['sessions'])} sessions into {args.out / 'manifest.json'}")


if __name__ == "__main__":
    main()
