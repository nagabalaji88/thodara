# ADR-0017: Per-account login slowdown and role-grant limits

- **Status:** Accepted (product owner, 2026-11-15). Implemented after the security review (`docs/code-review-2026-11-15.md`, findings A and B).
- **Date:** 2026-11-15

## Context

The review found two gaps:

- **A.** After five wrong passwords an account was "locked" for 15 minutes, but a correct password still signed in. So the lock did not slow guessing. The only brake was nginx's 10 tries a minute per visitor address.
- **B.** Anyone with "manage members" or "manage roles" could give a colleague, or a role, permissions they did not hold themselves, up to Owner.

## Decisions

**A. Slow every try (product owner's choice).**

- After **5** wrong passwords in a row (`login_lockout_attempts`), the account takes **one attempt per 30 seconds** (`login_throttle_seconds`), right or wrong, until a correct sign-in.
  - During the pause the password is not checked. The answer is 429 "Too many login attempts", the same wording as the per-visitor limit, so it says nothing more about the account.
  - Every further wrong try starts a new pause. A correct password after a pause signs in and clears the count.
- Effect: at most about 2,900 guesses a day per account, from any number of addresses. The real owner waits at most 30 seconds, and cannot be locked out for longer.
- Rejected alternatives:
  - A hard 15-minute lock: anyone knowing an email could keep that person out.
  - Keeping things as they were.
- Two-step sign-in (ADR-0015) keeps its own pause: 5 wrong codes stop code entry for 15 minutes.

**B. Only hand out what you hold.** For everyone except an administrator:

- A member's role can be changed only if both the new role and the current role have no permission the changer lacks. So nobody can raise anyone above themselves, or demote someone stronger.
- A new role, or the permissions a changed role gains, must be within the changer's own. Taking permissions away is always allowed.
- Resetting a standard role to its template counts as granting whatever the template adds back.
- Owners hold every permission, so in practice this limits custom roles that were given "manage members" or "manage roles". The existing rules stay: only administrators appoint administrators, and nobody changes their own role.

## Consequences

- The old rule "a valid password works during the lock" is replaced; its test now checks the slowdown.
- Wrong-password audit events record whether the account is now paused.
