---
name: waeyuk-agent-router
description: Routes Waeyuk engineering work to the appropriate migrated specialist role and model tier. Inspect first, preserve architecture, follow specs, test, and report.
---
# Waeyuk Agent Router
Use the migrated `waeyuk-agent-*` skills as role definitions. Choose the smallest capable role set, never duplicate existing modules without evidence, and follow `/var/www2/.agents-config/AGENT_GATEWAY.md` plus project `AGENTS.md`.
Role mapping: architect=architecture/DB/API; backend=PHP/Node/backend; frontend=UI/UX; database=schema/query; security=security; tester=tests/E2E; performance=performance; devops=server/deploy; designer=visual UX; critic=review; bug-hunt=adversarial audit; clean-code=refactor; spec-architect=Spec Kit; media-fetcher=media assets; image-gen=visual generation; vision=visual inspection; implementer=implementation; legal-egypt=legal/compliance; freebuff=free/open tooling; orchestrator=multi-step coordination.
Before implementation: inspect current code/specs and active work. Prefer existing relevant spec. Never expose secrets. For multi-step work use `/usr/local/bin/waeyuk-agent` as the server execution contract.
