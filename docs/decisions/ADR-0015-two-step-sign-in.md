# ADR-0015: Two-step sign-in with an authenticator app

- **Status:** Accepted (product owner, 2026-11-01). Implemented in slice G7.
- **Date:** 2026-11-01

## Context

Decision D3 (ADR-0009) requires two-step verification for owners and administrators, using a free authenticator app (TOTP), with nothing sent by SMS or email. This slice implements it for the existing email + password sign-in. Google / Microsoft sign-in, invitations and password reset are not part of it.

## Decisions (product owner, 2026-11-01)

| Question | Decision |
|---|---|
| Lost phone | **Backup codes plus administrator reset.** Ten one-time backup codes at set-up. If they are lost too, another administrator resets the person's two-step sign-in. |
| Existing owners and administrators | **7-day grace period** from the first sign-in where it applies, with a reminder. After that they must set it up before continuing. |
| How often | **A code at every password sign-in.** No "trust this device". |
| Who | **Required for owners and administrators; optional for everyone else.** |

## Rules

- **Codes.** RFC 6238 TOTP: HMAC-SHA1, 30-second steps, 6 digits, one step of clock drift either way. Each code is accepted once: the last accepted time step is stored.
- **Secrets.** Authenticator secrets are encrypted with AES-GCM under `THODARA_TWO_STEP_KEY` (32 bytes, base64), bound to the user id. Production refuses to start with the public development key. Backup codes (10 characters, no look-alike letters) are stored only as HMAC-SHA256 hashes under the same key.
- **Sign-in stages.** A correct password gives a session that reaches nothing but the two-step endpoints, `GET /auth/session` and sign-out:
  - `verify` when two-step is on;
  - `enrol` for an owner or administrator past the grace period or after a reset;
  - otherwise `full`.

  A partial session lasts 15 minutes and lists no companies. Success replaces it with a new full session (new token and CSRF token) rather than upgrading it. Only `full` sessions pass the normal authentication dependency (default deny).
- **Wrong codes.** Counted separately from wrong passwords. Five wrong codes end that sign-in attempt and pause code entry for that account for 15 minutes (`login_lockout_minutes`). A correct password does not lift the pause. Failed attempts are audited as anonymous.
- **Required.** Applies when the person is an active owner or administrator of any active company. The grace deadline is stored once and does not restart. Owners and administrators cannot turn it off.
- **Backup codes.** Shown once at set-up. New ones need a code from the authenticator, and replace all old ones. A backup code can be used to sign in, or by someone for whom it is optional to turn it off.
- **Administrator reset.** `POST /organization/members/{id}/reset-two-step`. Only the administrator role (not owner), only for members of the same company, never oneself. It removes the authenticator and backup codes and ends all of the person's sessions. Owners and administrators must set it up again at their next sign-in (no new grace period). Audited as `organization.member.two_step_reset`.
- **Support reset.** For a company whose only administrator is locked out, `thodara-api reset-two-step --email … --reason …` does the same from the server. It is audited as `support.two_step_reset` (actor `system`, channel `cli`) with the reason, in every company the person belongs to.
- **Audit.** Events: `auth.password_accepted`, `auth.login_succeeded` (with the method: `authenticator`, `backup_code` or `enrolled`), `auth.two_step_failed`, `auth.two_step_enabled`, `auth.two_step_disabled`, `auth.backup_code_used` and `auth.backup_codes_replaced`.

## Consequences

- The key must be kept with the other production secrets once hosting is decided (D4). Changing it makes existing secrets unreadable: everyone would need a reset. Key rotation is not built.
- The two-step identity is per person, not per company, so an administrator's reset affects that person in every company they belong to. This is acceptable while companies are onboarded by Thodara staff (D1). It should be revisited before self-service sign-up.
- Google / Microsoft sign-in (D3) will need its own rule for whether the provider's own two-step counts. That is not decided here.
