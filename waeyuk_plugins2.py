"""Waeyuk plugins WAVE 2 — ops for the MAIN server (plain PHP 8.3 + MySQL + redis + nginx).

Same-layer native tools (zero extra processes). READ ops OPEN, WRITE ops
chain-gated via waeyuk_start/waeyuk_task chain_id.

  ss_health    dashboard: load/mem/disk/docker/nginx/db/redis/site (read)
  ss_ls        list directory on MAIN (allowlisted roots) (read)
  ss_logs      tail + grep log files on MAIN (read)
  ss_dbschema  SHOW TABLES / DESCRIBE / indexes (read)
  ss_db_write  INSERT/UPDATE/DELETE with guardrails (WRITE-gated)
  ss_backup    mysqldump / tar to /var/www2/backups-export (WRITE-gated)
  ss_nginx     nginx -t + server_names (read); reload (WRITE-gated)
  ss_services  systemctl status + journalctl (read); restart (WRITE-gated)
  net_api      GET/HEAD (open); POST/PUT/PATCH/DELETE with JSON (WRITE-gated)
  net_ssl      cert expiry for host:443 (read, runs on jisr)
  ss_redis     ping/info/dbsize (read); del/flushdb on selected container (WRITE-gated)
  ss_php       php -v / php -l / composer validate (read)
"""

import base64
import re
import subprocess

try:
    from ss_tools import SS_SSH as _SS, _shq as _shq, _db_creds as _creds
    _BRIDGE_OK = True
except Exception:
    _BRIDGE_OK = False
    _SS = []

try:
    from waeyuk_chain import chain_required as _chain_req, touch_chain as _touch
    _CHAIN_OK = True
except Exception:
    _CHAIN_OK = False

_LS_ROOTS = ("/var/www2/", "/opt/", "/tmp/", "/root/",
             "/var/log/", "/etc/nginx/")
_LOG_OK = re.compile(r"^/(var/log/|var/www2/[\w.\-]+/storage/logs/|tmp/)")


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


def _ssh(cmd, timeout=60):
    r = subprocess.run(_SS + [cmd], capture_output=True,
                       text=True, timeout=timeout)
    out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
    return (out[:15000] or "(empty)") + "\n[exit=%d]" % r.returncode


def _mysql_wrap(sql, timeout=90):
    u, pb, d = _creds()
    qb = base64.b64encode(sql.encode()).decode()
    remote = ("export MYSQL_PWD=$(printf '%s' '" + pb + "' | base64 -d); "
              "printf '%s' '" + qb + "' | base64 -d | "
              "docker exec -i -e MYSQL_PWD waeyuk-db mysql -h127.0.0.1 "
              "-u'" + u + "' '" + d + "'")
    return _ssh(remote, timeout)


