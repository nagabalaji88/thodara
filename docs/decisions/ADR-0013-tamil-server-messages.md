# ADR-0013: Server messages in the user's language

- **Status:** Accepted. Implemented in slice G5 (follows ADR-0012, product owner decision of 2026-10-30). Tamil wording is a **draft awaiting native review**.
- **Date:** 2026-10-31

## Context

G4 translated screen text; text written by the server stayed English. That covers error messages, request-validation messages, delivery-risk explanations and notes, recovery suggestions, report definitions and labels, calendar reasons and import problems.

## Decision

- The screen sends `Accept-Language` with every request: `ta-IN` in Tamil, `en-IN` in English. A request middleware sets the language for that request; anything other than Tamil is English. The user's saved language (ADR-0012) decides what the screen sends.
- Messages are written as `tr("English text with {named} values", named=...)`. English is the key; `app/core/ta.py` holds the Tamil. `N_()` marks text kept in constants and translated where it is returned.
- Request-validation (422) messages are translated by error type, and so are the field names people see.
- `tests/test_i18n_catalogue.py` fails when a message has no Tamil, when an entry is no longer used, or when placeholders differ between English and Tamil. It runs in CI with the rest of the suite.
- **Stored records and audit details stay English.** Anything saved (audit events, history, reasons people type) is not translated, so the record does not depend on who looked at it. Text a person copies into a record, such as a suggestion they turn into an action title, is kept as they saw it.
- Values inside messages (quantities, codes, dates in ISO form) are not translated. Names, notes and blocker text typed by people stay as typed.

## Consequences

- New server messages must use `tr()` or `N_()` and add Tamil, or the test fails.
- The Tamil needs the same native review as the screen text before the pilot.
- A non-Thodara API client gets English unless it sends `Accept-Language: ta`.
