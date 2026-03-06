import json
import os
import re
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

# -----------------------------------------------------------------------------
# Flask app
# -----------------------------------------------------------------------------
app = Flask(__name__)

# Vercel runs this file as a serverless function.
# We'll serve the SPA (index.html) + static assets from ../public relative to /api/index.py
BASE_DIR = Path(__file__).resolve().parent.parent   # .../api/.. = project root (within Root Directory)
PUBLIC_DIR = BASE_DIR / "public"

CONFIG_PATH = BASE_DIR / "config.json"
CONFIG_EXAMPLE_PATH = BASE_DIR / "config.example.json"


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def _provider_npi_map_from_env() -> dict:
    """
    Supports multiple providers via env vars like:
      PROVIDER_NPI_Truumees=123...
      PROVIDER_NPI_Rory=456...
      PROVIDER_NPI_Moroz=789...

    Keys are matched case-insensitively by slug (letters/numbers/underscore).
    """
    out = {}
    prefix = "PROVIDER_NPI_"
    for k, v in os.environ.items():
        if not k.startswith(prefix):
            continue
        slug = _slugify(k[len(prefix):])
        if slug and v:
            out[slug] = v
    return out


def _resolve_provider_npi(provider_name: str | None) -> tuple[str, str | None]:
    """
    Returns (npi, matched_slug).

    Priority:
      1) PROVIDER_NPI (single-provider legacy)
      2) PROVIDER_NPI_<slug> matching provider_name (or PROVIDER_NAME)
      3) If exactly one PROVIDER_NPI_<slug> exists, use it
      4) else empty
    """
    # 1) legacy single value
    if os.environ.get("PROVIDER_NPI"):
        return os.environ.get("PROVIDER_NPI", ""), None

    provider_map = _provider_npi_map_from_env()

    requested = provider_name or os.environ.get("PROVIDER_NAME") or ""
    req_slug = _slugify(requested)

    # 2) match by slugified provider name
    if req_slug and req_slug in provider_map:
        return provider_map[req_slug], req_slug

    # allow passing the env suffix directly (already slugged)
    if requested and requested.strip().lower() in provider_map:
        slug = requested.strip().lower()
        return provider_map[slug], slug

    # 3) if only one provider configured, default to it
    if len(provider_map) == 1:
        only_slug, only_npi = next(iter(provider_map.items()))
        return only_npi, only_slug

    return "", None


def _get_selected_provider_name() -> str:
    """
    Allow selecting provider per request.
    Frontend can pass:
      ?provider_name=Truumees
      ?provider=Truumees
      header: X-Provider-Name: Truumees
    """
    return (
        request.args.get("provider_name")
        or request.args.get("provider")
        or request.headers.get("X-Provider-Name")
        or os.environ.get("PROVIDER_NAME", "")
    )


def load_config() -> dict:
    """
    Config load order:
      1) Vercel env vars (preferred)
      2) config.json (local dev)
      3) config.example.json (fallback)
    """
    config = {
        "practice_name": "",
        "provider_name": "",
        "npi": "",
        "ai_mode": True,
        "demo_mode": True,
        "storage": "env",  # env | file
        "providers": {},   # optional: map slug -> npi
    }

    # Env config
    config["practice_name"] = os.environ.get("PRACTICE_NAME", "")
    config["provider_name"] = os.environ.get("PROVIDER_NAME", "")
    config["ai_mode"] = str(os.environ.get("AI_MODE", "true")).strip().lower() in ("1", "true", "yes", "y")
    config["demo_mode"] = str(os.environ.get("DEMO_MODE", "true")).strip().lower() in ("1", "true", "yes", "y")

    # Multi-provider support
    provider_map = _provider_npi_map_from_env()
    if provider_map:
        config["providers"] = provider_map

    selected_provider = _get_selected_provider_name()
    npi, _matched_slug = _resolve_provider_npi(selected_provider)

    config["provider_name"] = selected_provider or config["provider_name"]
    config["npi"] = npi

    # If any env config is present, treat as env-based
    if (
        os.environ.get("PRACTICE_NAME")
        or os.environ.get("PROVIDER_NAME")
        or os.environ.get("PROVIDER_NPI")
        or provider_map
    ):
        config["storage"] = "env"
        return config  # <-- IMPORTANT: return inside the function

    # Local dev fallback (file-based)
    config["storage"] = "file"
    for path in (CONFIG_PATH, CONFIG_EXAMPLE_PATH):
        if path.exists():
            try:
                file_cfg = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(file_cfg, dict):
                    config.update(file_cfg)
            except Exception:
                pass

    return config


# -----------------------------------------------------------------------------
# API endpoints
# -----------------------------------------------------------------------------
@app.get("/status")
def status():
    cfg = load_config()
    providers = sorted((cfg.get("providers") or {}).keys())
    return jsonify(
        {
            "ai_mode": cfg.get("ai_mode", True),
            "demo_mode": cfg.get("demo_mode", True),
            "practice_name": cfg.get("practice_name", ""),
            "provider_name": cfg.get("provider_name", ""),
            "npi": cfg.get("npi", ""),
            "provider_keys": providers,
            "storage": cfg.get("storage", "env"),
        }
    )


# -----------------------------------------------------------------------------
# SPA + static
# -----------------------------------------------------------------------------
def _send_public(path: str):
    # Basic traversal protection
    safe = os.path.normpath(path).lstrip(os.sep).replace("..", "")
    full = PUBLIC_DIR / safe
    if not full.exists():
        return None
    return send_from_directory(PUBLIC_DIR, safe)


@app.get("/")
def index():
    if (PUBLIC_DIR / "index.html").exists():
        return send_from_directory(PUBLIC_DIR, "index.html")
    return (
        "Missing public/index.html. Ensure it exists under the Vercel Root Directory.",
        500,
    )


@app.get("/<path:path>")
def spa_route(path: str):
    resp = _send_public(path)
    if resp is not None:
        return resp
    return index()


# -----------------------------------------------------------------------------
# Compatibility routes: if Vercel rewrites/proxies to /api/index
# -----------------------------------------------------------------------------
@app.get("/api/index")
@app.get("/api/index/<path:subpath>")
def api_index_alias(subpath: str | None = None):
    """
    If your Vercel config rewrites '/' -> '/api/index', Flask would see '/api/index'
    and 404 unless we alias it.
    """
    if not subpath:
        return index()
    return spa_route(subpath)


# -----------------------------------------------------------------------------
# Entry point for local dev
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), debug=True)