import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, Check, LoaderCircle, Plus, X } from "lucide-react";
import { api, type ApiError } from "./api";
import { fmtDate } from "./orders";

export type ActionKind = "chase_update" | "collect" | "expedite" | "overtime" | "resequence" | "rework" | "alternate_supplier" | "promise_review" | "other";
export interface ActionEvent { kind: string; note: string | null; details: Record<string, unknown> | null; actor_label: string | null; created_at: string }
export interface RiskSnapshot { headline: string; projected_date?: string | null; promised_date?: string | null; issues?: string[]; computed_at: string }
export interface Action {
  id: string; kind: ActionKind; title: string; details: string | null; status: "awaiting_approval" | "open" | "done" | "rejected" | "cancelled";
  requires_approval: boolean; site_id: string;
  line: { line_id: string; order_id: string; order_number: string; line_no: number; customer_name: string; item_code: string } | null;
  batch: { batch_id: string; number: string; supplier_name: string } | null;
  owner_id: string; owner_label: string; due_at: string; overdue: boolean; created_by_label: string | null; created_at: string;
  approved_at: string | null; acknowledged_at: string | null; supplier_acknowledged_at: string | null;
  outcome: string | null; outcome_note: string | null; closed_at: string | null;
  risk_before: RiskSnapshot | null; risk_after: RiskSnapshot | null; version: number; is_mine: boolean; can_approve: boolean; events: ActionEvent[];
}
export interface ActionPage { items: Action[]; total: number; counts: { open: number; awaiting_approval: number; overdue: number; mine: number; to_approve: number } }
export interface Suggestion { kind: ActionKind; title: string; details: string; line_id: string; batch_id: string | null; requires_approval: boolean }

export const KINDS: [ActionKind, string][] = [
  ["chase_update", "Chase an update"], ["collect", "Collect from supplier"], ["expedite", "Expedite"], ["overtime", "Overtime"],
  ["resequence", "Resequence work"], ["rework", "Rework"], ["alternate_supplier", "Alternate supplier"], ["promise_review", "Review the promise"], ["other", "Other"],
];
const KIND_LABEL = Object.fromEntries(KINDS) as Record<string, string>;
const APPROVAL: ActionKind[] = ["rework", "alternate_supplier", "promise_review"];
const STATUS: Record<string, string> = { awaiting_approval: "Needs approval", open: "Open", done: "Done", rejected: "Rejected", cancelled: "Cancelled" };
const OUTCOME: Record<string, string> = { resolved: "Resolved", partly_resolved: "Partly resolved", not_resolved: "Not resolved" };
const when = (iso: string) => new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const person = (label: string | null) => label?.split(" <")[0] ?? "Unknown user";
const newKey = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`);
const toLocal = (d: Date) => { const x = new Date(d); x.setMinutes(x.getMinutes() - x.getTimezoneOffset()); return x.toISOString().slice(0, 16); };
const tomorrowNoon = () => { const d = new Date(); d.setDate(d.getDate() + 1); d.setHours(12, 0, 0, 0); return toLocal(d); };

export function ActionStatus({ a }: { a: Action }) {
  return <span className={`badge action-${a.overdue ? "overdue" : a.status}`}>{a.overdue ? "Overdue" : STATUS[a.status]}</span>;
}

function Subject({ a }: { a: Action }) {
  return <>{a.line && <a className="mono" href={`#orders/${a.line.order_id}`}>{a.line.order_number}/{a.line.line_no}</a>}{a.line && a.batch && " · "}{a.batch && <a className="mono" href={`#outsourcing/${a.batch.batch_id}`}>{a.batch.number}</a>}<small className="cell-sub">{a.line ? a.line.customer_name : a.batch?.supplier_name}</small></>;
}

export function ActionsPage({ sub, permissions }: { sub: string; permissions: string[] }) {
  if (sub) return <ActionView id={sub} canManage={permissions.includes("actions:manage")} />;
  return <ActionList canApproveDispatch={permissions.includes("dispatch:approve")} />;
}

