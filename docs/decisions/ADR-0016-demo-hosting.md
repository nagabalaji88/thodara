# ADR-0016: Zero-budget demo hosting

- **Status:** Accepted (product owner, 2026-11-02). Option A implemented in slice D1; option B follows in D2.
- **Date:** 2026-11-02

## Context

D4 (production hosting) is still open. Thodara needs to be shown to prospects now, at no cost, without real data. This decision covers **demos with fictional data only**. It does not decide D4, and it is not a pilot environment.

## Decision (product owner, 2026-11-02)

**Both, in order:**

- **A. A computer we own plus a free Cloudflare quick tunnel.** For demos a presenter runs: no account, card or domain. The link changes on every start, and the computer must stay on.
- **B. The Oracle Cloud Always Free virtual machine in an Indian region.** An always-on demo with a fixed link for prospects to try on their own. Sign-up needs a card for verification. Free capacity can be scarce. Oracle may reclaim an idle free instance.

Rejected for demos:

- **Free platform tiers (for example Render).** The free database is deleted after 30 days (plus a 14-day grace period), and the app sleeps after 15 minutes idle, taking about a minute to wake.
- **Splitting the screens and the API across different free hosts.** It breaks the same-site sign-in cookies.

## Rules

- **Environment `demo`.**
  - Secure cookies and a private `THODARA_TWO_STEP_KEY` are required; the server refuses to start without them.
  - API docs are hidden.
  - Every change request must carry an origin.
  - The production checks are not applied, because the tunnel needs `localhost` for the health check.
- **Origins.** A change request is accepted from the listed origins, or from the site's own address: the `Origin` host equals the request's `Host`. The host itself is restricted separately by the allowed hosts, here `*.trycloudflare.com`. A foreign origin is refused.
- **Visitor address.** nginx takes the visitor's address from `CF-Connecting-IP`, trusted only from private networks (the tunnel and Docker). The login limit therefore counts each visitor separately, not the whole tunnel as one.
- **Separate from a trial install.** The demo runs as Docker project `thodara-demo`, with its own database volume, and no database or API port on the computer. Locally it is at `http://localhost:8090`.
- **Fictional data.**
  - `thodara-api seed-demo [--reset]` (development and demo environments only) loads "Srimant Auto Parts (DEMO)" through the API, so it passes the same rules, permissions and audit trail:
    - seven people, one per main role;
    - four customer orders, three outsourced batches;
    - a supplier update of 120 / 20 / 60;
    - a receipt of 100, of which 95 are accepted and 5 held.
  - Without `--reset` it refuses to touch a database that has data. Each load creates new random passwords, written only to `demo-accounts.txt` on the host computer.
  - Every page shows a "Demo, fictional data" banner, read from the public `GET /api/v1/meta`.
- **Backups.** `scripts/demo.sh backup` writes a database dump to `backups/`. Demo data can be loaded again at any time, so backups are a convenience here, not a recovery promise (D9 stays open).

## Consequences

- People and passwords are created directly by the seed, because invitations wait on D3.
- The owner and administrator demo accounts start the 7-day two-step grace period (ADR-0015) when the seed signs in. Resetting the demo restarts it. Prospects should be given the non-administrator accounts.
- The quick tunnel has no uptime promise and allows 200 requests at once. It is for presenting, not for anything people rely on.
- Real customer data still waits for D4 (hosting) and D9 (recovery targets).
