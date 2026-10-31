# ADR-0012: English and Tamil on every screen

- **Status:** Accepted (product owner, 2026-10-30). Implemented in slice G4. Tamil wording is a **draft awaiting native review**.
- **Date:** 2026-10-30

## Context

ADR-0009 (D6) decided English and Tamil on every screen. This slice adds a per-user language and translates the screens. Text written by the server (validation messages, delivery-risk explanations, suggestions, report definitions, permission labels sent by the API) is a separate body of work.

## Decisions (product owner, 2026-10-30)

| Question | Decision |
|---|---|
| Scope of G4 | **All screen text now; server messages in a later slice (G5).** |
| Who writes the Tamil | **The development team drafts it; the pilot companies' team reviews it** before the pilot. Corrections are made in one file without touching code. |
| Numbers and dates | **0–9 digits with Indian grouping; Tamil month and day names** (locale `ta-IN-u-nu-latn`). |

## Rules

- Each user has a language (`en` or `ta`, default `en`) stored on the user and returned with the session. They change it from the account menu, or on the sign-in page before signing in (that choice is saved to their profile when they sign in). Changes are audited (`auth.language_changed`).
- English text is the translation key. `t()` shows the user's language and falls back to English; `tk()` marks phrases kept in label maps. Placeholders `{0}`, `{1}` carry values so that a whole sentence is one phrase, which Tamil word order needs.
- `frontend/src/ta.ts` holds every Tamil phrase. `scripts/check-i18n.mjs` runs before every build (and so in CI): a phrase on screen without a Tamil entry, or a stale entry, fails the build.
- Data stays as entered: names, codes, references, notes and reasons typed by users are never translated.
- Server-written text stays English until G5, including the permission catalogue labels, which the screen translates from a fixed list.

## Consequences

- G5 translates server messages on the server, using the language the screen sends (ADR-0013).
- Review of the Tamil draft is a pilot prerequisite. Some short fragments that sit next to values (for example "Keep every … order moving.") read less naturally than whole sentences; the reviewer should flag any that need rewording in code.
- Adding a third language needs only another catalogue file and an entry in `LANGUAGES`.
