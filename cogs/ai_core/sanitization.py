"""
Input Sanitization Module.
Provides functions to sanitize user input for safe use in Discord operations.
Protects against malicious input in AI-controlled operations.
"""

from __future__ import annotations

import re
import unicodedata

# Regex patterns for validation
_SAFE_CHANNEL_NAME = re.compile(r"[^a-zA-Z0-9\-_\u0E00-\u0E7F\s]")
_SAFE_ROLE_NAME = re.compile(r"[<>@#&]")

# Canonical bracketed-system-marker pattern, shared by every module that
# re-injects stored conversational content into a prompt (``memory/entity_memory``
# and ``memory/state_tracker``). Both used to carry their own copy and they drifted:
# state_tracker's was unanchored while entity_memory's was pinned to start-of-line,
# which \u2014 because every entity renderer emits ``<label>: <value>`` \u2014 meant the
# anchored copy could never fire on the fact values it was meant to protect. Keep
# this as the single definition so the two boundaries cannot diverge again.
#
# Matches from the marker to end of line so the injected *instruction* goes with
# the marker, not just the tag. ``ignore[^\]]*`` covers ``[ignore previous \u2026]``
# spellings; the plain reserved words require the bracket to close right after
# them (``\s*\]``) so ordinary text like ``[User Guide]`` is left alone.
SYSTEM_MARKER_RE = re.compile(r"(?im)\[\s*(?:system|inst|user|assistant|ignore[^\]]*)\s*\][^\n]*")


def sanitize_channel_name(name: str, max_length: int = 100) -> str:
    """Sanitize channel name to prevent injection attacks.

    Args:
        name: Raw channel name from AI
        max_length: Maximum allowed length

    Returns:
        Sanitized channel name
    """
    if not name:
        return "untitled"
    # Remove potentially dangerous characters
    cleaned = _SAFE_CHANNEL_NAME.sub("", name)
    # Normalize whitespace to dashes (Discord channel format)
    cleaned = re.sub(r"\s+", "-", cleaned.strip())
    # Remove consecutive dashes
    cleaned = re.sub(r"-+", "-", cleaned)
    # Limit length and remove leading/trailing dashes
    result = cleaned[:max_length].strip("-")
    return result or "untitled"


def sanitize_role_name(name: str, max_length: int = 100) -> str:
    """Sanitize role name to prevent mention injection.

    Args:
        name: Raw role name from AI
        max_length: Maximum allowed length

    Returns:
        Sanitized role name
    """
    if not name:
        return "unnamed-role"
    # Remove characters that could be used for mention injection
    cleaned = _SAFE_ROLE_NAME.sub("", name)
    return cleaned.strip()[:max_length] or "unnamed-role"


