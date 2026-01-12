#!/usr/bin/env python3
"""Cloudflare tunnel for tldw backend with GitHub Gist auto-update."""

import json
import os
import signal
import sys
import time
from datetime import datetime
from urllib import request

def update_gist(tunnel_url: str) -> bool:
    """Update GitHub Gist with tunnel URL."""
    github_token = os.environ.get('GITHUB_TOKEN')
    gist_id = os.environ.get('GIST_ID')

    if not github_token or not gist_id:
        print("Warning: GITHUB_TOKEN or GIST_ID not set, skipping gist update")
        return False

    data = {
        "files": {
            "tunnel.json": {
                "content": json.dumps({
                    "url": tunnel_url,
                    "updated": datetime.utcnow().isoformat() + "Z"
                })
            }
        }
    }

    try:
        req = request.Request(
            f"https://api.github.com/gists/{gist_id}",
            data=json.dumps(data).encode('utf-8'),
            headers={
                "Authorization": f"token {github_token}",
                "Content-Type": "application/json",
                "Accept": "application/vnd.github.v3+json"
            },
            method="PATCH"
        )
        with request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                print(f"Gist updated successfully")
                return True
    except Exception as e:
        print(f"Failed to update gist: {e}")
    return False

def main():
    port = int(os.environ.get('PORT', 5123))

    print(f"Starting tunnel for port {port}...")

    try:
        from pycloudflared import try_cloudflare
        tunnel = try_cloudflare(port=port)
        tunnel_url = tunnel.tunnel
    except Exception as e:
        print(f"Tunnel error: {e}", file=sys.stderr)
        sys.exit(1)

    # Update Gist with tunnel URL
    update_gist(tunnel_url)

    print("")
    print("=" * 50)
    print("  tldw service started!")
    print("=" * 50)
    print(f"")
    print(f"  Public URL:  {tunnel_url}")
    print(f"  Local URL:   http://localhost:{port}")
    print(f"")
    print(f"  Frontend will auto-detect this URL.")
    print(f"  Or open: https://ytquickbite.vercel.app/")
    print("")
    print("Press Ctrl+C to stop")

    def cleanup(sig, frame):
        print("\nShutting down tunnel...")
        tunnel.process.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    # Keep running
    while True:
        time.sleep(1)

if __name__ == "__main__":
    main()
