"""Deprecated: CMS has moved to static frontend + Cloudflare Worker backend.

Use `cms/index.html` with a static server (for example VS Code Live Server)
and the Worker CMS endpoints instead of this local Flask app.
"""

if __name__ == "__main__":
    raise SystemExit(
        "Deprecated. Use cms/index.html + Worker CMS API. See README.md for setup."
    )
