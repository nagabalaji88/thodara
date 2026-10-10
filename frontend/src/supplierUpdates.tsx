import { useEffect, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { AlertCircle, Check, LoaderCircle, MessageSquareText, PencilLine, X } from "lucide-react";
import { api, type ApiError } from "./api";
import { fmtDate } from "./orders";
import type { BatchDetail, ReportFields, SupplierUpdate } from "./types";

const METHODS: [SupplierUpdate["contact_method"], string][] = [["phone", "Phone call"], ["whatsapp", "WhatsApp"], ["email", "Email"], ["visit", "Site visit"], ["other", "Other"]];
const METHOD_LABEL = Object.fromEntries(METHODS) as Record<string, string>;

/** "3 hours ago", "2 days ago": how old the supplier's information is. */
export function age(iso: string, now = Date.now()) {
  const minutes = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60000));
  if (minutes < 60) return minutes <= 1 ? "just now" : `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

const when = (iso: string) => new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const person = (label: string | null) => label?.split(" <")[0] ?? "Unknown user";

/** Compact "supplier says" line for lists and the order page. */
export function ReportBrief({ r, unit, empty }: { r: ReportFields; unit: string; empty?: string }) {
  if (!r.last_reported_at) return empty ? <span className="stale-note">{empty}</span> : <span className="muted-inline">—</span>;
  return <span className="report-brief">
    <span><b>{r.reported_completed}</b> done · <b>{r.reported_rejected}</b> rejected · <b>{r.reported_pending}</b> pending <small>{unit}</small></span>
    <small>Supplier said {age(r.last_reported_at)}{r.revised_return_date ? ` · now expects ${fmtDate(r.revised_return_date)}` : ""}</small>
    {r.blocker && <small className="blocker-note">{r.blocker}</small>}
  </span>;
}

export function SupplierPanel({ batch: b, canRecord, onChange }: { batch: BatchDetail; canRecord: boolean; onChange: (b: BatchDetail) => void }) {
  const [mode, setMode] = useState<"new" | "correct" | null>(null);
  const q = b.quantities;
  const latest = b.latest_update;
  const atSupplier = b.status === "at_supplier";
  return <section className="panel supplier-panel" aria-labelledby="supplier-title">
    <header className="dependency-head">
      <div><span className="eyebrow">WHAT THE SUPPLIER SAYS</span><h2 id="supplier-title" className="panel-title">{latest ? `Last update ${age(latest.reported_at)}` : atSupplier ? "No update yet" : "Not sent yet"}</h2></div>
      {canRecord && atSupplier && <div className="row-buttons">
        {latest && <button className="quiet-button" onClick={() => setMode("correct")}><PencilLine size={14} /> Correct last update</button>}
        <button className="primary-button compact" onClick={() => setMode("new")}><MessageSquareText size={15} /> Record supplier update</button>
      </div>}
    </header>
    <dl className="qty-picture" aria-label="Quantities">
      <div><dt>Sent</dt><dd>{q.sent}</dd><small>{b.unit_code} on challan</small></div>
      <div className="reported"><dt>Supplier: completed</dt><dd>{q.reported_completed ?? "?"}</dd><small>reported, not received</small></div>
      <div className="reported bad"><dt>Supplier: rejected</dt><dd>{q.reported_rejected ?? "?"}</dd><small>reported</small></div>
      <div className="reported"><dt>Supplier: pending</dt><dd>{q.reported_pending ?? "?"}</dd><small>reported</small></div>
      <div><dt>Received</dt><dd>{q.received}</dd><small>at our gate</small></div>
      <div><dt>Accepted</dt><dd>{q.accepted}</dd><small>usable after inspection</small></div>
    </dl>
    <p className="hint">Supplier figures are what they told us. Nothing is usable until it is received and accepted by quality; receipts and inspection are recorded in the next release step.</p>
    {latest ? <div className="latest-report">
      <p className="provenance"><span className="badge status-pending">Supplier confirmation pending</span> Entered by {person(latest.recorded_by_label)} from a {METHOD_LABEL[latest.contact_method]?.toLowerCase()}{latest.contact_name ? ` with ${latest.contact_name}` : ""}. The supplier said this on {when(latest.reported_at)}.</p>
      <dl className="facts">
        <div><dt>Planned return</dt><dd>{fmtDate(b.expected_return_date)}</dd></div>
        <div><dt>Supplier now expects</dt><dd className={latest.revised_return_date && latest.revised_return_date > b.expected_return_date ? "late-text" : undefined}>{latest.revised_return_date ? fmtDate(latest.revised_return_date) : "No date given"}</dd></div>
      </dl>
      {latest.blocker && <div className="notice-line"><AlertCircle size={16} /><span><b>Blocker:</b> {latest.blocker}</span></div>}
    </div> : atSupplier && b.sent_date && <div className="notice-line"><AlertCircle size={16} /><span>Nothing heard from {b.supplier_name} since the batch was sent on {fmtDate(b.sent_date)}. Status is unknown, which is not the same as late.</span></div>}
    {b.updates.length > 0 && <details className="update-history">
      <summary>All {b.updates.length} update{b.updates.length > 1 ? "s" : ""}</summary>
      <ol className="timeline">{b.updates.map((u) => <li key={u.id} className={u.superseded ? "superseded" : undefined}>
        <b>{u.completed_qty} done · {u.rejected_qty} rejected · {u.pending_qty} pending{u.superseded && " (corrected)"}</b>
        <span>{u.corrects_id ? `Correction: ${u.correction_reason}` : METHOD_LABEL[u.contact_method]}{u.contact_name ? ` · ${u.contact_name}` : ""}{u.revised_return_date ? ` · expects ${fmtDate(u.revised_return_date)}` : ""}{u.blocker ? ` · ${u.blocker}` : ""}</span>
        <small>Said {when(u.reported_at)} · entered by {person(u.recorded_by_label)} {when(u.recorded_at)}</small>
      </li>)}</ol>
    </details>}
    {mode && <UpdateDialog batch={b} correcting={mode === "correct" ? latest : null} onClose={() => setMode(null)} onDone={(value) => { setMode(null); onChange(value); }} />}
  </section>;
}

const toLocalInput = (d: Date) => { const local = new Date(d); local.setMinutes(local.getMinutes() - local.getTimezoneOffset()); return local.toISOString().slice(0, 16); };
const localNow = () => toLocalInput(new Date());
const newKey = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`);

