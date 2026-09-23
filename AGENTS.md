# Instructions for coding agents

Before changing this repository, read `docs/manufacturing-erp-product-plan.md`, `docs/design-preview.md`, and the current module code.

- Implement one bounded story or release slice at a time; do not generate the ERP in one pass.
- Preserve the product direction: hosted, India-first, broad manufacturing ERP with a configurable shared core and an order-to-dispatch promise.
- Do not silently decide open product, finance, tax, identity-provider, cloud, pricing, or manufacturing-model questions. Record decisions in an ADR or ask the product owner when they block the current story.
- Treat `prototype/index.html` as a design reference with fictional data, not production behavior or an authorization model.
- Enforce tenant, site and supplier resource scope on the server. Default to deny. Never rely on frontend hiding for access control.
- Use decimal arithmetic and explicit units for quantities; preserve event source, actor, timestamp and amendment history.
- Keep supplier-reported, physically received and inspection-accepted quantities distinct. Keep missing/stale status separate from confirmed delay.
- Require authorized human approval for quality, commercial, supplier-change and other consequential state transitions.
- Use deterministic rules for authorization, quantities, approvals and date/dependency calculations. AI suggestions remain drafts until a user confirms them.
- Include migrations, meaningful business and authorization tests, error handling, audit events and relevant documentation with each implementation story.
- Report exactly which checks were run and any remaining gaps. Do not describe mocks or demo data as production-ready.
