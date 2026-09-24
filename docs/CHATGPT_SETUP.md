# ChatGPT App setup (copy-paste)

## App name

```
Jisr Bridge — Server Ops
```

## Description

```
Operations bridge to the production server: site files, read-only SQL, Docker, nginx, logs, Redis, backups, and deployments. All real work runs through a mandatory 10-stage chain: open it with waeyuk_start, advance stage-by-stage with waeyuk_advance, never skip. Write tools (ss_writefile, jisr_agent, ss_db_write, ss_git/ss_docker writes, backups) REQUIRE a live chain_id and refuse without it. Per stage, load the expert skill via waeyuk_agents_list + waeyuk_skill_read, persist facts with chain_memory, reason with waeyuk_think.
```

## OAuth endpoints (if the form asks)

```
Issuer:   <JISR_OAUTH_ISSUER>
Authorize: <JISR_OAUTH_ISSUER>/authorize
Token:     <JISR_OAUTH_ISSUER>/token
Register:  <JISR_OAUTH_ISSUER>/register
```

(Registration auto-approves — no manual client setup needed.)

## App instructions (if the form has an Instructions field)

```
For ANY task on the main server: FIRST call waeyuk_start. Follow the 10 stages (SPEC>CLARIFY>PLAN>TASKS>BUILD>TEST>SECURITY>QUALITY>REVIEW>DELIVER) via waeyuk_advance. Never invent tools. If waeyuk_start is missing, report it instead of working around it.
```

## First message in every new chat

```
List your tools starting with waeyuk, ss_, net_, chain_, then start any real work by opening a chain with waeyuk_start.
```

## Troubleshooting: new tools don't appear

The client caches the tool list per app. Fix: **Settings → Apps → remove the bridge → re-add it → open a new chat.**