/** Dispatch exceptions someone else requested; the panel only lists those this user may decide. */
function DispatchApprovals() {
  const pending = useQuery({ queryKey: ["dispatches", "pending"], queryFn: () => api<{ id: string; number: string; order_id: string; order_number: string; customer_name: string; dispatch_date: string; created_by_label: string | null; can_decide: boolean; lines: { line_no: number; quantity: string; unit_code: string; exception_reason: string | null }[] }[]>("/api/v1/dispatch?status=pending_approval"), staleTime: 0 });
  const mine = (pending.data ?? []).filter((n) => n.can_decide);
  if (mine.length === 0) return null;
  return <div className="panel data-panel">
    <h2 className="panel-title">Dispatch exceptions waiting for you</h2>
    <div className="table-wrap"><table className="data-table compact-table">
      <thead><tr><th scope="col">Dispatch</th><th scope="col">Order</th><th scope="col">Lines</th><th scope="col">Requested by</th></tr></thead>
      <tbody>{mine.map((n) => <tr key={n.id} tabIndex={0} onClick={() => { window.location.hash = `orders/${n.order_id}`; }} onKeyDown={(e) => { if (e.key === "Enter") window.location.hash = `orders/${n.order_id}`; }}>
        <td className="mono">{n.number}</td><td><span className="mono">{n.order_number}</span><small className="cell-sub">{n.customer_name}</small></td>
        <td>{n.lines.map((l) => `${l.quantity} ${l.unit_code} line ${l.line_no}${l.exception_reason ? ` — ${l.exception_reason}` : ""}`).join("; ")}</td>
        <td>{person(n.created_by_label)}</td>
      </tr>)}</tbody>
    </table></div>
    <p className="hint">Open the order to approve or reject. Nothing ships until someone other than the requester approves.</p>
  </div>;
}

type Filter = "mine" | "to_approve" | "overdue" | "active" | "closed";

function ActionList({ canApproveDispatch }: { canApproveDispatch: boolean }) {
  const [filter, setFilter] = useState<Filter>("active");
  const params = new URLSearchParams(filter === "mine" ? { mine: "true", status: "active" } : filter === "overdue" ? { overdue: "true" } : filter === "to_approve" ? { status: "awaiting_approval" } : { status: filter });
  const list = useQuery({ queryKey: ["actions", filter], queryFn: () => api<ActionPage>(`/api/v1/actions?${params}`), staleTime: 0 });
  const c = list.data?.counts;
  const items = (list.data?.items ?? []).filter((a) => filter !== "to_approve" || a.can_approve);
  const tabs: [Filter, string, number | undefined][] = [["active", "All open", c && c.open + c.awaiting_approval], ["mine", "Mine", c?.mine], ["overdue", "Overdue", c?.overdue], ["to_approve", "For my approval", c?.to_approve], ["closed", "Closed", undefined]];
  return <section className="wrap page">
    <header className="page-head"><div><span className="eyebrow">WHAT TO FIX TODAY</span><h1 className="page-title">Actions</h1></div><p className="lede small">Every recovery step with a named owner and a due time. Supplier changes, rework and promise reviews need someone else’s approval before they start.</p></header>
    <div className="panel data-panel">
      <div className="segmented" role="tablist">{tabs.map(([key, label, n]) => <button key={key} role="tab" aria-selected={filter === key} className={filter === key ? "on" : undefined} onClick={() => setFilter(key)}>{label}{n !== undefined && <b>{n}</b>}</button>)}</div>
      {list.isError ? <div className="form-error" role="alert"><AlertCircle size={15} />{list.error.message}</div>
        : list.isPending ? <div className="table-state"><LoaderCircle className="spin" size={16} /> Loading…</div>
          : items.length === 0 ? <div className="table-state">{filter === "active" ? "No open actions. Create one from an order’s delivery risk." : "Nothing here."}</div>
            : <div className="table-wrap"><table className="data-table">
              <thead><tr><th scope="col">Due</th><th scope="col">Action</th><th scope="col">For</th><th scope="col">Owner</th><th scope="col">Status</th></tr></thead>
              <tbody>{items.map((a) => <tr key={a.id} tabIndex={0} aria-label={`Open ${a.title}`} onClick={() => { window.location.hash = `actions/${a.id}`; }} onKeyDown={(e) => { if (e.key === "Enter") window.location.hash = `actions/${a.id}`; }}>
                <td className={`date ${a.overdue ? "late-text" : ""}`}>{when(a.due_at)}</td>
                <td><b>{a.title}</b><small className="cell-sub">{KIND_LABEL[a.kind]}</small></td>
                <td onClick={(e) => e.stopPropagation()}><Subject a={a} /></td>
                <td>{person(a.owner_label)}{a.is_mine && <small className="cell-sub">You</small>}</td>
                <td><ActionStatus a={a} />{a.outcome && <small className="cell-sub">{OUTCOME[a.outcome]}</small>}</td>
              </tr>)}</tbody>
            </table></div>}
    </div>
    {canApproveDispatch && <DispatchApprovals />}
  </section>;
}

type Step = "approve" | "reject" | "acknowledge" | "supplier" | "reassign" | "complete" | "cancel";

