"""Check API proxy balance / usage."""

import os
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

load_dotenv()

base = os.getenv("ANTHROPIC_BASE_URL")
key = os.getenv("ANTHROPIC_API_KEY")

if not base or not key:
    print("ERROR: ANTHROPIC_BASE_URL or ANTHROPIC_API_KEY not set in .env")
    sys.exit(1)

# Validate that the base URL points to a known-good host before attaching the
# bearer token. A poisoned ANTHROPIC_BASE_URL would otherwise exfiltrate the
# API key to whatever host the env var names. The allowlist mirrors the
# host-validation pattern used elsewhere in the codebase.
_parsed = urlparse(base)
if _parsed.scheme != "https":
    print(f"ERROR: ANTHROPIC_BASE_URL must use https:// (got {_parsed.scheme!r})")
    sys.exit(1)
_host = (_parsed.hostname or "").lower()
# Entries that START with ``.`` are SUBDOMAIN suffixes (matched by
# ``endswith``); entries that DO NOT start with ``.`` are EXACT-host
# matches (the ``lstrip`` on a no-dot entry is a no-op, so the equality
# check is what fires for them). This means an entry like ``anthropic.com``
# would accept BOTH ``anthropic.com`` exactly AND any host ending in
# ``anthropic.com`` (e.g. ``evil-anthropic.com``) — exactly the bypass
# we want to avoid. Keep the dot-prefix convention strict for new
# entries: SaaS proxies → both bare host AND ``.host`` pair; the bare
# entry handles the apex domain only.
_ALLOWED_HOST_SUFFIXES = (
    "api.anthropic.com",
    ".anthropic.com",
    # Known proxy SaaS endpoints — extend here, never read from env.
    "openrouter.ai",
    ".openrouter.ai",
)


def _host_allowed(host: str) -> bool:
    """Strict host match.

    Entries beginning with ``.`` are subdomain suffixes (matched via
    ``endswith``); entries without a leading dot must match the host
    EXACTLY. The old single-line check used ``_host.endswith(s)`` on the
    bare entry too, which let ``evil-openrouter.ai`` slip through.
    """
    for entry in _ALLOWED_HOST_SUFFIXES:
        if entry.startswith("."):
            if host.endswith(entry):
                return True
        elif host == entry:
            return True
    return False


if not _host_allowed(_host):
    print(
        f"ERROR: ANTHROPIC_BASE_URL host {_host!r} is not in the allowlist; "
        f"refusing to send the bearer token there."
    )
    sys.exit(1)

headers = {"Authorization": f"Bearer {key}"}
# Use UTC to match the Anthropic billing API's day boundary; local
# timezone produced a date one day off near midnight depending on the
# proxy's clock. ``datetime.utcnow()`` is deprecated in 3.12+, so use
# the timezone-aware ``datetime.now(timezone.utc)`` form.
first_of_month = datetime.now(timezone.utc).strftime("%Y-%m-01")

try:
    sub_resp = httpx.get(
        f"{base}/v1/dashboard/billing/subscription", headers=headers, timeout=10
    )
    # ``raise_for_status`` first so a 4xx HTML error body doesn't blow
    # up downstream as an opaque ``JSONDecodeError`` — the original
    # status code carries the actionable info (401 = bad key, 403 =
    # not entitled, 404 = wrong endpoint, etc.).
    sub_resp.raise_for_status()
    sub = sub_resp.json()

    usage_resp = httpx.get(
        f"{base}/v1/dashboard/billing/usage",
        headers=headers,
        params={"date": first_of_month},
        timeout=10,
    )
    usage_resp.raise_for_status()
    usage = usage_resp.json()

    limit = sub.get("hard_limit_usd", 0)
    used = usage.get("total_usage", 0) / 100
    balance = limit - used

    print("=" * 40)
    print(f"  Quota:   ${limit:.2f}")
    print(f"  Used:    ${used:.2f}")
    print(f"  Balance: ${balance:.2f}")
    print("=" * 40)
except httpx.HTTPStatusError as e:
    # Surface the response body for debugging — the JSON error message
    # from Anthropic is far more useful than just the status code.
    # Append a ``... (truncated)`` marker when the body actually got cut
    # so a reader doesn't think they're seeing the full error.
    _body = e.response.text
    _shown = _body[:500] + ("... (truncated)" if len(_body) > 500 else "")
    print(f"ERROR: HTTP {e.response.status_code}: {_shown}")
    sys.exit(1)
except Exception as e:
    import traceback

    print(f"ERROR: {e}")
    traceback.print_exc()
    sys.exit(1)
