"""Mint a Google master token for gkeepapi (one-time, local).

Keep has no consumer OAuth API. gkeepapi needs a Google master token obtained
via gpsoauth's EmbeddedSetup cookie exchange. That token can act as the whole
Google account — store it in the container env, never in git.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys

import gpsoauth

_SETUP_URL = "https://accounts.google.com/EmbeddedSetup"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Exchange an EmbeddedSetup oauth_token cookie for a Keep master token."
    )
    parser.add_argument("--email", help="Google account email")
    parser.add_argument(
        "--oauth-token",
        help="Value of the oauth_token cookie from EmbeddedSetup (not your password)",
    )
    parser.add_argument(
        "--android-id",
        help="Stable 16-char hex android id (generated if omitted)",
    )
    args = parser.parse_args()

    print(
        "Google Keep has no personal OAuth API. This mints a master token via\n"
        "gpsoauth (unofficial). The token can access the whole Google account.\n",
        file=sys.stderr,
    )
    print(f"1. Open { _SETUP_URL } in a browser and sign in.", file=sys.stderr)
    print('2. Click "I agree" if asked. The page may spin forever — that is ok.', file=sys.stderr)
    print(
        "3. DevTools → Application → Cookies → accounts.google.com → copy oauth_token.\n",
        file=sys.stderr,
    )

    email = (args.email or input("Google email: ")).strip()
    oauth_token = (args.oauth_token or input("oauth_token cookie: ")).strip()
    android_id = (args.android_id or secrets.token_hex(8)).strip()
    if not email or not oauth_token:
        print("email and oauth_token are required.", file=sys.stderr)
        sys.exit(1)

    response = gpsoauth.exchange_token(email, oauth_token, android_id)
    master = response.get("Token") if isinstance(response, dict) else None
    if not master:
        print("Token exchange failed. Full response:", file=sys.stderr)
        print(json.dumps(response, indent=2), file=sys.stderr)
        sys.exit(1)

    print("\nSet these on the keep-mcp container (do not commit them):\n")
    print(f"GOOGLE_EMAIL={email}")
    print(f"GOOGLE_MASTER_TOKEN={master}")
    print(f"# optional, keep this android id if you re-mint: GOOGLE_ANDROID_ID={android_id}")


if __name__ == "__main__":
    main()
