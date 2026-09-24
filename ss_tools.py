"""Extra bridge tools for ss-root: read-only DB, big file reads, code search."""

import base64
import os
import re
import subprocess
try:
    from waeyuk_chain import chain_required as _chain_required, touch_chain as _touch_chain
    _CHAIN_OK = True
except Exception:
    _CHAIN_OK = False

SS_SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
          "-i", os.environ.get("BRIDGE_SSH_KEY", "/root/.ssh/jisr_to_ssroot"), "root@" + os.environ.get("MAIN_SSH_HOST", "192.0.2.10")]
ENV_PATH = "/var/www2/waeyuk.com/.env"
_DB = {}

_CREDS_SCRIPT = """
import base64
d = {}
for _line in open('/var/www2/waeyuk.com/.env'):
    _line = _line.strip()
    if not _line or _line.startswith('#') or '=' not in _line:
        continue
    _k, _v = _line.split('=', 1)
    _v = _v.strip()
    if len(_v) >= 2 and _v[0] == _v[-1] and _v[0] in ('"', "'"):
        _v = _v[1:-1]
    d[_k.strip()] = _v
print(d.get('DB_USER', ''))
print(base64.b64encode(d.get('DB_PASS', '').encode()).decode())
print(d.get('DB_NAME', ''))
""".strip() + "\n"


def _run(argv, data=None, timeout=60):
    return subprocess.run(SS_SSH + argv, input=data, capture_output=True,
                          text=True, timeout=timeout)


def _db_creds():
    if _DB.get("ok"):
        return _DB["u"], _DB["p"], _DB["d"]
    r = _run(["python3"], data=_CREDS_SCRIPT, timeout=25)
    lines = (r.stdout or "").split("\n")
    u = lines[0].strip() if len(lines) > 0 else ""
    pb = lines[1].strip() if len(lines) > 1 else ""
    d = lines[2].strip() if len(lines) > 2 else ""
    if not re.fullmatch(r"[A-Za-z0-9_]+", u or "x"):
        raise RuntimeError("bad db user")
    if not re.fullmatch(r"[A-Za-z0-9_]+", d or "x"):
        raise RuntimeError("bad db name")
    if not pb:
        raise RuntimeError("empty db password")
    _DB.update({"ok": True, "u": u, "p": pb, "d": d})
    return u, pb, d


_READ_OK = re.compile(r"(?is)^\s*(SELECT|SHOW|DESCRIBE|DESC|EXPLAIN|WITH)\b")
_READ_NO = re.compile(
    r"(?i)\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE|"
    r"GRANT|REVOKE|LOCK|UNLOCK|HANDLER|LOAD|CALL|DO)\b|INTO\s+(OUTFILE|DUMPFILE)")


def _shq(s):
    return "'" + s.replace("'", "'\\''") + "'"


def _need_chain(chain_id=None):
    if not _CHAIN_OK:
        return None
    cid = chain_id or ""
    ok, msg = _chain_required(cid)
    if not ok:
        return msg
    try:
        _touch_chain(cid)
    except Exception:
        pass
    return None


