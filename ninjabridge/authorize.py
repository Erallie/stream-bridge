from __future__ import annotations

import argparse
import http.server
import json
import os
import secrets
import threading
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

PROVIDERS = {
    "twitch": {
        "authorize": "https://id.twitch.tv/oauth2/authorize",
        "token": "https://id.twitch.tv/oauth2/token",
        "scope": "chat:read chat:edit",
        "prefix": "TWITCH",
    },
    "youtube": {
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "scope": "https://www.googleapis.com/auth/youtube.force-ssl",
        "prefix": "YOUTUBE",
    },
}


def exchange(url: str, form: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(url, data=urllib.parse.urlencode(form).encode(), headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def save_tokens(prefix: str, client_id: str, client_secret: str, body: dict[str, Any]) -> Path:
    path = Path("data") / f"{prefix.casefold()}-oauth.env"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"{prefix}_CLIENT_ID={client_id}",
        f"{prefix}_CLIENT_SECRET={client_secret}",
        f"{prefix}_REFRESH_TOKEN={body.get('refresh_token', '')}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Authorize NinjaBridge with a streaming platform")
    parser.add_argument("provider", choices=PROVIDERS)
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    provider = PROVIDERS[args.provider]
    prefix = provider["prefix"]
    client_id = os.getenv(f"{prefix}_CLIENT_ID", "")
    client_secret = os.getenv(f"{prefix}_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise SystemExit(f"Set {prefix}_CLIENT_ID and {prefix}_CLIENT_SECRET in .env first.")
    redirect_uri = f"http://localhost:{args.port}/callback"
    state = secrets.token_urlsafe(32)
    result: dict[str, str] = {}
    ready = threading.Event()

    class Callback(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if query.get("state", [""])[0] != state:
                self.send_response(400)
                message = b"Invalid OAuth state. You may close this tab."
            else:
                result["code"] = query.get("code", [""])[0]
                result["error"] = query.get("error", [""])[0]
                self.send_response(200)
                message = b"Authorization received. You may close this tab and return to the terminal."
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(message)))
            self.end_headers()
            self.wfile.write(message)
            ready.set()

        def log_message(self, format: str, *values: Any) -> None:
            return

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": provider["scope"],
        "state": state,
    }
    if args.provider == "youtube":
        params.update({"access_type": "offline", "prompt": "consent"})
    url = provider["authorize"] + "?" + urllib.parse.urlencode(params)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Callback)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Opening authorization page:\n{url}\n")
    webbrowser.open(url)
    ready.wait(300)
    server.shutdown()
    server.server_close()
    if result.get("error"):
        raise SystemExit(f"Authorization failed: {result['error']}")
    if not result.get("code"):
        raise SystemExit("No authorization response arrived within five minutes.")
    body = exchange(provider["token"], {"client_id": client_id, "client_secret": client_secret, "code": result["code"], "grant_type": "authorization_code", "redirect_uri": redirect_uri})
    if not body.get("refresh_token"):
        raise SystemExit(f"{args.provider.title()} did not return a refresh token. Revoke access and authorize again.")
    path = save_tokens(prefix, client_id, client_secret, body)
    print(f"Saved credentials to {path}. Copy those three lines into .env, then securely delete that temporary file.")


if __name__ == "__main__":
    main()
