"""Check API proxy balance / usage."""

import os
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

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


def main() -> int:
    load_dotenv()

    # rstrip the trailing slash so f"{base}/v1/..." can't produce a double slash
    # (https://host//v1/...) that some proxies reject. A bare "/" collapses to ""
    # and is correctly rejected by the empty-check below.
    base = (os.getenv("ANTHROPIC_BASE_URL") or "").rstrip("/")
    key = os.getenv("ANTHROPIC_API_KEY")

    if not base or not key:
        print("ERROR: ANTHROPIC_BASE_URL or ANTHROPIC_API_KEY not set in .env")
        return 1

    # Validate that the base URL points to a known-good host before attaching the
    # bearer token. A poisoned ANTHROPIC_BASE_URL would otherwise exfiltrate the
    # API key to whatever host the env var names. The allowlist mirrors the
    # host-validation pattern used elsewhere in the codebase.
    parsed = urlparse(base)
    if parsed.scheme != "https":
        print(f"ERROR: ANTHROPIC_BASE_URL must use https:// (got {parsed.scheme!r})")
        return 1
    host = (parsed.hostname or "").lower()

    if not _host_allowed(host):
        print(
            f"ERROR: ANTHROPIC_BASE_URL host {host!r} is not in the allowlist; "
            f"refusing to send the bearer token there."
        )
        return 1

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

        # `or 0` (not just .get default) so an explicit JSON null is treated as 0 —
        # .get's default only applies when the key is absent, and None / 100 raises.
        limit = sub.get("hard_limit_usd") or 0
        used = (usage.get("total_usage") or 0) / 100
        balance = limit - used

        print("=" * 40)
        print(f"  Quota:   ${limit:.2f}")
        print(f"  Used:    ${used:.2f}")
        print(f"  Balance: ${balance:.2f}")
        print("=" * 40)
        return 0
    except httpx.HTTPStatusError as e:
        # Surface the response body for debugging — the JSON error message
        # from Anthropic is far more useful than just the status code.
        # Append a ``... (truncated)`` marker when the body actually got cut
        # so a reader doesn't think they're seeing the full error.
        body = e.response.text
        shown = body[:500] + ("... (truncated)" if len(body) > 500 else "")
        print(f"ERROR: HTTP {e.response.status_code}: {shown}")
        return 1
    except Exception as e:
        import traceback

        print(f"ERROR: {e}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
