"""Capture Yahoo OAuth token for headless deployment.

Run locally to authenticate with Yahoo, then outputs the token JSON
to set as a Fly.io secret for headless server use.

Usage:
    uv run python -m scripts.capture_yahoo_token
"""
import json

from yahoo_oauth import OAuth2


def main():
    from app.config import settings

    print("Starting Yahoo OAuth flow — a browser window will open.")
    print("Authorize the app, then paste the verifier code when prompted.\n")

    oauth = OAuth2(
        settings.yahoo_client_id,
        settings.yahoo_client_secret,
        browser_callback=True,
        store_file=False,
    )

    token_data = {
        "access_token": oauth.access_token,
        "consumer_key": oauth.consumer_key,
        "consumer_secret": oauth.consumer_secret,
        "guid": getattr(oauth, "guid", ""),
        "refresh_token": oauth.refresh_token,
        "token_time": oauth.token_time,
        "token_type": oauth.token_type,
    }

    token_json = json.dumps(token_data)

    print("\n✓ Yahoo OAuth successful!\n")
    print("Run this command to set the token on Fly.io:\n")
    print(f'flyctl secrets set YAHOO_ACCESS_TOKEN_JSON=\'{token_json}\'')
    print()

    # Also save locally for reference
    with open("yahoo_token.json", "w") as f:
        json.dump(token_data, f, indent=2)
    print("Token also saved to yahoo_token.json (do not commit this file)")


if __name__ == "__main__":
    main()
