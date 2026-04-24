"""Check API proxy balance / usage."""

import os
import sys
from datetime import datetime

import httpx
from dotenv import load_dotenv

load_dotenv()

base = os.getenv("ANTHROPIC_BASE_URL")
key = os.getenv("ANTHROPIC_API_KEY")

if not base or not key:
    print("ERROR: ANTHROPIC_BASE_URL or ANTHROPIC_API_KEY not set in .env")
    sys.exit(1)

headers = {"Authorization": f"Bearer {key}"}
first_of_month = datetime.now().strftime("%Y-%m-01")

try:
    sub = httpx.get(f"{base}/v1/dashboard/billing/subscription", headers=headers, timeout=10).json()
    usage = httpx.get(f"{base}/v1/dashboard/billing/usage", headers=headers, params={"date": first_of_month}, timeout=10).json()

    limit = sub.get("hard_limit_usd", 0)
    used = usage.get("total_usage", 0) / 100
    balance = limit - used

    print("=" * 40)
    print(f"  Quota:   ${limit:.2f}")
    print(f"  Used:    ${used:.2f}")
    print(f"  Balance: ${balance:.2f}")
    print("=" * 40)
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)