function ActionView({ id, canManage }: { id: string; canManage: boolean }) {
  const queryClient = useQueryClient();
  const action = useQuery({ queryKey: ["action", id], queryFn: () => api<Action>(`/api/v1/actions/${id}`), staleTime: 0 });
  const [step, setStep] = useState<Step | null>(null);
  if (action.isPending) return <section className="wrap page"><div className="table-state"><LoaderCircle className="spin" size={16} /> Loading…</div></section>;
  if (action.isError) return <section className="wrap page"><a className="back-link" href="#actions"><ArrowLeft size={15} /> Actions</a><div className="form-error" role="alert"><AlertCircle size={15} />{action.error.message}</div></section>;
  const a = action.data;
  const active = a.status === "open" || a.status === "awaiting_approval";
  const done = (value: Action) => { queryClient.setQueryData(["action", id], value); for (const k of ["actions", "order-actions"]) void queryClient.invalidateQueries({ queryKey: [k] }); setStep(null); };
  return <section className="wrap page">
    <a className="back-link" href="#actions"><ArrowLeft size={15} /> Actions</a>
    <header className="page-head order-head">
      <div><span className="eyebrow">{(KIND_LABEL[a.kind] ?? a.kind).toUpperCase()}{a.requires_approval ? " · NEEDS APPROVAL" : ""}</span><h1 className="page-title action-title">{a.title} <ActionStatus a={a} /></h1></div>
      <dl className="facts">
        <div><dt>Owner</dt><dd>{person(a.owner_label)}{a.acknowledged_at ? " ✓" : ""}</dd></div>
        <div><dt>Due</dt><dd className={a.overdue ? "late-text" : undefined}>{when(a.due_at)}</dd></div>
        <div><dt>For</dt><dd><Subject a={a} /></dd></div>
        <div><dt>Raised by</dt><dd>{person(a.created_by_label)}</dd></div>
      </dl>
    </header>
    {(a.can_approve || (canManage && active)) && <div className="action-bar">
      {a.can_approve && <><button className="primary-button compact" onClick={() => setStep("approve")}><Check size={15} /> Approve</button><button className="quiet-button danger" onClick={() => setStep("reject")}>Reject</button></>}
      {a.is_mine && a.status === "open" && !a.acknowledged_at && <button className="primary-button compact" onClick={() => setStep("acknowledge")}><Check size={15} /> I’m on it</button>}
      <span className="toolbar-spacer" />
      {canManage && active && <>
        {a.batch && a.status === "open" && <button className="quiet-button" onClick={() => setStep("supplier")}>Supplier acknowledged</button>}
        <button className="quiet-button" onClick={() => setStep("reassign")}>Reassign</button>
        {a.status === "open" && <button className="quiet-button" onClick={() => setStep("complete")}>Close with outcome</button>}
        <button className="quiet-button danger" onClick={() => setStep("cancel")}>Cancel</button>
      </>}
    </div>}
    {a.status === "awaiting_approval" && !a.can_approve && <div className="notice-line"><AlertCircle size={16} /><span>Waiting for approval by an owner, administrator or approver other than {person(a.created_by_label)}. It cannot be closed until then.</span></div>}
    {a.details && <div className="panel"><span className="field-label">What and why</span><p className="notes-text">{a.details}</p></div>}
    <div className="panel">
      <span className="eyebrow">DID IT WORK?</span>
      <div className="before-after">
        <Snapshot label="When raised" s={a.risk_before} />
        <Snapshot label={a.closed_at ? "When closed" : "When closed (not yet)"} s={a.risk_after} />
      </div>
      {a.outcome && <p className="provenance"><b>{OUTCOME[a.outcome]}.</b> {a.outcome_note}</p>}
    </div>
    <div className="panel">
      <span className="eyebrow">HISTORY</span>
      <ol className="timeline">{a.events.map((e, i) => <li key={i}><b>{e.kind.replace(/_/g, " ")}</b><span>{e.note ?? ""}{eventDetail(e)}</span><small>{person(e.actor_label)} · {when(e.created_at)}</small></li>)}</ol>
    </div>
    {step && <StepDialog step={step} action={a} onClose={() => setStep(null)} onDone={done} />}
  </section>;
}

function eventDetail(e: ActionEvent) {
  const d = e.details ?? {};
  if (d["contact_method"]) return ` · via ${String(d["contact_method"])}${d["contact_name"] ? ` with ${String(d["contact_name"])}` : ""} (entered by staff)`;
  const after = d["after"] as Record<string, string> | undefined;
  if (after?.["owner"]) return ` · now ${person(after["owner"])}`;
  return "";
}

