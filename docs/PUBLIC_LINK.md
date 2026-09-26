# Public-link instance (second account via URL, not tunnel)

The default deployment reaches ChatGPT through an **OpenAI Secure MCP Tunnel**
(private, no public surface). For a **second account** (or any client that
can't use your tunnel), this repo also supports a **direct public URL** with
**login-gated OAuth + enforced Bearer tokens**.

## The link

```
MCP endpoint:  https://<YOUR-DOMAIN>/mcp
OAuth issuer:  https://<YOUR-DOMAIN>/oauth
Authorize:     https://<YOUR-DOMAIN>/oauth/authorize
Token:         https://<YOUR-DOMAIN>/oauth/token
Register:      https://<YOUR-DOMAIN>/oauth/register
Metadata:      https://<YOUR-DOMAIN>/.well-known/oauth-authorization-server
```

The client registers (DCR, auto-approved), is redirected to a **bridge login
page**, signs in with the bridge username/password, gets an authorization
code, exchanges it for a Bearer token, and calls tools with that token.

## Verification (why not just anyone)

| Layer | What | Where |
|---|---|---|
| 1. OAuth login | `/authorize` shows a sign-in form unless a valid session cookie exists. Credentials live in `/etc/jisr-bridge/auth.env` (root-only, `0600`), compared constant-time. No login → no code → no token. | `server.py::_authorize` |
| 2. Bearer enforced | Every `/mcp` call without a live Bearer token gets **401**. Expired tokens are purged. | `server.py::_Gate` (`ENFORCE_BEARER=1`) |
| 3. Chain gate | Even authenticated callers can't write without a live `chain_id` (`waeyuk_start` → 10 stages). | `waeyuk_chain.py` |
| 4. Rate limits | `limit_req zone=gptmcp` on `/mcp`, `/register`, `/authorize`, `/token`. | nginx |
| 5. Separation | The public instance (`:8003`, enforced) is a **separate process** from the tunnel instance (`:8001`, unchanged auto-approve). Touching one never breaks the other. | `jisr-mcp-public.service` |

## Setup

```bash
# 1. credentials (once; user shares these with the second account owner)
mkdir -p /etc/jisr-bridge
printf 'BRIDGE_USER=admin\nBRIDGE_PASS=<random-20>\nBRIDGE_SESSION_SECRET=<random-40>\n' > /etc/jisr-bridge/auth.env
chmod 600 /etc/jisr-bridge/auth.env

# 2. public instance (port 8003, ENFORCE_BEARER=1) — see jisr-mcp-public.service
sudo cp jisr-mcp-public.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now jisr-mcp-public.service

# 3. nginx: proxy /mcp + OAuth paths to :8003 (tunnel keeps :8001 directly)
#    locations: /mcp, /.well-known/, /oauth/, =/register, =/authorize, =/token
sudo nginx -t && sudo systemctl reload nginx
```

## Test (no client needed)

```bash
# login wrong -> 403
curl -s -o /dev/null -w "%{http_code}\n" -X POST \
  "https://<DOMAIN>/authorize?redirect_uri=http://cb&client_id=x" \
  --data-urlencode "username=admin" --data-urlencode "password=wrong"
# MCP without token -> 401
curl -s -o /dev/null -w "%{http_code}\n" -X POST https://<DOMAIN>/mcp \
  -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1}'
```

## Rotating credentials

Change `BRIDGE_PASS` in `/etc/jisr-bridge/auth.env`, `systemctl restart
jisr-mcp-public` — old sessions/cookies stop working immediately (HMAC secret
unchanged keeps existing sessions valid; rotate `BRIDGE_SESSION_SECRET` too to
kill them all).