def escape_mentions(text: str) -> str:
    """Defang Discord mentions in ``text`` (NFKC width-fold + ZWSP inserts).

    Shared by :func:`sanitize_message_content` and ``send_as_webhook`` so both
    paths escape mentions with the SAME rules. Length truncation is intentionally
    NOT done here; callers that need a hard cap apply it after calling this.
    """
    # Escape dangerous mentions by inserting zero-width space.
    # NFKC normalisation handles compatibility decompositions like
    # full-width "\uff20" \u2192 "@" so the @everyone/@here regex below
    # catches them. NOTE: NFKC does NOT fold Latin/Cyrillic/Greek script
    # confusables (e.g. Cyrillic "\u0435" stays distinct from Latin "e"),
    # so a string like "@\u0435veryone" passes through unescaped. Discord
    # itself doesn't ping on confusables either, but be aware this is
    # NOT a confusables-defeating filter \u2014 only a width-fold one.
    text = unicodedata.normalize("NFKC", text)
    # Sanitize BEFORE truncation to avoid splitting escape sequences.
    # Idempotency guard: skip the substitution when a ZWSP is ALREADY
    # the next char after the ``@``. Without this, repeated sanitizer
    # passes (e.g. a value that's stored, fetched, and re-displayed)
    # accumulate ``\u200b`` chars: ``@everyone`` \u2192
    # ``@\u200beveryone`` \u2192 ``@\u200b\u200beveryone`` \u2192 \u2026 Use a
    # negative lookahead so the substitution only fires the first time.
    # Capture the keyword and re-emit it via a backreference so the original
    # casing is preserved (a fixed lowercase replacement under IGNORECASE would
    # silently fold "@EVERYONE" -> "@\u200beveryone", mangling the text). The
    # ZWSP still breaks the ping; matches the role/user-mention style below.
    text = re.sub(r"@(?!\u200b)(everyone)", "@\u200b\\1", text, flags=re.IGNORECASE)
    text = re.sub(r"@(?!\u200b)(here)", "@\u200b\\1", text, flags=re.IGNORECASE)

    # Escape role mentions (<@&ROLE_ID>) and user mentions (<@USER_ID>)
    # from AI output. Same idempotency guard via negative lookahead.
    text = re.sub(r"<@&(?!\u200b)(\d+)>", "<@&\u200b\\1>", text)
    # Capture the optional legacy-nickname bang so it survives the rewrite \u2014
    # ``<@!123>`` must become ``<@!\u200b123>``, not ``<@\u200b123>`` (the old
    # ``!?`` consumed the ``!`` and the replacement silently dropped it).
    text = re.sub(r"<@(!?)(?!\u200b)(\d+)>", "<@\\1\u200b\\2>", text)
    return text


def sanitize_message_content(content: str, max_length: int = 2000) -> str:
    """Sanitize message content for safe sending.

    Args:
        content: Raw message content
        max_length: Maximum allowed length

    Returns:
        Sanitized message content
    """
    # Handle None input
    if content is None:
        return ""

    content = escape_mentions(content)

    # Limit length (after sanitization to preserve escape sequences).
    # Walk back from the slice point to the last non-mark codepoint so a
    # Thai cluster (base + vowel/tone marks) doesn't get split
    # mid-character — slicing inside the cluster renders as a stray
    # combining mark on the ``...`` ellipsis. NOTE: the predicate is the
    # general category (Mn/Mc/Me), NOT ``unicodedata.combining()`` — the
    # most common Thai marks (MAI HAN-AKAT U+0E31, SARA I..UEE
    # U+0E34-0E37, MAITAIKHU U+0E47, THANTHAKHAT U+0E4C) are category Mn
    # with canonical combining class 0, so ``combining()`` returns 0 for
    # them and the rewind never fired (verified on this venv). Cap the
    # rewind so a degenerate input full of marks doesn't truncate to
    # nothing.
    if len(content) > max_length:
        # Clamp the slice point so a pathologically small max_length (< 3)
        # can't make ``cut`` go 0/negative — a negative ``cut`` would slice
        # from the END (content[:-1]) and yield output longer than max_length.
        cut = max(0, max_length - 3)
        if cut == 0:
            # Degenerate max_length: nothing fits before the ellipsis.
            return "..."
        rewind_limit = max(0, cut - 16)
        while cut > rewind_limit and unicodedata.category(content[cut]) in ("Mn", "Mc", "Me"):
            cut -= 1
        content = content[:cut] + "..."
    return content


# ---------------------------------------------------------------------------
# Long-term-memory write screening (shared sink for ALL ``remember`` writers)
# ---------------------------------------------------------------------------
# Historically the prompt-injection screen for ``remember`` lived inline in
# ``tools/tool_executor.execute_tool_call`` and was DUPLICATED in
# ``commands/memory_commands._screen_injection``. On the live ``cli`` backend the
# model's ``remember`` tool call flows through ``api/ai_tools_ipc._dispatch_memory``
# (NOT execute_tool_call), so the executor's copy never ran on the primary path —
# letting an injected ``[SYSTEM] ignore previous …`` payload persist verbatim into
# RAG-retrievable context (audit py-aicore-tools-1). This module is now the single
# authoritative screen: every writer (executor, IPC, ``!remember``) must funnel
# content through :func:`screen_memory_content` BEFORE it reaches ``add_explicit_fact``
# / ``rag_system.add_memory``. Do NOT weaken the denylists — only add to them.