function Snapshot({ label, s }: { label: string; s: RiskSnapshot | null }) {
  return <div className="snapshot"><small>{label}</small>{s ? <><b className={`badge risk-${s.headline}`}>{s.headline.replace(/_/g, " ")}</b>{s.projected_date && <span>Projected {fmtDate(s.projected_date)}{s.promised_date ? ` · promised ${fmtDate(s.promised_date)}` : ""}</span>}{s.issues?.[0] && <span className="cell-sub">{s.issues[0]}</span>}</> : <span className="muted-inline">—</span>}</div>;
}

function useAssignees(siteId: string) {
  return useQuery({ queryKey: ["assignees", siteId], queryFn: () => api<{ user_id: string; display_name: string; role: string }[]>(`/api/v1/actions/assignees?site_id=${siteId}`) });
}

function StepDialog({ step, action: a, onClose, onDone }: { step: Step; action: Action; onClose: () => void; onDone: (a: Action) => void }) {
  const [note, setNote] = useState("");
  const [outcome, setOutcome] = useState("resolved");
  const [owner, setOwner] = useState("");
  const [due, setDue] = useState("");
  const [method, setMethod] = useState("phone");
  const [contact, setContact] = useState("");
  const assignees = useAssignees(step === "reassign" ? a.site_id : "");
  useEffect(() => { const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); }; window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k); }, [onClose]);
  const submit = useMutation({
    mutationFn: () => {
      const base = `/api/v1/actions/${a.id}`;
      const send = (path: string, body: object) => api<Action>(`${base}/${path}`, { method: "POST", body: JSON.stringify({ version: a.version, ...body }) });
      switch (step) {
        case "approve": return send("approve", { note });
        case "reject": return send("reject", { reason: note });
        case "acknowledge": return send("acknowledge", { note });
        case "supplier": return send("supplier-acknowledgement", { contact_method: method, contact_name: contact, acknowledged_at: new Date().toISOString(), note });
        case "reassign": return send("reassign", { owner_id: owner, due_at: due ? new Date(due).toISOString() : null, reason: note });
        case "complete": return send("complete", { outcome, note });
        case "cancel": return send("cancel", { reason: note });
      }
    },
    onSuccess: onDone,
  });
  const titles: Record<Step, string> = { approve: "Approve this action", reject: "Reject this action", acknowledge: "Take ownership", supplier: "Supplier acknowledged", reassign: "Reassign", complete: "Close with an outcome", cancel: "Cancel this action" };
  const needsNote = step === "reject" || step === "reassign" || step === "complete" || step === "cancel";
  return <div className="dialog-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <form className="dialog" role="dialog" aria-modal="true" aria-labelledby="step-title" onSubmit={(e) => { e.preventDefault(); submit.mutate(); }}>
      <header><div><span className="eyebrow">{a.title}</span><h2 id="step-title">{titles[step]}</h2></div><button type="button" className="icon-button" onClick={onClose} aria-label="Close"><X size={16} /></button></header>
      <div className="dialog-grid">
        {step === "complete" && <label className="wide">Outcome<select value={outcome} onChange={(e) => setOutcome(e.target.value)}>{Object.entries(OUTCOME).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>}
        {step === "reassign" && <>
          <label>New owner<select value={owner} onChange={(e) => setOwner(e.target.value)} required><option value="" disabled>Choose a colleague</option>{(assignees.data ?? []).filter((x) => x.user_id !== a.owner_id).map((x) => <option key={x.user_id} value={x.user_id}>{x.display_name} · {x.role.replace(/_/g, " ")}</option>)}</select></label>
          <label>New due time <span className="optional">OPTIONAL</span><input type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} /></label>
        </>}
        {step === "supplier" && <>
          <label>How<select value={method} onChange={(e) => setMethod(e.target.value)}><option value="phone">Phone call</option><option value="whatsapp">WhatsApp</option><option value="email">Email</option><option value="visit">Site visit</option><option value="other">Other</option></select></label>
          <label>Who <span className="optional">OPTIONAL</span><input value={contact} onChange={(e) => setContact(e.target.value)} maxLength={120} /></label>
        </>}
        <label className="wide">{step === "complete" ? "What happened" : step === "approve" || step === "acknowledge" || step === "supplier" ? <>Note <span className="optional">OPTIONAL</span></> : "Reason"}<input value={note} onChange={(e) => setNote(e.target.value)} required={needsNote} minLength={needsNote ? 3 : undefined} maxLength={1000} autoFocus /></label>
        {step === "complete" && <p className="hint wide">Thodara records the line’s delivery risk now, next to the risk when the action was raised.{a.batch && (a.kind === "collect" || a.kind === "expedite") ? ` Closing does not move material: record what arrived as a receipt on ${a.batch.number} so the risk reflects it.` : ""}</p>}
        {step === "supplier" && <p className="hint wide">Saved as entered by you; the supplier has not confirmed it in Thodara.</p>}
      </div>
      {submit.error && <div className="form-error" role="alert"><AlertCircle size={15} /><span>{submit.error.message}{(submit.error as ApiError).status === 409 && " Reload to see the latest version."}</span></div>}
      <footer><span className="toolbar-spacer" /><button type="button" className="quiet-button" onClick={onClose}>Back</button><button type="submit" className={`primary-button compact ${step === "reject" || step === "cancel" ? "danger-fill" : ""}`} disabled={submit.isPending}>{submit.isPending ? <LoaderCircle className="spin" size={15} /> : <Check size={15} />} Save</button></footer>
    </form>
  </div>;
}

