"""Plain-language strings shown to the owner: subject names, spoken text, error sentences.

Pure stdlib. Everything here treats model and page text as untrusted content.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

MAX_SUBJECT = 32
FALLBACK_SUBJECT = "This part of the page"
# Protocol tokens and internal handles must never reach a name.
_PROTOCOL = re.compile(
    r"@\d+|</?[a-z_]+>|\[browsing inbox|\bresolution[_ ]?(id)?\s*:?\s*\d+|gaze_[a-z]+|browser_context|page_data|snapshot",
    re.IGNORECASE)
_TRAILING_WEAK = {"a", "an", "and", "at", "by", "for", "from", "in", "of", "on", "or", "over", "that", "the",
                  "to", "with", "which", "who", "is", "are", "gives", "can", "using", "via", "your", "my"}


def clean_subject(raw: object, limit: int = MAX_SUBJECT) -> str:
    """A short human name from untrusted text, cut at a natural boundary. Empty if unusable."""
    text = re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f*`#|<>\[\]{}]", " ", str(raw or ""))).strip()
    if not text or _PROTOCOL.search(str(raw or "")):
        return ""
    text = re.sub(r"^\(?(?:new|sale|hot|ad|sponsored)\)?[:\s-]+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^[\d.,#)\s]+(?=\D)", "", text)
    text = re.sub(r"^(?:[$£€]\s?[\d.,]+[\s–—-]*)+", "", text)
    text = re.sub(r"^(?:a|an|the)\s+", "", text, flags=re.IGNORECASE).strip(" .,:;–—-\"'“”")
    if len(text) > limit:
        for mark in (": ", " – ", " — ", " - ", " | ", ", ", ". ", " ("):
            head = text.split(mark, 1)[0].strip()
            if 6 <= len(head) <= limit:
                text = head
                break
    if len(text) > limit:
        words, kept = text.split(" "), []
        for word in words:
            if len(" ".join(kept + [word])) > limit:
                break
            kept.append(word)
        while len(kept) > 1 and kept[-1].lower().strip(",.:;") in _TRAILING_WEAK:
            kept.pop()
        text = " ".join(kept) or text[:limit]
    return text.strip(" .,:;–—-\"'“”")


def subject_hint(raw: object) -> tuple[str, int]:
    """Validate the overlay's name and pointed-thing count; names stay plain text only."""
    if not isinstance(raw, dict):
        return "", 1
    try:
        count = max(1, min(5, int(raw.get("count") or 1)))
    except (TypeError, ValueError):
        count = 1
    # Already-built names keep their separators ("Japan · GDP"); only strip markup and protocol.
    name = str(raw.get("name") or "")[:80]
    if _PROTOCOL.search(name):
        return "", count
    name = re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f*`#|<>\[\]{}]", " ", name)).strip()
    return name[:64], count



def plain_error(status: str, error: str) -> str:
    """One plain sentence for the card. Raw provider and host text stays out of the UI."""
    text = str(error or "")
    lower = text.lower()
    if status == "interrupted" and ("disconnect" in lower):
        return "Hermes was disconnected before this finished."
    if status == "interrupted":
        return "This answer was interrupted."
    if "no speech" in lower:
        return "I didn’t catch that; hold Space, wait for Listening, then ask again."
    if "send one normal hermes message" in lower:
        return "Hermes isn’t ready yet. Send it one normal message, then try again."
    if "injection outcome unknown" in lower:
        return "Hermes may not have received this question."
    if "no available cursor target" in lower or "target unavailable" in lower:
        return "I couldn’t tell what you were pointing at."
    if "capture" in lower and ("no transcribed" in lower or "no longer" in lower):
        return "That recording is no longer available."
    if "read aloud" in lower and "stopping" in lower:
        return "Read aloud is stopping. Wait, then hold Space again."
    if "microphone" in lower or "portaudio" in lower or "input device" in lower:
        if "permission" in lower or "denied" in lower or "not permitted" in lower:
            return "Microphone denied. Allow your terminal in settings, then restart it."
        if "already in use" in lower or "closing" in lower:
            return "Microphone busy. Let go of Space, wait, then hold again."
        return "Microphone failed. Check input and permission, then try again."
    if "downloaded speech file changed" in lower:
        return "A downloaded speech file changed. Preparation stopped; do not use this cache."
    if "speech recognition is not ready" in lower or "preparing local speech recognition" in lower:
        return "Local speech recognition is not ready. Run /look setup; use Right Option to type."
    if "speech model" in lower:
        return "Speech model unavailable. Check internet and disk space; restart Hermes."
    if any(word in lower for word in ("transcri", "recognition", "whisper", "parakeet", "asr")):
        return "Speech recognition failed. Try again, or use Right Option to type."
    if "rate" in lower and "limit" in lower or "429" in lower or "quota" in lower:
        return "Hermes is rate limited right now."
    return "Hermes couldn’t finish this answer." if text or status == "failed" else ""


def speech_text(markdown: object) -> str:
    """Answer text for /usr/bin/say: words only, no markup characters."""
    text = str(markdown or "").replace("\r", "")
    lines, fence = [], False
    for line in text.split("\n"):
        stripped = line.strip()
        if re.match(r"^(`{3,}|~{3,})", stripped):
            if not fence:
                lines.append("Code block.")
            fence = not fence
            continue
        if fence:
            continue
        if re.fullmatch(r"\|?[\s:|-]*-{2,}[\s:|-]*\|?", stripped) and "|" in stripped or \
                re.fullmatch(r"([-*_])(\s*\1){2,}", stripped):
            continue
        if stripped.startswith("|") or stripped.count("|") >= 2:
            stripped = ", ".join(cell.strip() for cell in stripped.strip("|").split("|") if cell.strip())
            line = stripped + "."
        line = re.sub(r"^\s{0,3}#{1,6}\s+", "", line)
        line = re.sub(r"^\s*>\s?", "", line)
        line = re.sub(r"^\s*(?:[-*+]|\d{1,3}[.)])\s+", "", line)
        lines.append(line)
    text = "\n".join(lines)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"(?<![\w/])https?://([^\s/)]+)[^\s)]*", r"\1", text)
    text = re.sub(r"`+([^`]*)`+", r"\1", text)
    text = re.sub(r"(\*\*|__|~~)", "", text)
    text = re.sub(r"(?<![\w*])[*_](?=\S)|(?<=\S)[*_](?![\w*])", "", text)
    text = re.sub(r"\\([\\`*_{}\[\]()#+\-.!|>~])", r"\1", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def safe_link(url: object) -> str:
    """An http(s) destination the user clicked, with no credentials or control characters."""
    text = str(url or "")
    if not text or len(text) > 2048 or re.search(r"[\x00-\x20\x7f\\]", text):
        return ""
    try:
        parts = urlsplit(text)
    except ValueError:
        return ""
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        return ""
    return text
