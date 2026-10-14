# Nexus security audit — 2026-10-15

**Method:** white-box code review of the whole app (backend + frontend), working through each
vulnerability class in the app-security skill set (OWASP web/API Top 10, auth, SSRF, injection,
XSS, CSRF, secrets, file handling, LLM/prompt-injection). This is a code review, not a live
penetration test — findings are reasoned from the source, and each fix ships with a test.

**Result:** 2 real vulnerabilities found and fixed, both denial-of-service on shared worker
processes in the multi-tenant deployment. No authentication bypass, privilege escalation, data
leak between tenants, injection, or SSRF was found — those areas were hardened in the earlier
security and multi-user work and held up. Suite: 506 backend / 155 frontend / 10 e2e, all green.

---

## Findings fixed

### 1. XML entity-expansion DoS in RSS/Atom feeds (medium)

- **Where:** [rss.py](../backend/app/integrations/rss.py) — `parse()` fed attacker-controlled feed
  XML to stdlib `xml.etree.ElementTree.fromstring`, which the Python docs explicitly call unsafe on
  hostile input (it expands internal entities).
- **Impact:** a user adds a public RSS feed they control; the **shared polling worker** fetches and
  parses it on a schedule. A "billion laughs" payload (a few hundred bytes declaring nested entities)
  expands to gigabytes in memory and OOMs the worker — stopping scheduled checks for *every* tenant.
  Not XXE: stdlib expat does not resolve external entities, so no file read / SSRF.
- **Fix:** reject any feed containing `<!DOCTYPE` or `<!ENTITY` before parsing. Legitimate feeds
  never declare these. Test: `test_rss_feed_with_entity_expansion_is_refused`.

### 2. Decompression-bomb DoS in document ingest (medium)

- **Where:** [loaders.py](../backend/app/rag/loaders.py) — `detect_kind()` and the docx/xlsx loaders
  read zip members (`[Content_Types].xml`, `word/document.xml`, sheets) with no decompressed-size
  bound. A 25 MB upload (the input cap) can be a zip whose members expand to many gigabytes.
- **Impact:** one tenant's upload OOMs the **shared RAG ingest worker**, which runs in the same
  process as the API, scheduler and bots — degrading or killing the service for everyone.
- **Fix:** `_guard_zip()` reads the zip's declared uncompressed total before any member is read and
  refuses files that expand past 1 GB or at a > 200:1 ratio (real Office files are ~5–30:1). Backed by
  a 2 GB container memory limit in `docker-compose.yml` so a forged-header or PDF-stream bomb takes
  down only the auto-restarting container, not the host. Test:
  `test_rejects_zip_bomb_before_decompressing_it`.

---

## Verified safe (areas reviewed, no change needed)

- **SQL injection:** every query is parameterized; the f-string queries interpolate only
  code-controlled identifiers (table names from fixed lists, `?`/`%s` placeholder marks, and
  UPDATE column names from server-built dicts — never raw request keys). The PostgreSQL layer
  (`pg.py`) parameterizes identically.
- **Authentication:** scrypt password hashing; `hmac.compare_digest` for password and all token
  checks; a dummy hash on unknown-user login so timing doesn't reveal which emails exist; 256-bit
  session tokens stored only as SHA-256; email/verify/reset tokens are high-entropy, hashed,
  single-use, purpose-scoped and expiring.
- **Authorization / multi-tenancy:** self-service edits use strict Pydantic models (a user cannot
  set `is_admin` on themselves); admin routes are behind the signed-in middleware *and*
  `require_admin`; an admin cannot disable or demote their own account (so ≥1 admin always remains);
  session delete and data export are scoped to the caller's `user_id`. Everything under `/api/auth`
  is middleware-exempt but every route re-checks the session itself (export included).
- **SSRF:** non-admin requests to feeds, workflow HTTP steps, MCP server URLs, LLM base URLs, the web
  reader and the built-in browser are restricted to public addresses (private/loopback/link-local/
  cloud-metadata blocked); feeds and HTTP steps re-check on every redirect. Admins may reach their own
  network (e.g. local Ollama) by design.
- **XSS:** React escapes by default; the one HTML surface (file preview) renders in
  `<iframe sandbox="" srcDoc>` with scripts and same-origin fully disabled; file downloads force
  `Content-Disposition: attachment` for everything except PDFs/images; the served app carries a
  `script-src 'self'` CSP and the built bundle has no inline scripts.
- **CSRF:** `SameSite=Lax` HttpOnly cookies plus an Origin / `Sec-Fetch-Site` check on all unsafe
  methods — two independent layers. DNS-rebinding is blocked by a host allowlist (421).
- **Webhooks:** GitHub/Slack/Notion HMAC signatures and the generic token all use constant-time
  compare; Slack enforces a timestamp replay window; wrong-token and wrong-workflow return an
  identical 403 so IDs can't be probed; 1 MB body cap.
- **Google OAuth:** 192-bit single-use, 10-minute state (CSRF); the post-login redirect target is
  server-configured, not a request parameter (no open redirect); an existing email is only linked
  when Google reports it verified (no account takeover).
- **Secrets:** API keys and MCP/integration configs are Fernet-encrypted at rest; `public()` and the
  admin user list never expose the password hash; the whole-DB backup is admin-and-local-only and
  disabled on PostgreSQL.
- **Code step:** user JavaScript runs in an isolated QuickJS interpreter (no require/fetch/filesystem)
  with time and memory limits; the input is JSON-encoded so it can't break out of the call.
- **Prompt injection / exfiltration:** tools that take a URL require user approval when the model
  *built* the address rather than it appearing verbatim in the chat or a tool result — the data-
  exfiltration-via-crafted-link pattern. Destructive tools default to an "ask" approval policy.

---

## Residual risks (accepted / noted, not fixed)

- **PDF decompression bombs** (pypdf) and **forged-size zips** aren't bounded in-process; the 2 GB
  container memory limit is the backstop. A per-worker memory cap would be stronger.
- **Signup email enumeration:** signup returns 409 for an existing email (standard UX). Forgot-password
  already returns 204 regardless, so that path doesn't enumerate.
- **URL re-validation (TOCTOU):** MCP/LLM URLs are checked for being public when saved; a domain whose
  DNS later resolves to a private address could slip through on use. Feeds and HTTP steps re-check live.
- **OAuth state is in-process:** fine for the single-process deployment; would need shared storage if
  Nexus is ever run with multiple worker processes.
- **Soft storage quota:** concurrent uploads can race past the limit slightly (bounded overrun, not a
  breach).
