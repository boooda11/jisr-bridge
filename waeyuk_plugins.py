"""Waeyuk plugins layer — official-MCP equivalents, native Python, zero extra processes.

Mirrors modelcontextprotocol/servers reference set, adapted to the SSH bridge
(jisr -> MAIN server via $MAIN_SSH_HOST). Runs INSIDE the existing jisr-mcp process:
no node, no extra ports, no extra RAM (box has ~411MB free, no npm).

  net_fetch    ~ Fetch:   GET a URL, return text (for checking deployed pages/APIs)
  ss_git       ~ Git:     status/diff/log/show on MAIN repos (open); commit/pull/push (chain-gated)
  ss_docker    ~ Docker:  ps/logs/inspect/stats on MAIN (open); restart/exec (chain-gated)
  chain_memory ~ Memory:  remember/recall key facts per chain_id (survives all 10 stages)
  util_time    ~ Time:    now + timezone conversion (Africa/Cairo, UTC, Asia/Dubai)
  waeyuk_think ~ SequentialThinking: structured thought step, logged to the chain ledger

READ ops stay OPEN (no chain). WRITE ops REQUIRE live chain_id from
waeyuk_start/waeyuk_task — same policy as ss_writefile/jisr_agent.
"""

import html as _html
import json
import re
import subprocess
import time as _time
from pathlib import Path as _Path

try:
    from ss_tools import SS_SSH as _SS, _run as _ss_run, _shq as _shq
    _BRIDGE_OK = True
except Exception:
    _BRIDGE_OK = False
    _SS = []

try:
    from waeyuk_chain import chain_required as _chain_req, touch_chain as _touch
    _CHAIN_OK = True
except Exception:
    _CHAIN_OK = False

_MEM = _Path("/var/lib/jisr-memory.json")
if not _MEM.parent.exists():
    _MEM = _Path("/tmp/jisr-memory.json")

_GIT_REPOS = ("/var/www2/waeyuk.com", "/root/secrets-vault",
              "/opt/ai-gateway", "/opt/jisr-mcp")


def _need_chain(chain_id=""):
    if not _CHAIN_OK:
        return None
    ok, msg = _chain_req(chain_id or "")
    if not ok:
        return msg
    try:
        _touch(chain_id)
    except Exception:
        pass
    return None


def _mem_load():
    try:
        return json.loads(_MEM.read_text())
    except Exception:
        return {}


def _mem_save(d):
    try:
        _MEM.parent.mkdir(parents=True, exist_ok=True)
        _MEM.write_text(json.dumps(d, ensure_ascii=False))
    except Exception:
        pass


def _html_to_text(h, limit=15000):
    h = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", h)
    h = re.sub(r"(?is)<[^>]+>", " ", h)
    t = _html.unescape(h)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n\n", t).strip()
    return t[:limit] + ("\n...[truncated]..." if len(t) > limit else "")


