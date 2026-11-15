# Code review: security and deployment readiness (2026-11-15)

Scope: the whole repository at `main` (132f842): backend (about 15,000 lines), frontend (about 4,900 lines), Docker and Compose files, nginx and Caddy configuration, scripts and CI.

## Verdict

- **Demo hosting (fictional data): ready**, with the fixes in this change. Two parts remain untested from the development sandbox: the Windows `.bat` files, and the first run on a real Oracle server (DuckDNS, Let's Encrypt).
- **Production (real customer data): not ready.** No security hole blocks it, but the operational pieces listed under "Blocks production" do not exist yet. They wait on decision D4.

## How it was checked

- Read the sign-in, session, two-step, role and tenant-scope code in full; read the loaders and commit paths of every business module.
- Listed every database query without a company filter and traced where its key comes from.
- Inspected the running app's route table: 112 routes, each checked for sign-in, a permission, and CSRF protection on changes.
- Ran `pip-audit` and `npm audit` on the locked dependencies.
- Reproduced the two race conditions below against PostgreSQL before fixing them.
- Searched the screens for unsafe HTML, and the server for raw SQL, shell calls and committed secrets.

## What is sound

- **Company and site scope.** Every record is loaded with the company filter and the site check, and returns 404 otherwise. Child rows are reached only through a parent that passed that check. No query takes an unchecked id from the request.
- **Routes.** Only `/health/*`, `/api/v1/meta` and `/auth/login` are open. Every other route requires a signed-in session, and every change requires the CSRF token. Business routes require a named permission, read from the company's roles on each request.
- **Sessions.** Tokens are random, stored only as hashes, in `HttpOnly`, `SameSite=Lax` cookies (`Secure` outside development). Sign-in gives a new session. A password alone gives a 15-minute session that reaches nothing but two-step sign-in.
- **Passwords.** Argon2. An unknown email takes the same time and gets the same answer as a wrong password.
- **Concurrent edits.** Editable records carry a version; a stale save gets "reload and try again". Stock cannot go negative (checked in code and by a database constraint). Document numbers are allocated under a row lock.
- **Input limits.** Lists are capped (200 or 500 rows), imports at 2,000 rows and 500 KB, search text is escaped.
- **Screens.** No raw HTML insertion; a strict Content-Security-Policy; nothing sensitive in browser storage.
- **Secrets.** None committed. `.env`, `demo-accounts.txt` and `backups/` are ignored by git.

## Found and fixed in this change

| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | High | **Two-step limits could be dodged with parallel requests.** Reproduced on PostgreSQL: 40 wrong codes sent at once all answered "wrong" and the counter ended at 1, so the 5-try lock never applied; one valid code was accepted by six sign-ins at once. Someone who already had the password could guess codes without limit. | The user row is locked while a code is checked (`two_step_api.active_user`). New PostgreSQL test; it fails without the fix. |
| 2 | Medium | **Outdated libraries with published advisories**: `cryptography` 46.0.7, `certifi`, `dnspython`; `vite` and `source-map-js` (build tools). None is reachable the way Thodara uses them (only AES-GCM; no certificate or DNS parsing; `vite` is not in the built app). | Upgraded (`cryptography` 50.0.2, `certifi` 2026.10.23, `dnspython` 2.9.2, `vite` 8.3.8). Both audits now report nothing. |
| 3 | Medium | **`staging` ran with development rules**: insecure cookies allowed, the public development two-step key allowed, no origin required. | `staging` now needs secure cookies, a private key and an origin on every change, like `demo`. |
| 4 | Low | The "same host" origin rule accepted `http://` for a site whose cookies are HTTPS-only. | Only `https://` counts when cookies are `Secure`. |
| 5 | Low | **Container logs grew without limit**, which would eventually fill the disk of the always-on server. | Log rotation (5 × 10 MB) on every service. |
| 6 | Low | Two batch imports at the same moment could end in an error page (unhandled conflict). | The second now gets "reload and try again". |
| 7 | Low (usability) | When a session ended (8 hours, signed out elsewhere, two-step reset), the screens kept showing errors until the page was reloaded. | The person is returned to sign-in with "Your session has ended". |

## Open: needs a product decision

| # | Severity | Finding | Options |
|---|---|---|---|
| A | Medium | **The password lock does not stop guessing.** After 5 wrong passwords the account is "locked" for 15 minutes, but a correct password still signs in (`test_lockout_does_not_extend_and_valid_password_still_works`). So the lock only affects wrong guesses, which fail anyway. The only real brake is nginx's limit of 10 sign-in tries per minute per visitor address. This was deliberate, so that an attacker cannot lock the real owner out. | (1) Refuse even the correct password while locked: the usual rule, but an attacker can keep someone locked out. (2) Keep as is, and add a per-account slowdown that applies to every attempt. (3) Keep as is, since two-step sign-in protects owners and administrators. |
| B | Medium | **Someone with "manage members" can give a colleague a stronger role than their own**, including Owner (which has every permission). They cannot change their own role, but two people could raise each other. With the standard roles only owners and administrators hold this permission; the risk appears when a company grants it to a custom role. | Allow assigning only roles whose permissions the assigner already holds (administrators exempt). |
| C | Low | An administrator of one company can reset two-step sign-in for a person who also belongs to another company (already noted in ADR-0015). | Revisit before self-service sign-up. |

## Blocks production (waits on D4 and related decisions)

1. **No production deployment definition.** `compose.yaml` runs the API in `development` mode; only demo overrides exist. There is no production Compose file, secret handling or TLS set-up.
2. **No way to create the first company and owner outside development.** `provision-owner` refuses to run elsewhere, and invitations do not exist (D3).
3. **No password change or reset.** A leaked password cannot be changed by its owner (D3 email provider).
4. **Backups stay on the same machine**, are not encrypted, and no restore has been rehearsed (D9).
5. **No monitoring, alerting or error reporting.** A failure would be noticed only by users.
6. **One API process, no automatic clean-up** of expired sessions; audit history grows without archiving.
7. **Dependency audits are not part of CI.** They were run by hand for this review.

## Smaller notes (no action taken)

- `uvicorn --proxy-headers` has no effect behind nginx in Docker (the proxy's address is not trusted). Nothing depends on it today, because the audit trail does not record addresses.
- nginx trusts `CF-Connecting-IP` from private networks. That is right behind the tunnel and Caddy. A production proxy must set or strip that header the same way.
- Base images are pinned by version tag, not by digest; GitHub Actions by major version.
- Delivery risk and reports are computed on every read. Fine at pilot size; needs measuring before large companies.
- `scripts/oracle-setup.sh` takes the DuckDNS token as an argument, so it lands in shell history on the server.