/** Create an action, optionally from a suggestion. */
export function NewActionDialog({ siteId, lineId, batchId, suggestion, onClose, onDone }: {
  siteId: string; lineId?: string; batchId?: string | null; suggestion?: Suggestion; onClose: () => void; onDone: (a: Action) => void;
}) {
  const assignees = useAssignees(siteId);
  const [kind, setKind] = useState<ActionKind>(suggestion?.kind ?? "chase_update");
  const [title, setTitle] = useState(suggestion?.title ?? "");
  const [details, setDetails] = useState(suggestion?.details ?? "");
  const [owner, setOwner] = useState("");
  const [due, setDue] = useState(tomorrowNoon());
  const key = useMemo(newKey, []);
  useEffect(() => { const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); }; window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k); }, [onClose]);
  const create = useMutation({
    mutationFn: () => api<Action>("/api/v1/actions", { method: "POST", body: JSON.stringify({ submission_key: key, kind, title, details, line_id: lineId ?? null, batch_id: suggestion ? suggestion.batch_id : batchId ?? null, owner_id: owner, due_at: new Date(due).toISOString() }) }),
    onSuccess: onDone,
  });
  return <div className="dialog-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <form className="dialog" role="dialog" aria-modal="true" aria-labelledby="new-action-title" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
      <header><div><span className="eyebrow">{suggestion ? "SUGGESTED FROM DELIVERY RISK" : "NEW ACTION"}</span><h2 id="new-action-title">Plan an action</h2></div><button type="button" className="icon-button" onClick={onClose} aria-label="Close"><X size={16} /></button></header>
      <div className="dialog-grid">
        <label>Kind<select value={kind} onChange={(e) => setKind(e.target.value as ActionKind)}>{KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
        <label>Owner<select value={owner} onChange={(e) => setOwner(e.target.value)} required><option value="" disabled>Choose who does it</option>{(assignees.data ?? []).map((x) => <option key={x.user_id} value={x.user_id}>{x.display_name} · {x.role.replace(/_/g, " ")}</option>)}</select></label>
        <label className="wide">What<input value={title} onChange={(e) => setTitle(e.target.value)} required minLength={3} maxLength={160} autoFocus={!suggestion} /></label>
        <label className="wide">Why <span className="optional">OPTIONAL</span><input value={details} onChange={(e) => setDetails(e.target.value)} maxLength={2000} /></label>
        <label>Due by<input type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} required /></label>
        {APPROVAL.includes(kind) && <p className="hint">Needs approval by someone other than you before work starts.</p>}
      </div>
      {create.error && <div className="form-error" role="alert"><AlertCircle size={15} />{create.error.message}</div>}
      <footer><span className="toolbar-spacer" /><button type="button" className="quiet-button" onClick={onClose}>Back</button><button type="submit" className="primary-button compact" disabled={create.isPending}>{create.isPending ? <LoaderCircle className="spin" size={15} /> : <Plus size={15} />} Create action</button></footer>
    </form>
  </div>;
}

/** Actions linked to one order, shown on the order page. */
export function useOrderActions(orderId: string) {
  return useQuery({ queryKey: ["order-actions", orderId], queryFn: () => api<ActionPage>(`/api/v1/actions?order_id=${orderId}`), staleTime: 0 });
}

export function ActionChips({ actions }: { actions: Action[] }) {
  if (actions.length === 0) return null;
  return <ul className="action-chips">{actions.map((a) => <li key={a.id}><a href={`#actions/${a.id}`}><ActionStatus a={a} /> {a.title}<small>{person(a.owner_label)} · due {when(a.due_at)}</small></a></li>)}</ul>;
}
