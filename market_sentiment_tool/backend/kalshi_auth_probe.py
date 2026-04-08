from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.kalshi_ws import load_rsa_private_key, sign_kalshi_message


def _build_headers(api_key_id: str, pem_path: Path, request_path: str) -> dict[str, str]:
    private_key = load_rsa_private_key(str(pem_path))
    ts = str(int(time.time() * 1000))
    msg = f"{ts}GET{request_path}"
    signature = sign_kalshi_message(private_key=private_key, message=msg.encode("utf-8"))
    return {
        "KALSHI-ACCESS-KEY": api_key_id,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("utf-8"),
        "KALSHI-ACCESS-TIMESTAMP": ts,
    }


def probe_key(api_key_id: str, pem_path: Path, base_url: str) -> tuple[int | None, str]:
    request_path = "/portfolio/balance"
    url = f"{base_url.rstrip('/')}{request_path}"
    try:
        headers = _build_headers(api_key_id, pem_path, request_path)
    except Exception as exc:
        return None, f"key-load-error: {exc}"

    try:
        response = requests.get(url, headers=headers, timeout=15)
    except Exception as exc:
        return None, f"http-error: {exc}"

    try:
        body = response.json()
        preview = json.dumps(body)[:300]
    except Exception:
        preview = response.text[:300]
    return response.status_code, preview


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Kalshi API key/PEM combinations against an authenticated endpoint.")
    parser.add_argument("--api-key-id", required=True, help="Kalshi API key id to test.")
    parser.add_argument(
        "--base-url",
        default="https://demo-api.kalshi.co/trade-api/v2",
        help="Kalshi trade API base URL, e.g. https://demo-api.kalshi.co/trade-api/v2",
    )
    parser.add_argument("pem_files", nargs="+", help="One or more private key PEM files to test.")
    args = parser.parse_args()

    overall_success = False
    print(f"Testing API key id against {len(args.pem_files)} PEM file(s) via {args.base_url}/portfolio/balance")
    for raw_path in args.pem_files:
        pem_path = Path(raw_path).expanduser().resolve()
        status, detail = probe_key(args.api_key_id, pem_path, args.base_url)
        label = pem_path.name
        if status == 200:
            overall_success = True
            print(f"[OK]     {label}: HTTP 200 {detail}")
        elif status is None:
            print(f"[ERROR]  {label}: {detail}")
        else:
            print(f"[FAIL]   {label}: HTTP {status} {detail}")

    return 0 if overall_success else 1


if __name__ == "__main__":
    raise SystemExit(main())