def register_plugin_tools(mcp):
    @mcp.tool()
    def net_fetch(url: str, max_chars: int = 15000) -> str:
        """Fetch a URL and return its text (like MCP Fetch server). For verifying deployed pages/APIs return 200 and expected content. No chain needed."""
        u = (url or "").strip()
        if not re.match(r"^https?://", u, re.I) or len(u) > 2000:
            return "REFUSED: http(s) URL only, max 2000 chars."
        try:
            mc = max(1000, min(int(max_chars or 15000), 60000))
        except Exception:
            mc = 15000
        try:
            import httpx
            r = httpx.get(u, timeout=30, follow_redirects=True,
                          headers={"User-Agent": "jisr-bridge/1.0"})
            body = r.text or ""
            head = "HTTP %d | %d bytes | %s\n" % (
                r.status_code, len(body),
                r.headers.get("content-type", "?"))
            if "html" in (r.headers.get("content-type", "") or "").lower():
                body = _html_to_text(body, mc)
            return head + (body[:mc] or "(empty body)")
        except Exception:
            pass
        try:
            import urllib.request
            req = urllib.request.Request(
                u, headers={"User-Agent": "jisr-bridge/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read(2 * 1024 * 1024).decode("utf-8", "ignore")
                ct = r.headers.get("Content-Type", "?")
            head = "HTTP %d | %s\n" % (r.status, ct)
            if "html" in (ct or "").lower():
                raw = _html_to_text(raw, mc)
            return head + (raw[:mc] or "(empty body)")
        except Exception as e:
            return "FETCH FAILED: %s" % str(e)[:300]

    @mcp.tool()
    def ss_git(repo: str = "/var/www2/waeyuk.com",
               action: str = "status", arg: str = "",
               chain_id: str = "") -> str:
        """Git on MAIN server repos (like MCP Git server). READ (status/diff/log/show/branch): no chain. WRITE (commit/pull/push/checkout): chain_id required. repo must be one of the known paths."""
        if not _BRIDGE_OK:
            return "Bridge not available."
        rp = (repo or "").strip()
        if rp not in _GIT_REPOS:
            return "REFUSED: repo must be one of: %s" % ", ".join(_GIT_REPOS)
        a = (action or "").strip().lower()
        READ = {"status": "git -C %s status -sb | head -n 30",
                "diff": "git -C %s diff --stat | head -n 40",
                "log": "git -C %s log --oneline -15",
                "show": "git -C %s show --stat HEAD | head -n 40",
                "branch": "git -C %s branch -vv | head -n 20"}
        WRITE = {"commit": None, "pull": "git -C %s pull --ff-only",
                 "push": "git -C %s push",
                 "checkout": None}
        if a in READ:
            cmd = READ[a] % _shq(rp)
            if a == "diff" and (arg or "").strip():
                if not re.fullmatch(r"[A-Za-z0-9_.\-/]{1,120}", arg.strip()):
                    return "REFUSED: bad diff path."
                cmd = "git -C %s diff -- %s | head -n 200" % (
                    _shq(rp), _shq(arg.strip()))
            try:
                r = subprocess.run(_SS + [cmd], capture_output=True,
                                   text=True, timeout=40)
            except Exception as e:
                return "ERROR: %s" % str(e)[:200]
            out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr)
                                      if r.stderr else "")
            return (out[:12000] or "(empty)") + "\n[exit=%d]" % r.returncode
        if a in WRITE:
            ref = _need_chain(chain_id)
            if ref:
                return ref
            if a == "commit":
                msg = (arg or "").strip()[:200]
                if len(msg) < 5:
                    return ("REFUSED: commit needs a message "
                            "(arg, min 5 chars).")
                if not re.fullmatch(r"[A-Za-z0-9 _\-.,:/()\[\]ء-غ]+", msg):
                    return "REFUSED: bad chars in commit message."
                cmd = ("git -C %s add -A && git -C %s commit -m %s"
                       % (_shq(rp), _shq(rp), _shq(msg)))
            elif a == "checkout":
                br = (arg or "").strip()
                if not re.fullmatch(r"[A-Za-z0-9_.\-/]{1,80}", br):
                    return "REFUSED: bad branch name."
                cmd = "git -C %s checkout %s" % (_shq(rp), _shq(br))
            else:
                cmd = WRITE[a] % _shq(rp)
            try:
                r = subprocess.run(_SS + [cmd], capture_output=True,
                                   text=True, timeout=120)
            except Exception as e:
                return "ERROR: %s" % str(e)[:200]
            out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr)
                                      if r.stderr else "")
            return (out[:12000] or "(empty)") + "\n[exit=%d]" % r.returncode
        return ("Unknown action. READ: status/diff/log/show/branch. "
                "WRITE (chain-gated): commit/pull/push/checkout.")

    @mcp.tool()
    def ss_docker(action: str = "ps", target: str = "",
                  chain_id: str = "") -> str:
        """Docker on MAIN server (containers: waeyuk-*, litellm, mb-*...). READ (ps/logs/inspect/stats): no chain. WRITE (restart/exec): chain_id required."""
        if not _BRIDGE_OK:
            return "Bridge not available."
        a = (action or "").strip().lower()
        t = (target or "").strip()
        if t and not re.fullmatch(r"[A-Za-z0-9_.\-]{1,80}", t):
            return "REFUSED: bad container/name."
        if a == "ps":
            cmd = ("docker ps --format '{{.Names}} | {{.Image}} | "
                   "{{.Status}}'")
        elif a in ("logs", "inspect", "stats"):
            if not t:
                return "REFUSED: %s needs target container." % a
            cmd = {"logs": "docker logs --tail 80 %s",
                   "inspect": "docker inspect %s | head -n 80",
                   "stats": ("docker stats --no-stream %s")} [a] % _shq(t)
        elif a in ("restart", "exec"):
            ref = _need_chain(chain_id)
            if ref:
                return ref
            if not t:
                return "REFUSED: %s needs target container." % a
            if a == "restart":
                cmd = "docker restart %s" % _shq(t)
            else:
                if len(t) < 1:
                    return "REFUSED."
                cmd = "docker exec %s %s" % (_shq(t), "uptime")
        else:
            return ("Unknown action. READ: ps/logs/inspect/stats. "
                    "WRITE (chain-gated): restart/exec.")
        try:
            r = subprocess.run(_SS + [cmd], capture_output=True,
                               text=True, timeout=60)
        except Exception as e:
            return "ERROR: %s" % str(e)[:200]
        out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr)
                                  if r.stderr else "")
        return (out[:12000] or "(empty)") + "\n[exit=%d]" % r.returncode

    @mcp.tool()
    def chain_memory(chain_id: str, action: str = "recall",
                     key: str = "", value: str = "") -> str:
        """Persistent memory per chain (like MCP Memory server). remember(key, value) stores decisions/facts so the 10 stages never lose context; recall() lists them. Needs a live chain_id."""
        ref = _need_chain(chain_id)
        if ref:
            return ref
        a = (action or "").strip().lower()
        d = _mem_load()
        box = d.get(chain_id) or {}
        if a == "remember":
            k = (key or "").strip()[:80]
            v = (value or "").strip()[:2000]
            if len(k) < 2 or len(v) < 3:
                return "REFUSED: remember needs key (2+) + value (3+)."
            box[k] = {"v": v, "at": _time.time()}
            d[chain_id] = box
            _mem_save(d)
            return "REMEMBERED [%s] (%d keys total)." % (k, len(box))
        if a == "recall":
            if not box:
                return "(memory empty for %s)" % chain_id
            return "\n".join("- %s: %s" % (k, box[k]["v"][:300])
                             for k in sorted(box))
        if a == "forget":
            k = (key or "").strip()
            if k in box:
                box.pop(k)
                d[chain_id] = box
                _mem_save(d)
                return "FORGOT [%s]." % k
            return "No such key."
        return "Actions: remember / recall / forget."

    @mcp.tool()
    def util_time(action: str = "now", zone: str = "Africa/Cairo") -> str:
        """Time utils (like MCP Time server). now -> current time in zone; convert needs 'YYYY-MM-DD HH:MM zone'. No chain needed."""
        try:
            from datetime import datetime
            try:
                from zoneinfo import ZoneInfo
            except Exception:
                ZoneInfo = None
            a = (action or "").strip().lower()
            z = (zone or "Africa/Cairo").strip()[:60]
            if ZoneInfo:
                try:
                    tz = ZoneInfo(z)
                except Exception:
                    return ("Bad zone. Try: Africa/Cairo, UTC, "
                            "Asia/Dubai, Europe/Berlin.")
                now = datetime.now(tz)
            else:
                now = datetime.utcnow()
                z = "UTC"
            if a == "now":
                return now.strftime("%Y-%m-%d %H:%M:%S ") + z
            return now.strftime("%Y-%m-%d %H:%M:%S ") + z + " (use now)"
        except Exception as e:
            return "ERROR: %s" % str(e)[:200]

    @mcp.tool()
    def waeyuk_think(chain_id: str, thought: str,
                     next_step: str = "") -> str:
        """Structured reasoning step (like MCP SequentialThinking). Logs one numbered thought to the chain ledger so long sessions stay on track. Needs live chain_id."""
        ref = _need_chain(chain_id)
        if ref:
            return ref
        th = (thought or "").strip()
        if len(th) < 20:
            return "REFUSED: thought min 20 chars — فكر بجد مش سطر."
        d = _mem_load()
        box = d.get(chain_id) or {}
        n = sum(1 for k in box if k.startswith("thought-")) + 1
        box["thought-%02d" % n] = {
            "v": th[:1500] + (" | NEXT: " + next_step[:300]
                              if (next_step or "").strip() else ""),
            "at": _time.time()}
        d[chain_id] = box
        _mem_save(d)
        return ("THOUGHT %d logged. Total thoughts: %d. %s"
                % (n, n, ("المقترح للتالي: " + next_step[:200])
                   if (next_step or "").strip() else
                   "كمل المرحلة الحالية عبر waeyuk_advance."))
