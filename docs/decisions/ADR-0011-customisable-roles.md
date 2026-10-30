# ADR-0011: Company-customisable roles

- **Status:** Accepted (product owner, 2026-10-30). Implemented in slice G3.
- **Date:** 2026-10-30

## Context

ADR-0009 decided that companies can customise roles before the pilot, with the fixed role map of ADR-0003 becoming the default template. Permissions are checked on the server for every request; the screen only hides what a user cannot do.

## Decisions (product owner, 2026-10-30)

| Question | Decision |
|---|---|
| Who may change roles | **Owners and administrators** (the `roles:manage` permission). |
| What companies can do | **Change the standard roles and add new named roles.** The standard set stays as the default template; a changed standard role can be reset to it. |
| Fixed safeguard | **Administrator is the locked top role.** It always has every permission and cannot be edited, so a company can never lock itself out. The owner role is editable like the others. |
| Self-approval | **Blocked by default; a company may allow it.** When allowed, whoever entered or requested something may also approve it, and the audit log marks it as self-approved. |

## Rules

- A role is a key, a name, an optional description and a set of permissions chosen from a fixed catalogue. Unknown permissions are refused.
- Standard roles keep their keys. Editing one stores the company's version; resetting deletes it and the default applies again. Standard roles cannot be deleted.
- Custom roles get a key derived from their name. They can be deleted only when no member holds them.
- Changing roles never removes the last way to manage roles: a change is refused if no active member would still hold `roles:manage` (administrators always do).
- Only an administrator can make someone an administrator or change an administrator's role. While a company has no active administrator, an owner may appoint the first one.
- A member's role can be changed by anyone with `users:manage`, except to or from administrator (above), and nobody can change their own role.
- Owners and administrators always see every site (unchanged). Every other role, standard or custom, is limited to the member's sites.
- Every change (role created, changed, reset or deleted; a member's role changed; the self-approval setting) is audited with before and after values.
- Permissions are read from the database on each request, so a change applies at once to signed-in users.
- Inviting new users still waits on D3 (identity and email provider).

## Consequences

- Approval limits (D8) can later attach to roles.
- Moving away from the fixed map makes the permission catalogue the contract: new permissions must be added to it with a label and given to the right default roles.
