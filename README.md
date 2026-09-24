# Jisr Bridge — MCP Operations Bridge with Mandatory Agent Chain

A private **Model Context Protocol (MCP) bridge** that lets an AI assistant (ChatGPT/Claude/Gemini)
operate a production server **through a small gateway host**, with every real task forced through a
**10-stage expert chain** built from a mirrored bundle of OpenCode agents & skills.

```
┌──────────┐   MCP (OAuth)   ┌──────────────┐   SSH (key)   ┌──────────────┐
│   GPT    │ ───────────────▶ │  jisr bridge │ ───────────▶ │ MAIN server  │
│ (client) │  36 tools        │  this repo   │  root@host  │ production   │
└──────────┘   + instructions └──────────────┘              └──────────────┘
```

No task is done in one shot: one user order = one chain of 10 stages
(`SPEC → CLARIFY → PLAN → TASKS → BUILD → TEST → SECURITY → QUALITY → REVIEW → DELIVER`),
each stage driven by a real agent/skill file from `bundle/`. Write tools **refuse** to run
without a live `chain_id`, so sessions stay long, structured, and multi-angle.

## Contents

| Path | What it is |
|---|---|
| `server.py` | FastMCP server (`jisr-bridge`): local pages tools, `ss_exec`, OAuth 2.0 + DCR (auto-approve, private bridge), server-level `instructions` |
| `ss_tools.py` | Bridge tools to MAIN: `ss_db` (read-only SQL), `ss_readfile`, `ss_search`, `ss_writefile` (backup-first, **chain-gated**), `jisr_agent`/`jisr_bg` (autonomous OpenCode worker, **chain-gated**) |
| `waeyuk_chain.py` | **Mandatory chain layer**: `waeyuk_start`, `waeyuk_advance`, `waeyuk_task` (gateway), `waeyuk_chain_status`, `waeyuk_agents_list`, `waeyuk_skill_read` + `chain_required()` gate used by all write tools |
| `waeyuk_plugins.py` | Wave 1 (official-MCP equivalents, zero extra processes): `net_fetch`, `ss_git`, `ss_docker`, `chain_memory`, `util_time`, `waeyuk_think` |
| `waeyuk_plugins2.py` | Wave 2 ops: `ss_health`, `ss_ls`, `ss_logs`, `ss_dbschema`, `ss_db_write` (guardrailed, gated), `ss_backup`, `ss_nginx`, `ss_services`, `net_api`, `net_ssl`, `ss_redis`, `ss_php` |
| `bundle/agent/` | 20 OpenCode agent definitions (orchestrator, implementer, tester, security, database, …) |
| `bundle/skills/` | 34 skills (agent playbooks + speckit commands) |
| `bundle/command/` | `/speckit.*` + `/img` command docs |
| `bundle/AGENTS.md` | Project operating rules (spec-driven, mandatory tests, test-account cleanup, …) |
| `jisr-mcp.service` | systemd unit (localhost-only, auto-restart) |

**36 tools total.** Read tools are open; every write tool requires `chain_id`.

## Requirements

- Bridge host: any small Linux box (Debian 12, 1 GB RAM is enough — everything runs in **one** Python process, no Node needed)
- Python 3.11+, `pip`
- SSH key access from bridge → main (`root@MAIN`, key auth, BatchMode)
- MAIN server: Docker (optional), MySQL via `docker exec <container> mysql` (optional — point at your own DB), nginx (optional)

## Quick start

```bash
# 1. clone + venv
git clone <this-repo> /opt/jisr-mcp && cd /opt/jisr-mcp
python3 -m venv venv && venv/bin/pip install -r requirements.txt

# 2. configure (never commit real values)
cp .env.example .env   # edit: MAIN_SSH_HOST, BRIDGE_SSH_KEY, issuers, tunnel URL

# 3. install service
sudo cp jisr-mcp.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now jisr-mcp.service

# 4. verify: expect 36 tools, waeyuk_start present
venv/bin/python -c "
from server import mcp
import asyncio
async def f():
    print(len([t.name async for t in mcp.list_tools()]) if False else len(await mcp.list_tools()))
asyncio.run(f())"
```

### Environment (.env)

| Var | Purpose | Default |
|---|---|---|
| `MAIN_SSH_HOST` | production server IP/hostname | `192.0.2.10` |
| `BRIDGE_SSH_KEY` | private key bridge→main | `/root/.ssh/jisr_to_ssroot` |
| `JISR_MCP_HOST/PORT` | bind (keep `127.0.0.1`) | `127.0.0.1:8001` |
| `JISR_PUBLIC_MCP_URL` | public MCP URL (tunnel/domain) | `https://example.com/mcp` |
| `JISR_OAUTH_ISSUER` | OAuth issuer base | `https://example.com/oauth` |

## Connecting GPT (ChatGPT Apps)

1. Add the bridge as an App/connector (OAuth auto-approves via DCR).
2. **Open a new chat** with the app attached (tool list is fetched per session).
3. First message (forces discovery + chain discipline):
   > List your tools starting with `waeyuk`, `ss_`, `net_`, `chain_`, then start any real work by opening a chain with `waeyuk_start`.
4. If new tools don't appear: the client cached the old list — **remove + re-add the app**, then open a new chat.

Suggested app description / instructions are in [`docs/CHATGPT_SETUP.md`](docs/CHATGPT_SETUP.md).

## The mandatory workflow (what GPT must do)

```
waeyuk_start(task="...")            → CHAIN OPENED: w... + stage 1/10 (SPEC)
waeyuk_skill_read("waeyuk-agent-spec-architect")
... do SPEC work (ss_readfile/ss_search/ss_db are open) ...
waeyuk_advance(chain_id, stage_output) → stage 2/10 (CLARIFY)
... repeat through PLAN > TASKS > BUILD > TEST > SECURITY > QUALITY > REVIEW > DELIVER ...
writes: ss_writefile(..., chain_id) / jisr_agent(..., chain_id) / ss_db_write(..., chain_id)
memory: chain_memory(chain_id, remember/recall) + waeyuk_think(chain_id, thought)
```

Rules enforced in code: stage output < 20 chars is rejected; `UPDATE`/`DELETE` without `WHERE`
refused; DDL refused; write commands without `chain_id` refused with recovery instructions.

## Security notes

- Bind `127.0.0.1` only; expose via reverse proxy / tunnel with OAuth in front.
- DB credentials are **read at runtime from the main server's `.env`** over SSH — they never live on the bridge and are **not** in this repo.
- `ss_writefile` makes a timestamped `.bak` before overwriting.
- Test accounts created during tasks must be deleted afterwards (see `bundle/AGENTS.md`).
- Review `bundle/AGENTS.md` rules 9–10 (no touching real user data without explicit owner approval).

## ملخص عربي

ده بريدج MCP بين GPT والسيرفر الرئيسي: GPT بيكلم سيرفر صغير (jisr)، والصغير بيكلم الكبير عبر SSH.
أي أمر حقيقي لازم يفتح `chain` من 10 مراحل إجبارية (`waeyuk_start` → `waeyuk_advance` ×10) بالـ agents والـ skills اللي في `bundle/`.
أدوات الكتابة بترفض الشغل من غير `chain_id` — فالسيشن بتطول وبتتغطى من كل الزوايا.
التسطيب: `venv` + `.env` + `systemd` (القسم الإنجليزي فوق فيه الخطوات)، وربط ChatGPT كـ App، ولو الأدوات الجديدة مظهرتش: امسح التطبيق وضيفه تاني + شات جديد.

## License

MIT — see [LICENSE](LICENSE).