# Minimum plausible length for a stored fact — the model occasionally tries to
# "remember" a single word, polluting RAG with noise.
_MEMORY_MIN_LENGTH = 8
# Hard cap on stored memory content to prevent unbounded DB/cache growth and
# context-token inflation on recall (audit py-aicore-tools-M1). The executor used
# 5000 chars; keep that as the shared cap so every writer is bounded.
_MEMORY_MAX_LENGTH = 5000

# Plain markers checked against the raw lowercased text.
_MEMORY_SUSPICIOUS_MARKERS = (
    "[system]",
    "[inst]",
    "ignore previous",
    "ignore the previous",
    "<system>",
    "<inst>",
    "</system>",
    "</inst>",
)
# Cyrillic/Greek/full-width/math confusables -> plain ASCII, so visually-identical
# spellings (e.g. "иgnore previous", "𝗶gnore previous", "ｉgnore previous") can't
# slip past the normalised screen. Without the de-confuse step a Cyrillic 'и'
# would be ASCII-stripped by NFKD, leaving "gnore previous" which evades the
# "ignore previous" marker while still reading as the original to a downstream LM.
_MEMORY_CONFUSABLE_MAP = {
    # Dotless Latin letters — the OPPOSITE failure mode from the script
    # confusables below. NFKD has no decomposition for these, so the ASCII fold
    # DELETES them instead of folding: "ıgnore previous" arrived at the denylist
    # as "gnore previous" and matched nothing (audit: confirmed reaching
    # storage). Map them so the letter survives as its dotted ASCII twin. Only
    # the lowercase forms need entries — uppercase İ (U+0130) DOES decompose
    # (I + combining dot above), so NFKD already folds it to "I".
    "ı": "i",  # U+0131 dotless i — Latin 'i' minus the tittle
    "ȷ": "j",  # U+0237 dotless j — 'j' appears in "jailbreak"
    # Cyrillic lowercase -> Latin lowercase
    "а": "a",
    "в": "b",
    "с": "c",
    "д": "d",
    "е": "e",
    "х": "x",
    "и": "i",
    # U+0456 Cyrillic dotted i — pixel-identical to Latin 'i' (unlike U+0438 'и'
    # above), so "іgnore previous" must map through to "ignore previous".
    "і": "i",
    "ј": "j",
    "к": "k",
    "ӏ": "l",
    "о": "o",
    "р": "p",
    "ѕ": "s",
    "т": "t",
    "у": "y",
    "һ": "h",
    # Cyrillic uppercase -> Latin uppercase
    "А": "A",
    "В": "B",
    "С": "C",
    "Е": "E",
    "Н": "H",
    "К": "K",
    "М": "M",
    "О": "O",
    "Р": "P",
    "Т": "T",
    "Х": "X",
    "Ј": "J",
    "І": "I",  # U+0406 Cyrillic capital dotted I — homoglyph of Latin 'I'
    # Greek lowercase -> Latin lowercase
    "α": "a",
    "ο": "o",
    "ρ": "p",
    "υ": "y",
    "ι": "i",  # U+03B9 Greek small iota — homoglyph of Latin 'i'
    # Greek uppercase -> Latin uppercase
    "Α": "A",
    "Β": "B",
    "Ε": "E",
    "Ζ": "Z",
    "Η": "H",
    "Ι": "I",
    "Κ": "K",
    "Μ": "M",
    "Ν": "N",
    "Ο": "O",
    "Ρ": "P",
    "Τ": "T",
    "Υ": "Y",
    "Χ": "X",
    # Mathematical Alphanumeric Symbols (U+1D400+ bold ASCII Latin)
    "𝐚": "a",
    "𝐛": "b",
    "𝐜": "c",
    "𝐝": "d",
    "𝐞": "e",
    "𝐟": "f",
    "𝐠": "g",
    "𝐡": "h",
    "𝐢": "i",
    "𝐣": "j",
    "𝐤": "k",
    "𝐥": "l",
    "𝐦": "m",
    "𝐧": "n",
    "𝐨": "o",
    "𝐩": "p",
    "𝐪": "q",
    "𝐫": "r",
    "𝐬": "s",
    "𝐭": "t",
    "𝐮": "u",
    "𝐯": "v",
    "𝐰": "w",
    "𝐱": "x",
    "𝐲": "y",
    "𝐳": "z",
    # Full-width ASCII (U+FF21-U+FF5A)
    "ａ": "a",
    "ｂ": "b",
    "ｃ": "c",
    "ｄ": "d",
    "ｅ": "e",
    "ｆ": "f",
    "ｇ": "g",
    "ｈ": "h",
    "ｉ": "i",
    "ｊ": "j",
    "ｋ": "k",
    "ｌ": "l",
    "ｍ": "m",
    "ｎ": "n",
    "ｏ": "o",
    "ｐ": "p",
    "ｑ": "q",
    "ｒ": "r",
    "ｓ": "s",
    "ｔ": "t",
    "ｕ": "u",
    "ｖ": "v",
    "ｗ": "w",
    "ｘ": "x",
    "ｙ": "y",
    "ｚ": "z",
    "Ａ": "A",
    "Ｅ": "E",
    "Ｉ": "I",
    "Ｏ": "O",
    "Ｕ": "U",
}
# Broader forbidden set checked against the de-confused + NFKD-decomposed form.
# Includes the bracket/tag markers too, so a confusable spelling (e.g. ``<ѕystem>``)
# that slips past the plain pass is still caught here.
_MEMORY_FORBIDDEN_NORMALIZED = (
    "[system]",
    "[inst]",
    "<system>",
    "</system>",
    "<inst>",
    "</inst>",
    "ignore previous",
    "ignore the previous",
    "pretend",
    "you are now",
    "system:",
    "override",
    "jailbreak",
    # Two-token spelling of the "jailbreak" needle. A bare single word can't go
    # in the despaced pass (see below), but the SPACED form can — and it is the
    # spelling that actually evaded the screen ("Jail break the model now"
    # reached storage). Adding it here makes the separator-folded pass catch
    # "jail-break"/"jail.break" too, and the despaced pass catch "jailbreak"
    # written with any run of whitespace/control chars between the halves.
    "jail break",
    "disregard",
)