function UpdateDialog({ batch: b, correcting, onClose, onDone }: { batch: BatchDetail; correcting: SupplierUpdate | null; onClose: () => void; onDone: (b: BatchDetail) => void }) {
  const start = correcting ?? b.latest_update;
  const [completed, setCompleted] = useState(start?.completed_qty ?? "0");
  const [rejected, setRejected] = useState(start?.rejected_qty ?? "0");
  const [pending, setPending] = useState(start?.pending_qty ?? b.quantity);
  // Until someone types a pending figure, it is the rest of the batch.
  const [pendingTouched, setPendingTouched] = useState(false);
  const fillPending = (c: string, r: string) => {
    if (pendingTouched) return;
    const rest = Math.round((Number(b.quantity) - (Number(c) || 0) - (Number(r) || 0)) * 1e6) / 1e6;
    setPending(rest >= 0 ? String(rest) : "");
  };
  const [method, setMethod] = useState<SupplierUpdate["contact_method"]>(correcting?.contact_method ?? "phone");
  const [contact, setContact] = useState(correcting?.contact_name ?? b.latest_update?.contact_name ?? "");
  const [reportedAt, setReportedAt] = useState(correcting ? toLocalInput(new Date(correcting.reported_at)) : localNow());
  const [revised, setRevised] = useState(start?.revised_return_date ?? "");
  const [blocker, setBlocker] = useState(start?.blocker ?? "");
  const [reason, setReason] = useState("");
  // One key per dialog: a double tap or retry is recorded once.
  const submissionKey = useMemo(newKey, []);
  useEffect(() => { const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); }; window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k); }, [onClose]);
  const total = [completed, rejected, pending].reduce((sum, v) => sum + (Number(v) || 0), 0);
  const sent = Number(b.quantity);
  const diff = Math.round((sent - total) * 1e6) / 1e6;
  const submit = useMutation({
    mutationFn: () => api<BatchDetail>(`/api/v1/outsourcing/batches/${b.id}/updates`, { method: "POST", body: JSON.stringify({
      version: b.version, submission_key: submissionKey, completed_qty: completed, rejected_qty: rejected, pending_qty: pending,
      contact_method: method, contact_name: contact, reported_at: new Date(reportedAt).toISOString(), revised_return_date: revised || null, blocker,
      ...(correcting ? { corrects_id: correcting.id, correction_reason: reason } : {}),
    }) }),
    onSuccess: onDone,
  });
  const stale = (submit.error as ApiError | null)?.status === 409;
  return <div className="dialog-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <form className="dialog" role="dialog" aria-modal="true" aria-labelledby="update-title" onSubmit={(e) => { e.preventDefault(); submit.mutate(); }}>
      <header><div><span className="eyebrow">{b.number} · {b.supplier_name} · {b.quantity} {b.unit_code} {b.item_code}</span><h2 id="update-title">{correcting ? "Correct the last update" : "Record what the supplier said"}</h2></div><button type="button" className="icon-button" onClick={onClose} aria-label="Close"><X size={16} /></button></header>
      <div className="dialog-grid three">
        <label>Completed<input inputMode="decimal" value={completed} onChange={(e) => { setCompleted(e.target.value); fillPending(e.target.value, rejected); }} required autoFocus /></label>
        <label>Rejected<input inputMode="decimal" value={rejected} onChange={(e) => { setRejected(e.target.value); fillPending(completed, e.target.value); }} required /></label>
        <label>Pending<input inputMode="decimal" value={pending} onChange={(e) => { setPending(e.target.value); setPendingTouched(true); }} required /></label>
        <p className={`reconcile wide ${diff === 0 ? "ok" : "off"}`} aria-live="polite">{diff === 0 ? <><Check size={13} /> Adds up to the {b.quantity} {b.unit_code} sent.</> : <><AlertCircle size={13} /> Adds up to {total} of {b.quantity} {b.unit_code} sent; {diff > 0 ? `${diff} unaccounted` : `${-diff} too many`}.</>}</p>
      </div>
      <div className="dialog-grid">
        <label>How you heard<select value={method} onChange={(e) => setMethod(e.target.value as SupplierUpdate["contact_method"])}>{METHODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <label>Who said it <span className="optional">OPTIONAL</span><input value={contact} onChange={(e) => setContact(e.target.value)} maxLength={120} placeholder="e.g. Murugan, supervisor" /></label>
        <label>When they said it<input type="datetime-local" value={reportedAt} max={localNow()} onChange={(e) => setReportedAt(e.target.value)} required /></label>
        <label>Supplier now expects <span className="optional">OPTIONAL</span><input type="date" value={revised} min={b.sent_date ?? undefined} onChange={(e) => setRevised(e.target.value)} /></label>
        <label className="wide">Blocker <span className="optional">OPTIONAL</span><input value={blocker} onChange={(e) => setBlocker(e.target.value)} maxLength={500} placeholder="e.g. Coating line down; porosity on 20 castings" /></label>
        {correcting && <label className="wide">Why correct it<input value={reason} onChange={(e) => setReason(e.target.value)} required minLength={3} maxLength={500} placeholder="e.g. Supervisor read out yesterday's count" /></label>}
      </div>
      <p className="hint">Saved as <b>entered by you, supplier confirmation pending</b>. It does not count as received and does not change any customer promise.</p>
      {submit.error && <div className="form-error" role="alert"><AlertCircle size={15} /><span>{submit.error.message}{stale && " Close this and reopen the batch to see the latest version."}</span></div>}
      <footer><span className="toolbar-spacer" /><button type="button" className="quiet-button" onClick={onClose}>Back</button><button type="submit" className="primary-button compact" disabled={submit.isPending || diff !== 0}>{submit.isPending ? <LoaderCircle className="spin" size={15} /> : <Check size={15} />} {correcting ? "Save correction" : "Save update"}</button></footer>
    </form>
  </div>;
}