def register_plugin2_tools(mcp):
    @mcp.tool()
    def ss_health() -> str:
        """One-shot health dashboard of MAIN server: load/mem/disk/docker/nginx/db/redis. No chain needed."""
        if not _BRIDGE_OK:
            return "Bridge not available."
        cmd = ("echo '--- uptime ---'; uptime; "
               "echo '--- mem ---'; free -m | head -n 3; "
               "echo '--- disk ---'; df -h / /var 2>/dev/null | head -n 5; "
               "echo '--- docker ---'; docker ps --format '{{.Names}} {{.Status}}' | head -n 30; "
               "echo '--- nginx ---'; nginx -t 2>&1 | head -n 5; "
               "echo '--- site ---'; curl -s -m 10 -o /dev/null -w '%{http_code} %{time_total}s' https://waeyuk.com 2>&1; echo")
        try:
            out = _ssh(cmd)
        except Exception as e:
            return "ERROR: %s" % str(e)[:200]
        try:
            u, pb, d = _creds()
            rq = subprocess.run(
                _SS + ["export MYSQL_PWD=$(printf '%s' '" + pb +
                       "' | base64 -d); docker exec -i -e MYSQL_PWD waeyuk-db "
                       "mysql -h127.0.0.1 -u'" + u + "' '" + d +
                       "' -e 'SELECT 1' 2>&1 | head -n 3"],
                capture_output=True, text=True, timeout=30)
            out += "\n--- db ---\n" + ((rq.stdout or "")[:300] or "(db ping failed)")
        except Exception as e:
            out += "\n--- db ---\nERROR: %s" % str(e)[:150]
        try:
            rr = subprocess.run(
                _SS + ["docker exec waeyuk-redis redis-cli ping 2>&1 || "
                       "docker exec mb-redis redis-cli ping 2>&1 | head -n 2"],
                capture_output=True, text=True, timeout=30)
            out += "\n--- redis ---\n" + ((rr.stdout or "")[:200] or "(no redis)")
        except Exception as e:
            out += "\n--- redis ---\nERROR: %s" % str(e)[:150]
        return out[:15000]

    @mcp.tool()
    def ss_ls(path: str = "/var/www2/waeyuk.com", max_entries: int = 100) -> str:
        """List a directory on MAIN (sizes + dates). Roots: /var/www2 /opt /tmp /root /var/log /etc/nginx. No chain needed."""
        if not _BRIDGE_OK:
            return "Bridge not available."
        p = (path or "").strip()
        if ".." in p or not p.startswith(_LS_ROOTS):
            return "REFUSED: path must be under: %s" % ", ".join(_LS_ROOTS)
        try:
            n = max(10, min(int(max_entries or 100), 300))
        except Exception:
            n = 100
        try:
            return _ssh("ls -la --time-style=long-iso %s 2>&1 | head -n %d"
                        % (_shq(p), n + 5))
        except Exception as e:
            return "ERROR: %s" % str(e)[:200]

    @mcp.tool()
    def ss_logs(path: str, pattern: str = "", tail_lines: int = 60) -> str:
        """Tail (+optional grep) a log file on MAIN. Allowed: /var/log/*, */storage/logs/*, /tmp/*. No chain needed. For docker logs use ss_docker."""
        if not _BRIDGE_OK:
            return "Bridge not available."
        p = (path or "").strip()
        if ".." in p or not _LOG_OK.match(p.lstrip("/")) and not p.startswith(
                ("/var/log/", "/tmp/")):
            return ("REFUSED: logs only from /var/log/, /tmp/, "
                    "*/storage/logs/.")
        try:
            tl = max(5, min(int(tail_lines or 60), 300))
        except Exception:
            tl = 60
        pat = (pattern or "").strip()
        if pat:
            if len(pat) > 120 or not re.fullmatch(
                    r"[A-Za-z0-9 _\-.,:/()\[\]ء-غ]+", pat):
                return "REFUSED: bad pattern chars."
            pb = base64.b64encode(pat.encode()).decode()
            cmd = ("PAT=$(printf '%s' '%s' | base64 -d); tail -n %d %s | "
                   "grep -a -i -F -- \"$PAT\" | tail -n %d"
                   % (pb, tl * 5, _shq(p), tl))
        else:
            cmd = "tail -n %d %s" % (tl, _shq(p))
        try:
            return _ssh(cmd)
        except Exception as e:
            return "ERROR: %s" % str(e)[:200]

    @mcp.tool()
    def ss_dbschema(table: str = "") -> str:
        """DB schema explorer (read-only): empty table -> SHOW TABLES; else DESCRIBE + indexes. No chain needed. Data queries: ss_db."""
        if not _BRIDGE_OK:
            return "Bridge not available."
        t = (table or "").strip()
        if t and not re.fullmatch(r"[A-Za-z0-9_]{1,64}", t):
            return "REFUSED: bad table name."
        sql = ("SHOW TABLES;" if not t else
               "DESCRIBE `%s`; SHOW INDEX FROM `%s`;" % (t, t))
        try:
            return _mysql_wrap(sql)[:12000]
        except Exception as e:
            return "ERROR: %s" % str(e)[:200]

    @mcp.tool()
    def ss_db_write(sql: str, chain_id: str = "") -> str:
        """WRITE to MAIN project DB (INSERT/UPDATE/DELETE only, chain-gated). UPDATE/DELETE REQUIRE WHERE. DROP/ALTER/CREATE/TRUNCATE refused. Test accounts must be deleted after the task (owner rule 2026-09-09)."""
        ref = _need_chain(chain_id)
        if ref:
            return ref
        if not _BRIDGE_OK:
            return "Bridge not available."
        q = (sql or "").strip().rstrip(";")
        if not re.match(r"(?is)^\s*(INSERT|UPDATE|DELETE)\b", q):
            return "REFUSED: INSERT/UPDATE/DELETE only."
        if re.search(r"(?i)\b(DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|LOCK|HANDLER|CALL|DO)\b|INTO\s+(OUTFILE|DUMPFILE)",
                     q):
            return "REFUSED: DDL/admin/outfile not allowed here."
        if re.match(r"(?is)^\s*(UPDATE|DELETE)\b", q) and not re.search(
                r"(?i)\bWHERE\b", q):
            return "REFUSED: UPDATE/DELETE without WHERE would wipe a table."
        if len(q) > 8000:
            return "REFUSED: max 8000 chars, split it."
        try:
            return _mysql_wrap(q + "; SELECT ROW_COUNT() AS affected;")[:8000]
        except Exception as e:
            return "ERROR: %s" % str(e)[:200]

    @mcp.tool()
    def ss_backup(kind: str = "db", target: str = "", chain_id: str = "") -> str:
        """Backup before risky ops (chain-gated). kind=db (target=table or empty=full DB) via mysqldump; kind=files (target=dir under /var/www2 or /opt) via tar. Output -> /var/www2/backups-export/."""
        ref = _need_chain(chain_id)
        if ref:
            return ref
        if not _BRIDGE_OK:
            return "Bridge not available."
        k = (kind or "").strip().lower()
        t = (target or "").strip()
        stamp = subprocess.run(["date", "+%Y%m%d-%H%M%S"], capture_output=True,
                               text=True).stdout.strip() or "ts"
        if k == "db":
            if t and not re.fullmatch(r"[A-Za-z0-9_]{1,64}", t):
                return "REFUSED: bad table name."
            try:
                u, pb, d = _creds()
            except Exception as e:
                return "DB creds error: %s" % str(e)[:150]
            fn = "/var/www2/backups-export/jisr-%s-%s%s.sql.gz" % (
                stamp, d, ("-" + t) if t else "-full")
            what = ("%s %s" % (d, t)) if t else d
            remote = ("mkdir -p /var/www2/backups-export && export MYSQL_PWD=$(printf '%s' '%s' | base64 -d); "
                      "docker exec -e MYSQL_PWD waeyuk-db mysqldump -h127.0.0.1 -u'%s' %s 2>/dev/null | gzip > %s && ls -la %s"
                      % (pb, u, what, _shq(fn), _shq(fn)))
            try:
                return _ssh(remote, timeout=300)[:2000]
            except Exception as e:
                return "ERROR: %s" % str(e)[:200]
        if k == "files":
            if ".." in t or not t.startswith(("/var/www2/", "/opt/")):
                return "REFUSED: files backup only under /var/www2/ or /opt/."
            safe = re.sub(r"[^A-Za-z0-9_.\-]", "_", t.strip("/"))[:60]
            fn = "/var/www2/backups-export/jisr-%s-%s.tar.gz" % (stamp, safe)
            try:
                return _ssh("mkdir -p /var/www2/backups-export && tar czf %s %s 2>/dev/null && ls -la %s"
                            % (_shq(fn), _shq(t), _shq(fn)), timeout=300)[:2000]
            except Exception as e:
                return "ERROR: %s" % str(e)[:200]
        return "kinds: db | files."

    @mcp.tool()
    def ss_nginx(action: str = "test", chain_id: str = "") -> str:
        """Nginx on MAIN: test (nginx -t) + sites (server_names) are open; reload needs chain_id."""
        if not _BRIDGE_OK:
            return "Bridge not available."
        a = (action or "").strip().lower()
        if a == "test":
            try:
                return _ssh("nginx -t 2>&1")
            except Exception as e:
                return "ERROR: %s" % str(e)[:200]
        if a == "sites":
            try:
                return _ssh("grep -rhoE 'server_name[^;]+' /etc/nginx/ 2>/dev/null | head -n 40")
            except Exception as e:
                return "ERROR: %s" % str(e)[:200]
        if a == "reload":
            ref = _need_chain(chain_id)
            if ref:
                return ref
            try:
                return _ssh("nginx -t 2>&1 && systemctl reload nginx 2>&1; echo reloaded:$?")
            except Exception as e:
                return "ERROR: %s" % str(e)[:200]
        return "actions: test | sites | reload(chain-gated)."

    @mcp.tool()
    def ss_services(unit: str = "", action: str = "list",
                    chain_id: str = "") -> str:
        """systemd on MAIN: list (running services) + status/journal per unit are open; restart needs chain_id."""
        if not _BRIDGE_OK:
            return "Bridge not available."
        a = (action or "").strip().lower()
        u = (unit or "").strip()
        if u and not re.fullmatch(r"[A-Za-z0-9@_.\-]{1,80}", u):
            return "REFUSED: bad unit name."
        try:
            if a == "list":
                return _ssh("systemctl list-units --type=service --state=running --no-pager 2>&1 | head -n 40")
            if a in ("status", "journal"):
                if not u:
                    return "REFUSED: %s needs unit." % a
                cmd = ("systemctl status %s --no-pager 2>&1 | head -n 30"
                       % _shq(u) if a == "status" else
                       "journalctl -u %s -n 50 --no-pager 2>&1 | tail -n 50"
                       % _shq(u))
                return _ssh(cmd)
            if a == "restart":
                ref = _need_chain(chain_id)
                if ref:
                    return ref
                if not u:
                    return "REFUSED: restart needs unit."
                return _ssh("systemctl restart %s 2>&1; echo restarted:$?"
                            % _shq(u))
        except Exception as e:
            return "ERROR: %s" % str(e)[:200]
        return "actions: list | status | journal | restart(chain-gated)."

    @mcp.tool()
    def net_api(url: str, method: str = "GET", body: str = "",
                chain_id: str = "") -> str:
        """HTTP API tester (JSON). GET/HEAD open; POST/PUT/PATCH/DELETE need chain_id. Body max 8k. Response truncated 8k."""
        m = (method or "GET").strip().upper()
        u = (url or "").strip()
        if not re.match(r"^https?://", u, re.I) or len(u) > 2000:
            return "REFUSED: http(s) URL only."
        if m not in ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"):
            return "REFUSED: bad method."
        if m not in ("GET", "HEAD"):
            ref = _need_chain(chain_id)
            if ref:
                return ref
        b = (body or "")
        if len(b) > 8000:
            return "REFUSED: body max 8000 chars."
        if b:
            try:
                json.loads(b)
            except Exception:
                return "REFUSED: body must be valid JSON."
        try:
            import httpx
            r = httpx.request(m, u, content=b or None, timeout=30,
                              follow_redirects=True,
                              headers={"Content-Type": "application/json",
                                       "User-Agent": "jisr-bridge/1.0"})
            head = "%s %s -> HTTP %d | %d bytes\n" % (m, u, r.status_code,
                                                      len(r.text or ""))
            return head + (r.text or "(empty)")[:8000]
        except Exception as e:
            return "API FAILED: %s" % str(e)[:300]

    @mcp.tool()
    def net_ssl(host: str) -> str:
        """Cert expiry check (like a tiny SSL monitor): subject/issuer/dates for host:443. No chain needed."""
        h = (host or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9.\-]{3,120}", h):
            return "REFUSED: bad hostname."
        try:
            p1 = subprocess.run(
                ["openssl", "s_client", "-connect", "%s:443" % h,
                 "-servername", h], input="",
                capture_output=True, text=True, timeout=25)
            p2 = subprocess.run(
                ["openssl", "x509", "-noout", "-subject", "-issuer",
                 "-dates"], input=p1.stdout,
                capture_output=True, text=True, timeout=15)
            out = (p2.stdout or "").strip()
            if not out:
                return "SSL FAILED for %s: %s" % (
                    h, (p1.stderr or "")[:200])
            return out[:1000]
        except Exception as e:
            return "ERROR: %s" % str(e)[:200]

    @mcp.tool()
    def ss_redis(container: str = "waeyuk-redis", action: str = "info",
                 key: str = "", chain_id: str = "") -> str:
        """Redis on MAIN (waeyuk-redis/mb-redis/chatwoot-redis): ping/info/dbsize open; get/del/flushdb need chain_id."""
        if not _BRIDGE_OK:
            return "Bridge not available."
        c = (container or "").strip()
        if c not in ("waeyuk-redis", "mb-redis", "chatwoot-redis"):
            return "REFUSED: container one of waeyuk-redis/mb-redis/chatwoot-redis."
        a = (action or "").strip().lower()
        k = (key or "").strip()
        if k and not re.fullmatch(r"[A-Za-z0-9_:.\-]{1,200}", k):
            return "REFUSED: bad key."
        if a in ("ping", "info", "dbsize"):
            cmd = {"ping": "docker exec %s redis-cli ping",
                   "info": "docker exec %s redis-cli info server | head -n 15",
                   "dbsize": "docker exec %s redis-cli dbsize"}[a] % _shq(c)
            try:
                return _ssh(cmd)
            except Exception as e:
                return "ERROR: %s" % str(e)[:200]
        if a in ("get", "del", "flushdb"):
            ref = _need_chain(chain_id)
            if ref:
                return ref
            if a in ("get", "del") and not k:
                return "REFUSED: %s needs key." % a
            cmd = {"get": "docker exec %s redis-cli GET %s",
                   "del": "docker exec %s redis-cli DEL %s",
                   "flushdb": "docker exec %s redis-cli FLUSHDB"}[a]
            cmd = cmd % (_shq(c), _shq(k)) if k else cmd % _shq(c)
            try:
                return _ssh(cmd)
            except Exception as e:
                return "ERROR: %s" % str(e)[:200]
        return "actions: ping/info/dbsize (open) | get/del/flushdb (chain-gated)."

    @mcp.tool()
    def ss_php(action: str = "version", path: str = "",
               chain_id: str = "") -> str:
        """PHP 8.3 on MAIN: version (php -v) + lint (php -l file under /var/www2) + composer validate. Read-only, no chain."""
        if not _BRIDGE_OK:
            return "Bridge not available."
        a = (action or "").strip().lower()
        try:
            if a == "version":
                return _ssh("php -v 2>&1 | head -n 3")
            if a == "lint":
                p = (path or "").strip()
                if not p.startswith("/var/www2/") or not p.endswith(".php") or ".." in p:
                    return "REFUSED: lint only *.php under /var/www2/."
                return _ssh("php -l %s 2>&1" % _shq(p))
            if a == "composer":
                p = (path or "/var/www2/waeyuk.com").strip()
                if not p.startswith("/var/www2/") or ".." in p:
                    return "REFUSED: dir under /var/www2/ only."
                return _ssh("cd %s && composer validate --no-check-publish 2>&1 | head -n 10" % _shq(p))
        except Exception as e:
            return "ERROR: %s" % str(e)[:200]
        return "actions: version | lint | composer."
