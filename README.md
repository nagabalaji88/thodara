# Thodara

**Keep every order moving.**

Thodara is a hosted, India-first manufacturing ERP concept for manufacturing businesses. Its shared core connects customer demand with planning, purchasing, internal and outsourced production, inventory, quality and dispatch. The product promise is a trustworthy operating picture: what is confirmed, what is at risk, what is unknown, and who needs to act next.

## Product plan

The complete product, security, architecture and implementation plan is in [`docs/manufacturing-erp-product-plan.md`](docs/manufacturing-erp-product-plan.md). It is the source of truth for confirmed decisions, open questions, scope gates, role permissions, data integrity, release phases and LLM-assisted implementation rules.

## Design preview

Open [`prototype/index.html`](prototype/index.html) directly in a browser. It is a self-contained, responsive click-through preview and needs no build or install step.

The preview includes the public landing page, login, account creation, password reset, company setup, daily work list, order-risk board, sales order list/detail, planning and production, procurement and supplier progress, inventory and traceability, quality, dispatch, master data, approvals, reports, administration, a finance scope gate, and the supplier's mobile update view.

## Prototype status

This repository currently holds product requirements and a design prototype. The prototype uses clearly illustrative demo data; its sign-in, forms, buttons, permissions, calculations, integrations and notifications are not connected to a production backend. It must not be used with real customer or supplier data.

## Development direction

Build in bounded, testable phases. Start with the secure SaaS foundation, tenant/site scoping, identity, authorization and onboarding, then master data/imports and the order-to-dispatch workflow. Keep finance/statutory functionality behind the decisions and qualified review described in the product plan. Review the plan and repository instructions before asking an LLM to implement a story.
