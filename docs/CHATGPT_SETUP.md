# Links — everything wired together (put literally everything here)

## 1) The bridge link (where the bridge is created / runs)

The bridge MCP server itself runs on your gateway host (`server.py`, localhost-only).
ChatGPT reaches it through an **OpenAI Secure MCP Tunnel** — no public internet
exposure needed:

- **Tunnels management (create / view tunnels):**
  `https://platform.openai.com/settings/organization/tunnels`
- **Create the tunnel profile (first use, on the gateway host):**
  ```bash
  tunnel-client init      # runnable first-use profile
  tunnel-client help quickstart
  ```
- **Run it (systemd keeps it alive — see `jisr-mcp.service` pattern):**
  ```bash
  tunnel-client run \
    --control-plane.tunnel-id=<TUNNEL_ID> \
    --control-plane.api-key=file:/etc/tunnel-client/api-key \
    --mcp.server-url=url=http://127.0.0.1:8001/mcp \
    --harpoon.target=label=main,url=http://127.0.0.1:8001/mcp,desc=jisr-bridge-mcp
  ```
- **Health:** `tunnel-client health`, `tunnel-client help doctor`
- Docs: `https://developers.openai.com/plugins/build/mcp-server`
  (“Secure MCP Tunnel can connect a private MCP server … without exposing the
  server to the public internet.”)

## 2) The key link (where the tunnel API key comes from)

- **Runtime API keys (used by `--control-plane.api-key`):**
  `https://platform.openai.com/settings/organization/api-keys`
- **Admin API keys (tunnel administration):**
  `https://platform.openai.com/settings/organization/admin-keys`
- On the host the key lives in **one file only** (never in the repo):
  `/etc/tunnel-client/api-key` (mode `0600`, referenced as `file:/etc/tunnel-client/api-key`)
- Manage profiles non-interactively:
  `tunnel-client admin-profiles ...`, `tunnel-client profiles ...`

## 3) The addon link (creating the ChatGPT app on top of the bridge)

- **Connectors settings:** `https://chatgpt.com/#settings/Connectors`
- **Create:** ChatGPT → *Settings → Apps → Create* (workspace admins:
  *Workspace settings → Apps → Create*), developer mode on.
  Steps per the official guide: provide the endpoint + metadata → pick auth
  (this bridge: OAuth, auto-approved DCR) → **Scan Tools** → authorize →
  wait for scan → **Create** → draft → Publish.
- **Official guide (read this first):**
  `https://help.openai.com/en/articles/12584461-developer-mode-and-full-mcp-connectors-in-chatgpt`
- OAuth endpoints of THIS bridge (fill from your `.env`):
  ```
  Issuer:   <JISR_OAUTH_ISSUER>               e.g. https://bridge.example.com/oauth
  Authorize: <JISR_OAUTH_ISSUER>/authorize
  Token:     <JISR_OAUTH_ISSUER>/token
  Register:  <JISR_OAUTH_ISSUER>/register
  ```

## 4) App texts (copy-paste — also used at creation)

**Name:** `Jisr Bridge — Server Ops`

**Description:**
```
Operations bridge to the production server: site files, read-only SQL, Docker, nginx, logs, Redis, backups, and deployments. All real work runs through a mandatory 10-stage chain: open it with waeyuk_start, advance stage-by-stage with waeyuk_advance, never skip. Write tools (ss_writefile, jisr_agent, ss_db_write, ss_git/ss_docker writes, backups) REQUIRE a live chain_id and refuse without it. Per stage, load the expert skill via waeyuk_agents_list + waeyuk_skill_read, persist facts with chain_memory, reason with waeyuk_think.
```

**Instructions:**
```
For ANY task on the main server: FIRST call waeyuk_start. Follow the 10 stages (SPEC>CLARIFY>PLAN>TASKS>BUILD>TEST>SECURITY>QUALITY>REVIEW>DELIVER) via waeyuk_advance. Never invent tools. If waeyuk_start is missing, report it instead of working around it.
```

**First message in every new chat:**
```
List your tools starting with waeyuk, ss_, net_, chain_, then start any real work by opening a chain with waeyuk_start.
```

## 5) Cache troubleshooting (new tools don't appear)

The client caches the tool list per app. Fix: **Settings → Apps → remove the
bridge → re-add it → open a new chat.** (On Business plans a published app
can't be updated — recreate + republish.)