# THIS repo's own prompt-structure markers. The list above is the generic
# LLM-injection denylist; these are the boundaries our own prompt builders emit,
# and a stored memory is re-injected INSIDE them — the ``[Long-term Memory]``
# block sits in ``prompt_with_context`` ahead of the real
# ``---END SYSTEM CONTEXT---``, and on the CLI path the whole thing is flattened
# into one text prompt whose sections are exactly these headings. So a fact
# carrying one of them can close the system-context section early, open a forged
# ``[System Info] … | User: <someone else>`` header, or restate the identity
# directive — inside a store that is replayed into every future turn rather than
# just the one message its author sent.
#
# Live until 2026-08-28 only by accident: nothing on the Discord reply path read
# the explicit-fact store, so the screen guarded a dead path. Wiring
# ``!remember`` into the prompt is what made these load-bearing.
#
# Checked as plain lowercased substrings (the same pass
# ``_MEMORY_SUSPICIOUS_MARKERS`` uses) rather than through the confusable /
# despaced folds: these are long, punctuation-heavy literals with no benign
# reading in a personal fact, and folding separators out of them would start
# matching ordinary prose. The ``#`` headings are matched WITH their leading
# hash so a sentence that merely contains the words ("the system context of
# this") is untouched.
_PROMPT_STRUCTURE_MARKERS = (
    "---end system context---",
    "[system info]",
    "# primary directive",
    "# context & format rules",
    "# conversation history",
    "# current user message",
    "# available tools",
    "# formatting rules",
    "# your recent messages",
)

