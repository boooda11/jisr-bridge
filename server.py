#!/usr/bin/env python3
"""Jisr bridge MCP server — private, localhost only.

Tools (sandboxed under BASE_DIR):
  update_page(file_path, new_content)
  read_page(file_path)
  list_pages(subdir="")

Minimal OAuth 2.0 + Dynamic Client Registration (auto-approve, private bridge):
  /.well-known/oauth-protected-resource[/...]  -> resource metadata
  /.well-known/oauth-authorization-server[/...] -> AS metadata
  /register  (POST) -> DCR, accepts any client
  /authorize (GET)  -> auto-approves, 302 with code (+ PKCE support)
  /token     (POST) -> authorization_code / refresh_token exchange
"""

import base64
import hashlib
import os
import secrets
import subprocess
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

import uvicorn
import logging
log = logging.getLogger("jisr-oauth")
from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse, PlainTextResponse, RedirectResponse
from starlette.routing import Route

BASE_DIR = Path(os.environ.get("JISR_MCP_BASE", "/var/www/html")).resolve()
HOST = os.environ.get("JISR_MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("JISR_MCP_PORT", "8001"))

PUBLIC_MCP_URL = os.environ.get(
    "JISR_PUBLIC_MCP_URL",
    os.environ.get("JISR_PUBLIC_MCP_URL", "https://example.com/mcp"),
)
ISSUER = os.environ.get("JISR_OAUTH_ISSUER", "https://example.com/oauth")

mcp = FastMCP(
    "jisr-bridge",
    host=HOST,
    port=PORT,
    instructions=(
        "You are connected to the Waeyuk MAIN server through this jisr bridge. "
        "MANDATORY WORKFLOW for ANY real task on the main server: FIRST call "
        "waeyuk_start(task=...) or waeyuk_task(task=...). This opens a 10-stage chain "
        "(SPEC>CLARIFY>PLAN>TASKS>BUILD>TEST>SECURITY>QUALITY>REVIEW>DELIVER) built from "
        "the bundled agents/skills - follow it stage by stage via waeyuk_advance, never skip. "
        "WRITE tools (ss_writefile, jisr_agent, jisr_bg, ss_exec writes, ss_db_write, "
        "ss_git/ss_docker/ss_services/ss_nginx/ss_redis writes, ss_backup, net_api writes) "
        "REQUIRE the chain_id and REFUSE without it. "
        "Per stage: waeyuk_agents_list + waeyuk_skill_read to load the expert skill, "
        "chain_memory to persist facts, waeyuk_think for reasoning steps. "
        "READ tools (ss_readfile, ss_search, ss_db, ss_dbschema, ss_health, ss_ls, ss_logs, "
        "ss_php, net_fetch, net_ssl, util_time) are open for investigation."
    ),
)
try:
    from ss_tools import register_ss_tools
    register_ss_tools(mcp)
except Exception as _e:
    print("ss_tools not loaded:", _e)
try:
    from waeyuk_chain import register_chain_tools, chain_required, is_write_command, touch_chain
    register_chain_tools(mcp)
    _CHAIN_OK2 = True
except Exception as _e2:
    print("chain not loaded:", _e2)
    _CHAIN_OK2 = False
try:
    from waeyuk_plugins import register_plugin_tools
    register_plugin_tools(mcp)
    print("plugins loaded")
except Exception as _e3:
    print("plugins not loaded:", _e3)
try:
    from waeyuk_plugins2 import register_plugin2_tools
    register_plugin2_tools(mcp)
    print("plugins2 loaded")
except Exception as _e4:
    print("plugins2 not loaded:", _e4)


_codes = {}    # code -> {exp, challenge, method, client_id, redirect_uri}
_tokens = {}   # access_token -> exp
_clients = {}  # client_id -> secret


def _safe(path: str) -> Path:
    target = (BASE_DIR / path.lstrip("/")).resolve()
    if target != BASE_DIR and BASE_DIR not in target.parents:
        raise ValueError(f"path outside base dir: {path}")
    return target


@mcp.tool()
def update_page(file_path: str, new_content: str) -> str:
    """Create or overwrite a page file with new content.

    Args:
        file_path: path relative to the site root, e.g. "index.html" or "news/today.html"
        new_content: full new file content
    """
    target = _safe(file_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(new_content, encoding="utf-8")
    size = target.stat().st_size
    return f"OK: wrote {size} bytes to {target.relative_to(BASE_DIR)}"


@mcp.tool()
def read_page(file_path: str) -> str:
    """Read a page file. Args: file_path relative to site root."""
    target = _safe(file_path)
    if not target.is_file():
        return f"NOT FOUND: {file_path}"
    return target.read_text(encoding="utf-8")


@mcp.tool()
def list_pages(subdir: str = "") -> str:
    """List files under site root (or subdir)."""
    target = _safe(subdir)
    if not target.is_dir():
        return f"NOT A DIRECTORY: {subdir or '/'}"
    items = sorted(
        str(p.relative_to(BASE_DIR)) + ("/" if p.is_dir() else "")
        for p in target.iterdir()
    )
    return "\n".join(items) if items else "(empty)"


SS_SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
          "-i", os.environ.get("BRIDGE_SSH_KEY", "/root/.ssh/jisr_to_ssroot"), "root@" + os.environ.get("MAIN_SSH_HOST", "192.0.2.10")]


@mcp.tool()
def ss_exec(command: str, chain_id: str = "") -> str:
    """Run a shell command on the MAIN server (MAIN_SSH_HOST) and return output.

    Use it to inspect the main server: status, sites, docker, logs, files.
    Examples: "uptime; free -m; df -h /", "ls -la /var/www2", "docker ps --format '{{.Names}} {{.Status}}'".

    WRITE commands REQUIRE chain_id from waeyuk_start/waeyuk_task (10-stage chain).
    READ commands (uptime/ls/docker ps/logs) stay open.

    Args:
        command: shell command to run on ss-root
        chain_id: required for any write command
    """
    if _CHAIN_OK2:
        try:
            if is_write_command(command or ""):
                ok, msg = chain_required(chain_id or "")
                if not ok:
                    return msg
                try:
                    touch_chain(chain_id)
                except Exception:
                    pass
        except Exception:
            pass
    try:
        r = subprocess.run(SS_SSH + [command], capture_output=True,
                           text=True, timeout=60)
        out = r.stdout or ""
        if r.stderr:
            out += ("\n" if out else "") + "[stderr]\n" + r.stderr
        out += f"\n[exit={r.returncode}]"
        if len(out) > 20000:
            out = out[:20000] + "\n...[truncated]..."
        return out or "(empty output)"
    except subprocess.TimeoutExpired:
        return "TIMEOUT after 60s"
    except Exception as e:
        return f"ERROR: {e}"


# ---------------- OAuth / DCR ----------------

def _prm(request):
    log.warning("PRM hit ua=%s", request.headers.get("user-agent"))
    return JSONResponse({
        "resource": PUBLIC_MCP_URL,
        "authorization_servers": [ISSUER],
        "bearer_methods_supported": ["header"],
        "scopes_supported": ["read", "write"]
    })


def _asm(request):
    log.warning("ASM hit ua=%s path=%s", request.headers.get("user-agent"), request.url.path)
    return JSONResponse({
        "issuer": ISSUER,
        "authorization_endpoint": ISSUER + "/authorize",
        "token_endpoint": ISSUER + "/token",
        "registration_endpoint": ISSUER + "/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": [
            "none", "client_secret_post", "client_secret_basic",
        ],
        "code_challenge_methods_supported": ["S256", "plain"],
        "scopes_supported": ["read", "write"]
    })


async def _register(request):
    log.warning("REGISTER hit ua=%s path=%s", request.headers.get("user-agent"), request.url.path)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    cid = body.get("client_id") or "chatgpt-" + secrets.token_hex(4)
    sec = secrets.token_urlsafe(24)
    _clients[cid] = sec
    return JSONResponse({
        "client_id": cid,
        "client_secret": sec,
        "client_id_issued_at": int(time.time()),
        "client_secret_expires_at": 0,
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
    })


async def _authorize(request):
    q = request.query_params
    log.warning("AUTHORIZE hit ua=%s path=%s", request.headers.get("user-agent"), request.url.path)
    redirect_uri = q.get("redirect_uri", "")
    if not redirect_uri:
        return PlainTextResponse("missing redirect_uri", status_code=400)
    code = secrets.token_urlsafe(24)
    _codes[code] = {
        "exp": time.time() + 600,
        "challenge": q.get("code_challenge", ""),
        "method": q.get("code_challenge_method", "plain"),
        "client_id": q.get("client_id", ""),
        "redirect_uri": redirect_uri,
    }
    params = {"code": code, "iss": ISSUER}
    if q.get("state"):
        params["state"] = q.get("state")
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(redirect_uri + sep + urlencode(params), status_code=302)


async def _token(request):
    log.warning("TOKEN hit ua=%s path=%s", request.headers.get("user-agent"), request.url.path)
    raw = (await request.body()).decode("utf-8", "ignore")
    form = dict(parse_qsl(raw))
    grant = form.get("grant_type", "")
    if grant == "authorization_code":
        rec = _codes.pop(form.get("code", ""), None)
        if not rec or rec["exp"] < time.time():
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        if rec["challenge"]:
            verifier = form.get("code_verifier", "")
            if rec["method"] == "S256":
                digest = hashlib.sha256(verifier.encode()).digest()
                expect = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
            else:
                expect = verifier
            if not verifier or expect != rec["challenge"]:
                return JSONResponse(
                    {"error": "invalid_grant", "error_description": "PKCE failed"},
                    status_code=400,
                )
        at = secrets.token_urlsafe(32)
        _tokens[at] = time.time() + 3600
        return JSONResponse({
            "access_token": at,
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "read write",
            "refresh_token": secrets.token_urlsafe(32),
        })
    if grant == "refresh_token":
        at = secrets.token_urlsafe(32)
        _tokens[at] = time.time() + 3600
        return JSONResponse({
            "access_token": at,
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "read write",
        })
    return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)


async def _catchall(request):
    path = request.url.path
    if "oauth-protected-resource" in path:
        return _prm(request)
    if "oauth-authorization-server" in path:
        return _asm(request)
    if path.rstrip("/").endswith("/register") and request.method == "POST":
        return await _register(request)
    if path.rstrip("/").endswith("/authorize") and request.method == "GET":
        return await _authorize(request)
    if path.rstrip("/").endswith("/token") and request.method == "POST":
        return await _token(request)
    return PlainTextResponse("not found", status_code=404)


def build_app():
    app = mcp.streamable_http_app()
    app.routes.extend([
        Route("/.well-known/oauth-protected-resource", _prm),
        Route("/.well-known/oauth-protected-resource/{rest:path}", _prm),
        Route("/.well-known/oauth-authorization-server", _asm),
        Route("/.well-known/oauth-authorization-server/{rest:path}", _asm),
        Route("/register", _register, methods=["POST"]),
        Route("/authorize", _authorize, methods=["GET"]),
        Route("/token", _token, methods=["POST"]),
        Route("/{rest:path}", _catchall, methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]),
    ])
    return app


if __name__ == "__main__":
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    uvicorn.run(build_app(), host=HOST, port=PORT, log_level="info")