def register_ss_tools(mcp):
    @mcp.tool()
    def ss_db(query: str) -> str:
        "Run a READ-ONLY SQL query on the main server project database and return rows. SELECT/SHOW/DESCRIBE/EXPLAIN only. Use for counts and marketing stats, e.g. SELECT COUNT(*) FROM specialists."
        q = (query or "").strip()
        if not q or not _READ_OK.match(q) or _READ_NO.search(q):
            return "REFUSED: read-only queries only (SELECT/SHOW/DESCRIBE/EXPLAIN)."
        try:
            u, pb, d = _db_creds()
        except Exception as e:
            return "DB creds error: " + str(e)[:200]
        qb = base64.b64encode(q.encode()).decode()
        remote = ("export MYSQL_PWD=$(printf '%s' '" + pb + "' | base64 -d); "
                  "printf '%s' '" + qb + "' | base64 -d | "
                  "docker exec -i -e MYSQL_PWD waeyuk-db mysql -h127.0.0.1 "
                  "-u'" + u + "' '" + d + "'")
        try:
            r = _run([remote], timeout=90)
        except subprocess.TimeoutExpired:
            return "TIMEOUT after 90s"
        except Exception as e:
            return "ERROR: " + str(e)[:200]
        out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
        if len(out) > 30000:
            out = out[:30000] + "\n...[truncated, refine query]..."
        return out or "(no rows)"

    @mcp.tool()
    def ss_readfile(path: str, max_chars: int = 60000) -> str:
        "Read any text file on the MAIN server. Use for marketing pages, configs, code. Example path: /var/www2/waeyuk.com/public/index.php"
        try:
            mc = max(1000, min(int(max_chars or 60000), 200000))
        except Exception:
            mc = 60000
        try:
            r = _run(["cat " + _shq(path)], timeout=30)
        except Exception as e:
            return "ERROR: " + str(e)[:200]
        if r.returncode != 0:
            return "READ FAILED: " + (r.stderr or "")[:500]
        out = r.stdout or ""
        if len(out) > mc:
            out = out[:mc] + "\n...[truncated]..."
        return out or "(empty file)"

    @mcp.tool()
    def ss_search(pattern: str, directory: str = "/var/www2/waeyuk.com",
                  max_results: int = 50) -> str:
        "Fixed-string code/text search on the MAIN server (grep -rn). Use to find features, pages, tracking pixels."
        try:
            mr = max(5, min(int(max_results or 50), 200))
        except Exception:
            mr = 50
        pb = base64.b64encode((pattern or "").encode()).decode()
        remote = ("PAT=$(printf '%s' '" + pb + "' | base64 -d); "
                  "grep -rn -I -F -m " + str(mr * 4) + " -- \"$PAT\" " +
                  _shq(directory) + " 2>/dev/null | head -n " + str(mr))
        try:
            r = _run([remote], timeout=60)
        except Exception as e:
            return "ERROR: " + str(e)[:200]
        return (r.stdout or "(no matches)")[:20000]

    @mcp.tool()
    def ss_writefile(path: str, new_content: str, chain_id: str = "") -> str:
        """WRITE REQUIRES chain_id from waeyuk_start/waeyuk_task (10-stage mandatory chain)."""
        _ref = _need_chain(chain_id)
        if _ref:
            return _ref
        "Create or overwrite ANY file on the MAIN server (full write access). Always makes a timestamped .bak backup first when the file exists. Returns backup path and bytes written."
        import datetime as _dt
        try:
            r = _run(["test -e " + _shq(path) + " && echo EXISTS || echo NEW"],
                     timeout=20)
            bak = ""
            if "EXISTS" in (r.stdout or ""):
                stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
                bak = path + ".bak-" + stamp
                rb = _run(["cp -p " + _shq(path) + " " + _shq(bak) +
                           " && echo BACKUP-OK"], timeout=30)
                if "BACKUP-OK" not in (rb.stdout or ""):
                    return "BACKUP FAILED, aborting write: " + (rb.stderr or "")[:300]
            b64 = base64.b64encode((new_content or "").encode()).decode()
            remote = ("printf '%s' '" + b64 + "' | base64 -d > " +
                      _shq(path) + " && wc -c < " + _shq(path))
            rw = _run([remote], timeout=60)
            if rw.returncode != 0:
                return "WRITE FAILED: " + (rw.stderr or "")[:300]
            msg = "OK: wrote " + (rw.stdout or "").strip() + " bytes to " + path
            if bak:
                msg += " (backup: " + bak + ")"
            return msg
        except subprocess.TimeoutExpired:
            return "TIMEOUT"
        except Exception as e:
            return "ERROR: " + str(e)[:200]


    OP_BIN = "/root/.opencode/bin/opencode"
    OP_SKILLS_DIRS = ["/root/.agents/skills", "/root/opencode/.opencode/skills"]
    OP_SAFE_DIRS = ("/var/www2/", "/tmp/", "/opt/", "/root/")
    SKILLS_SCRIPT = """
import os, re
seen = {}
for base in ['/root/.agents/skills', '/root/opencode/.opencode/skills']:
    try:
        names = sorted(os.listdir(base))
    except Exception:
        continue
    for n in names:
        p = os.path.join(base, n, 'SKILL.md')
        if n in seen or not os.path.isfile(p):
            continue
        try:
            txt = open(p, encoding='utf-8', errors='ignore').read(2000)
        except Exception:
            continue
        m = re.search(r'^description:\\s*(.+)$', txt, re.M)
        seen[n] = (m.group(1).strip()[:300] if m else '')
for n in sorted(seen):
    print(n + ' | ' + seen[n])
""".strip() + "\n"

    @mcp.tool()
    def jisr_agent_skills() -> str:
        """List all expert skill playbooks on the main server (name + what each does). WORKFLOW: you are the brain. For any non-trivial task: 1) call this, 2) read the chosen SKILL.md with ss_readfile, 3) execute it step by step yourself with ss_exec/ss_writefile. Use jisr_agent only for long autonomous runs."""
        try:
            r = subprocess.run(SS_SSH + ["python3"], input=SKILLS_SCRIPT,
                               capture_output=True, text=True, timeout=30)
        except Exception as e:
            return "ERROR: " + str(e)[:200]
        if r.returncode != 0:
            return "LIST FAILED: " + (r.stderr or "")[:300]
        return (r.stdout or "").strip() or "(no skills found)"

    @mcp.tool()
    def jisr_agent(task: str, skill: str = "", workdir: str = "/var/www2/waeyuk.com", timeout_min: int = 10, model: str = "", chain_id: str = "") -> str:
        """Run the autonomous OpenCode worker on the MAIN server (needs model credits; if it reports 402/credits errors, fall back to brain mode). Args: task, skill (from jisr_agent_skills), workdir (/var/www2/waeyuk.com), timeout_min 1-30, model override. PREFERRED MODE is brain mode: read the skill file yourself with ss_readfile and execute it with ss_exec/ss_writefile — you reason, no extra model cost. Use this tool only for long unattended runs."""
        t = (task or "").strip()
        if not t or len(t) < 10:
            return "Give a specific task (min 10 chars)."
        if len(t) > 8000:
            return "Task too long (max 8000 chars)."
        _ref = _need_chain(chain_id)
        if _ref:
            return _ref
        wd = (workdir or "/var/www2/waeyuk.com").strip()
        wd_check = wd.rstrip("/") + "/"
        if not wd_check.startswith(("/var/www2/", "/tmp/", "/opt/", "/root/")):
            return "Workdir not allowed. Use /var/www2/, /tmp/, /opt/ or /root/."
        try:
            mins = max(1, min(int(timeout_min or 10), 30))
        except Exception:
            mins = 10
        sk = (skill or "").strip()
        if sk and not re.fullmatch(r"[A-Za-z0-9_.+-]{2,80}", sk):
            return "Bad skill name."
        prompt = ("Use the '" + sk + "' skill for this task. " + t) if sk else t
        parts = ["cd", _shq(wd), "&&", "timeout", str(mins * 60),
                 _shq(OP_BIN), "run"]
        if (model or "").strip():
            parts += ["--model", _shq(model.strip())]
        parts += [_shq(prompt)]
        try:
            r = subprocess.run(SS_SSH + [" ".join(parts)], capture_output=True,
                               text=True, timeout=mins * 60 + 60)
        except subprocess.TimeoutExpired:
            return "TIMEOUT after " + str(mins) + "min (bridge level)."
        except Exception as e:
            return "ERROR: " + str(e)[:200]
        out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
        out += "\n[exit=" + str(r.returncode) + "]"
        if len(out) > 30000:
            out = out[:30000] + "\n...[truncated, ask for a summary rerun]..."
        return out or "(empty output)"


    import time as _time
    import secrets as _sx

    @mcp.tool()
    def jisr_bg(command: str, workdir: str = "/var/www2/waeyuk.com", chain_id: str = "") -> str:
        """BG REQUIRES chain_id from waeyuk_start/waeyuk_task."""
        _ref = _need_chain(chain_id)
        if _ref:
            return _ref
        """Launch a LONG shell command in the BACKGROUND on the MAIN server and return immediately with a job_id. For test suites, builds, migrations, scans. Poll with jisr_bg_check. GPT stays the brain: launch, do other steps, check back."""
        cmd = (command or "").strip()
        if not cmd or len(cmd) > 8000:
            return "Give a command (max 8000 chars)."
        wd = (workdir or "/var/www2/waeyuk.com").strip()
        wd_check = wd.rstrip("/") + "/"
        if not wd_check.startswith(("/var/www2/", "/tmp/", "/opt/", "/root/")):
            return "Workdir not allowed."
        jid = "j" + _time.strftime("%Y%m%d-%H%M%S") + "-" + _sx.token_hex(3)
        jb = "/tmp/jisr-jobs"
        script = "cd " + _shq(wd) + "\n" + cmd + "\necho JISR_EXIT:$?\n"
        b64 = base64.b64encode(script.encode()).decode()
        launch = ("mkdir -p " + jb + " && echo '" + b64 + "' | base64 -d > " +
                  jb + "/" + jid + ".sh && chmod +x " + jb + "/" + jid +
                  ".sh && rm -f " + jb + "/" + jid + ".log && setsid nohup bash " +
                  jb + "/" + jid + ".sh > " + jb + "/" + jid + ".log 2>&1 < /dev/null & echo \"PID:$!\"")
        try:
            r = subprocess.run(SS_SSH + [launch], capture_output=True,
                               text=True, timeout=30)
        except Exception as e:
            return "ERROR: " + str(e)[:200]
        if r.returncode != 0:
            return "LAUNCH FAILED: " + (r.stderr or "")[:300]
        try:
            subprocess.run(SS_SSH + ["find " + jb + " -name 'j*.log' -mtime +1 -delete"], capture_output=True, text=True, timeout=20)
        except Exception:
            pass
        return "JOB STARTED: " + jid + "\n" + (r.stdout or "").strip() + "\nPoll with jisr_bg_check(\"" + jid + "\")."

    @mcp.tool()
    def jisr_bg_check(job_id: str, tail_lines: int = 60) -> str:
        """Check a background job: running or done, exit code, and log tail. Call repeatedly until done, then continue the task from the output."""
        jid = (job_id or "").strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9\-]{2,40}", jid):
            return "Bad job id."
        try:
            tl = max(5, min(int(tail_lines or 60), 200))
        except Exception:
            tl = 60
        jb = "/tmp/jisr-jobs"
        pat = "[" + jid[0] + "]" + jid[1:] + ".sh"
        script = ("L=" + jb + "/" + jid + ".log; "
                  "if [ ! -f \"$L\" ]; then echo NO-SUCH-JOB; exit 0; fi; "
                  "if pgrep -f " + _shq("jisr-jobs/" + pat) + " >/dev/null; then echo STATUS:RUNNING; "
                  "else echo STATUS:DONE; fi; "
                  "grep -a 'JISR_EXIT:' \"$L\" | tail -1; "
                  "echo ---LOG-TAIL---; tail -n " + str(tl) + " \"$L\"")
        try:
            r = subprocess.run(SS_SSH + [script], capture_output=True,
                               text=True, timeout=30)
        except Exception as e:
            return "ERROR: " + str(e)[:200]
        out = (r.stdout or "").strip() or "(empty)"
        if len(out) > 20000:
            out = out[:20000] + "\n...[truncated]..."
        return out