# Leet/symbol substitutions folded into ONE extra normalised form. Purely
# additive: the folded string is checked against the SAME needles, so it can
# only ever add a detection. Motivation: "0v3rr1d3 the rules" cleared every
# other pass (verified by probe) because none of them touch digit-for-letter
# spellings. Deliberately narrow — only the substitutions that actually spell
# out the needles above — so ordinary text carrying digits ("user is 25",
# "earns $500") cannot fold into one of them.
_MEMORY_LEET_MAP = {
    "0": "o",
    "1": "i",
    "3": "e",
    "4": "a",
    "5": "s",
    "7": "t",
    "@": "a",
    "$": "s",
}

# A denylist that recognises only ONE spelling of the gap between two words is
# trivially evaded: "ignore\nprevious", "ignore\tprevious", "ignore  previous"
# and "ignore.previous" all read as the original instruction to a downstream LM,
# yet none of them contain the literal "ignore previous" the set above checks
# for (all four were confirmed to reach storage). Two extra normalisations close
# that, applied on top of the de-confused/NFKD form:
#
#   * separator-folded — every run of non-alphanumeric characters collapses to a
#     single space, so any separator spelling folds onto the canonical one.
#   * whitespace-stripped — ALL whitespace AND ASCII control characters removed,
#     matched against the forbidden phrases with their spaces likewise removed,
#     which additionally catches letter-spaced payloads
#     ("i g n o r e   p r e v i o u s").
#
# The whitespace-stripped pass is deliberately restricted to the MULTI-TOKEN,
# bracketed and COLON-bearing entries. Running it over the bare single words
# would manufacture matches out of adjacent ones — "handed over ride quality"
# strips to "…overridequality", which contains "override" — so those keep to the
# passes that preserve word boundaries.
#
# ``system:`` earns its place in that set because the colon is itself a strong
# boundary marker, not an accident of adjacency. Without it that needle was
# reachable ONLY by the exact pass: the separator-folded pass erases the colon
# (so the needle can never match there) and the despaced filter excluded it for
# want of a space/bracket — leaving "SYSTEM : do this" to sail through every
# pass and reach storage (verified by probe). Including it adds no new
# false-positive CLASS: any text the despaced pass now catches ("subsystem: x")
# already matched the exact pass in its unspaced spelling.
_MEMORY_SEPARATOR_RUN = re.compile(r"[^a-z0-9]+")
# Stripped for the whitespace-stripped pass: real whitespace plus the C0/DEL
# control range. ``str.split()`` alone removed only whitespace, so a control
# character kept the word boundary this pass exists to erase —
# "ig\x00nore previous" survived every pass and reached storage. The non-ASCII
# zero-width spellings (ZWSP, ZWNJ, …) are already dropped by the NFKD + ASCII
# fold above, which is why only the ASCII controls need naming here. Brackets
# and angle brackets must SURVIVE this strip: the despaced needles keep theirs
# ("[system]", "<inst>").
_MEMORY_INVISIBLE_RUN = re.compile(r"[\s\x00-\x1f\x7f]+")
_MEMORY_FORBIDDEN_DESPACED = tuple(
    f.replace(" ", "")
    for f in _MEMORY_FORBIDDEN_NORMALIZED
    if " " in f or "[" in f or "<" in f or ":" in f
)


def memory_content_has_injection(content: str) -> bool:
    """Return True if ``content`` carries a prompt-injection marker.

    Plain lowercased pass for the suspicious markers, then a de-confused +
    NFKD-decomposed + ASCII pass for the broader forbidden set so confusable
    spellings can't evade detection, then the two separator-insensitive passes
    described above, and finally the same three passes over a leet-folded copy.
    Pure predicate (no clamping/attribution) so callers that only need the
    boolean (e.g. the ``!remember`` command) can reuse the SAME denylists as the
    AI-tool/IPC sinks.
    """
    lowered = content.lower()
    if any(marker in lowered for marker in _MEMORY_SUSPICIOUS_MARKERS):
        return True
    # Our own prompt boundaries — see _PROMPT_STRUCTURE_MARKERS for why a stored
    # memory carrying one is a different (and longer-lived) problem than the
    # same text in a single chat message.
    if any(marker in lowered for marker in _PROMPT_STRUCTURE_MARKERS):
        return True
    de_confused = "".join(_MEMORY_CONFUSABLE_MAP.get(c, c) for c in content)
    normalized = (
        unicodedata.normalize("NFKD", de_confused).encode("ascii", "ignore").decode("ascii").lower()
    )
    # Leet-folded twin of ``normalized`` (see _MEMORY_LEET_MAP). Checked through
    # the SAME three passes below so a digit-substituted spelling can't dodge
    # one pass by hiding in another; identical to ``normalized`` for text with
    # no leet characters, in which case the extra checks are pure no-ops.
    leet = "".join(_MEMORY_LEET_MAP.get(c, c) for c in normalized)
    forms = (normalized,) if leet == normalized else (normalized, leet)

    if any(f in form for form in forms for f in _MEMORY_FORBIDDEN_NORMALIZED):
        return True
    # Separator-folded pass — catches "ignore.previous", "ignore\nprevious",
    # "ignore__previous", "ignore  previous". The bracketed entries can't match
    # here (their brackets fold away too); the exact pass above owns those.
    if any(
        f in _MEMORY_SEPARATOR_RUN.sub(" ", form)
        for form in forms
        for f in _MEMORY_FORBIDDEN_NORMALIZED
    ):
        return True
    # Whitespace-stripped pass — catches letter-spaced payloads, split tags
    # ("[ system ]", "<sys tem>"), control-character-separated spellings
    # ("ig\x00nore previous"), and spaced-out colon markers ("SYSTEM : do
    # this"). Multi-token / bracketed / colon-bearing entries only.
    return any(
        f in _MEMORY_INVISIBLE_RUN.sub("", form)
        for form in forms
        for f in _MEMORY_FORBIDDEN_DESPACED
    )


def screen_memory_content(content: object) -> tuple[bool, str]:
    """Authoritative screen for a ``remember`` write, shared by every sink.

    Applies, in order: type check, ``strip``, min-length, the plain+normalised
    prompt-injection denylists, and the 5000-char clamp (with a ``[truncated]``
    marker). Attribution is intentionally NOT added here — it is path-specific
    (the executor prefixes ``[user … (id=…)]`` for the shared per-channel RAG
    store, while the IPC path records ``user_id`` as a structured column), so
    baking it in would change the IPC storage format. Callers add attribution
    themselves AFTER this returns.

    Args:
        content: Raw model/user-supplied memory content (any type — validated).

    Returns:
        ``(False, reason)`` when the write must be rejected (reason is a short
        human-readable string suitable to surface to the model/user), or
        ``(True, screened)`` where ``screened`` is the stripped, denylist-cleared,
        length-clamped content ready to persist.
    """
    if not isinstance(content, str):
        return False, "Content must be a string"
    content = content.strip()
    if len(content) < _MEMORY_MIN_LENGTH:
        return False, "Content is too short"
    if memory_content_has_injection(content):
        return False, "Content contains restricted markers"
    if len(content) > _MEMORY_MAX_LENGTH:
        content = content[:_MEMORY_MAX_LENGTH] + " [truncated]"
    return True, content


__all__ = [
    "SYSTEM_MARKER_RE",
    "escape_mentions",
    "memory_content_has_injection",
    "sanitize_channel_name",
    "sanitize_message_content",
    "sanitize_role_name",
    "screen_memory_content",
]
