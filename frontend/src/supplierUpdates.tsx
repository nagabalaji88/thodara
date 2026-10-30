import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AlertCircle, Check, LoaderCircle, MessageSquareText, PencilLine, X } from "lucide-react";
import { api, type ApiError } from "./api";
import { fmtDate } from "./orders";
import type { BatchDetail, ReportFields, SupplierUpdate } from "./types";
import { locale, t, tk } from "./i18n";

const METHODS: [SupplierUpdate["contact_method"], string][] = [["phone", tk("Phone call")], ["whatsapp", tk("WhatsApp")], ["email", tk("Email")], ["visit", tk("Site visit")], ["other", tk("Other")]];
const METHOD_LABEL = Object.fromEntries(METHODS) as Record<string, string>;

/** "3 hours ago", "2 days ago": how old the supplier's information is. */
export function age(iso: string, now = Date.now()) {
  const minutes = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60000));
  if (minutes < 60) return minutes <= 1 ? t("just now") : t("{0} min ago", [minutes]);
  const hours = Math.round(minutes / 60);
  if (hours < 24) return t("{0} h ago", [hours]);
  const days = Math.round(hours / 24);
  return t(days === 1 ? "{0} day ago" : "{0} days ago", [days]);
}

const when = (iso: string) => new Date(iso).toLocaleString(locale(), { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const person = (label: string | null) => label?.split(" <")[0] ?? t("Unknown user");

/** Compact "supplier says" line for lists and the order page. */
export function ReportBrief({ r, unit, empty }: { r: ReportFields; unit: string; empty?: string }) {
  if (!r.last_reported_at) return empty ? <span className="stale-note">{empty}</span> : <span className="muted-inline">—</span>;
  return <span className="report-brief">
    <span><b>{r.reported_completed}</b> {t("done ·")} <b>{r.reported_rejected}</b> {t("rejected ·")} <b>{r.reported_pending}</b> {t("pending")} <small>{unit}</small></span>
    <small>{t("Supplier said {0}{1}", [age(r.last_reported_at), r.revised_return_date ? t(" · now expects {0}", [fmtDate(r.revised_return_date)]) : ""])}</small>
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
      <div><span className="eyebrow">{t("WHAT THE SUPPLIER SAYS")}</span><h2 id="supplier-title" className="panel-title">{latest ? t("Last update {0}", [age(latest.reported_at)]) : atSupplier ? t("No update yet") : t("Not sent yet")}</h2></div>
      {canRecord && atSupplier && <div className="row-buttons">
        {latest && <button className="quiet-button" onClick={() => setMode("correct")}><PencilLine size={14} /> {t("Correct last update")}</button>}
        <button className="primary-button compact" onClick={() => setMode("new")}><MessageSquareText size={15} /> {t("Record supplier update")}</button>
      </div>}
    </header>
    <dl className="qty-picture" aria-label={t("Quantities")}>
      <div><dt>{t("Sent")}</dt><dd>{q.sent}</dd><small>{t("{0} on challan", [b.unit_code])}</small></div>
      <div className="reported"><dt>{t("Supplier: completed")}</dt><dd>{q.reported_completed ?? "?"}</dd><small>{t("reported, not received")}</small></div>
      <div className="reported bad"><dt>{t("Supplier: rejected")}</dt><dd>{q.reported_rejected ?? "?"}</dd><small>{t("reported")}</small></div>
      <div className="reported"><dt>{t("Supplier: pending")}</dt><dd>{q.reported_pending ?? "?"}</dd><small>{q.reported_unaccounted && Number(q.reported_unaccounted) !== 0 ? (Number(q.reported_unaccounted) > 0 ? t("{0} unaccounted", [q.reported_unaccounted]) : t("{0} more than sent", [-Number(q.reported_unaccounted)])) : t("reported")}</small></div>
      <div><dt>{t("Received")}</dt><dd>{q.received}</dd><small>{Number(q.awaiting_inspection) > 0 ? t("{0} awaiting inspection", [q.awaiting_inspection]) : t("at our gate")}</small></div>
      <div className="usable"><dt>{t("Accepted · usable")}</dt><dd>{q.accepted}</dd><small>{Number(q.held) > 0 ? t("{0} on quality hold", [q.held]) : t("passed inspection")}</small></div>
    </dl>
    <p className="hint">{t("Supplier figures are what they told us. Only material received at our gate and accepted by quality is usable.")}</p>
    {latest ? <div className="latest-report">
      <p className="provenance"><span className="badge status-pending">{t("Supplier confirmation pending")}</span> {t("Entered by {0} from a {1}{2}. The supplier said this on {3}", [person(latest.recorded_by_label), t(METHOD_LABEL[latest.contact_method])?.toLowerCase(), latest.contact_name ? t(" with {0}", [latest.contact_name]) : "", when(latest.reported_at)])}.</p>
      <dl className="facts">
        <div><dt>{t("Planned return")}</dt><dd>{fmtDate(b.expected_return_date)}</dd></div>
        <div><dt>{t("Supplier now expects")}</dt><dd className={latest.revised_return_date && latest.revised_return_date > b.expected_return_date ? "late-text" : undefined}>{latest.revised_return_date ? fmtDate(latest.revised_return_date) : t("No date given")}</dd></div>
      </dl>
      {latest.blocker && <div className="notice-line"><AlertCircle size={16} /><span><b>{t("Blocker:")}</b> {latest.blocker}</span></div>}
    </div> : atSupplier && b.sent_date && <div className="notice-line"><AlertCircle size={16} /><span>{t("Nothing heard from {0} since the batch was sent on {1}. Status is unknown, which is not the same as late.", [b.supplier_name, fmtDate(b.sent_date)])}</span></div>}
    {b.updates.length > 0 && <details className="update-history">
      <summary>{t(b.updates.length > 1 ? "All {0} updates" : "All {0} update", [b.updates.length])}</summary>
      <ol className="timeline">{b.updates.map((u) => <li key={u.id} className={u.superseded ? "superseded" : undefined}>
        <b>{t("{0} done · {1} rejected · {2} pending{3}", [u.completed_qty, u.rejected_qty, u.pending_qty, Number(u.unaccounted_qty) > 0 ? t(" · {0} unaccounted", [u.unaccounted_qty]) : Number(u.unaccounted_qty) < 0 ? t(" · {0} more than sent", [-Number(u.unaccounted_qty)]) : ""])}{u.superseded && t(" (corrected)")}</b>
        <span>{u.corrects_id ? t("Correction: {0}", [u.correction_reason]) : t(METHOD_LABEL[u.contact_method])}{u.contact_name ? ` · ${u.contact_name}` : ""}{u.revised_return_date ? t(" · expects {0}", [fmtDate(u.revised_return_date)]) : ""}{u.blocker ? ` · ${u.blocker}` : ""}</span>
        <small>{t("Said {0} · entered by {1} {2}", [when(u.reported_at), person(u.recorded_by_label), when(u.recorded_at)])}</small>
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
  // The company may allow the figures to differ from the quantity sent by a small percentage.
  const settings = useQuery({ queryKey: ["fulfillment-settings"], queryFn: () => api<{ reconciliation_tolerance_percent: string }>("/api/v1/fulfillment/settings") });
  const tolerance = Number(settings.data?.reconciliation_tolerance_percent ?? 0);
  const allowed = Math.round(sent * tolerance / 100 * 1e6) / 1e6;
  const fits = Math.abs(diff) <= allowed;
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
      <header><div><span className="eyebrow">{b.number} · {b.supplier_name} · {b.quantity} {b.unit_code} {b.item_code}</span><h2 id="update-title">{correcting ? t("Correct the last update") : t("Record what the supplier said")}</h2></div><button type="button" className="icon-button" onClick={onClose} aria-label={t("Close")}><X size={16} /></button></header>
      <div className="dialog-grid three">
        <label>{t("Completed")}<input inputMode="decimal" value={completed} onChange={(e) => { setCompleted(e.target.value); fillPending(e.target.value, rejected); }} required autoFocus /></label>
        <label>{t("Rejected")}<input inputMode="decimal" value={rejected} onChange={(e) => { setRejected(e.target.value); fillPending(completed, e.target.value); }} required /></label>
        <label>{t("Pending")}<input inputMode="decimal" value={pending} onChange={(e) => { setPending(e.target.value); setPendingTouched(true); }} required /></label>
        <p className={`reconcile wide ${fits ? "ok" : "off"}`} aria-live="polite">{diff === 0 ? <><Check size={13} /> {t("Adds up to the {0} {1} sent.", [b.quantity, b.unit_code])}</>
          : fits ? <><Check size={13} /> {t("{0} of {1} {2} sent; {3}, within the company’s ±{4}", [total, b.quantity, b.unit_code, diff > 0 ? t("{0} unaccounted", [diff]) : t("{0} more than sent", [-diff]), tolerance])}% ({t("{0} {1}). Unaccounted pieces are not expected back.", [allowed, b.unit_code])}</>
          : <><AlertCircle size={13} /> {t("Adds up to {0} of {1} {2} sent; {3}. Allowed difference: ±{4}", [total, b.quantity, b.unit_code, diff > 0 ? t("{0} unaccounted", [diff]) : t("{0} too many", [-diff]), tolerance])}% ({allowed} {b.unit_code}).</>}</p>
      </div>
      <div className="dialog-grid">
        <label>{t("How you heard")}<select value={method} onChange={(e) => setMethod(e.target.value as SupplierUpdate["contact_method"])}>{METHODS.map(([v, l]) => <option key={v} value={v}>{t(l)}</option>)}</select></label>
        <label>{t("Who said it")} <span className="optional">{t("OPTIONAL")}</span><input value={contact} onChange={(e) => setContact(e.target.value)} maxLength={120} placeholder={t("e.g. Murugan, supervisor")} /></label>
        <label>{t("When they said it")}<input type="datetime-local" value={reportedAt} max={localNow()} onChange={(e) => setReportedAt(e.target.value)} required /></label>
        <label>{t("Supplier now expects")} <span className="optional">{t("OPTIONAL")}</span><input type="date" value={revised} min={b.sent_date ?? undefined} onChange={(e) => setRevised(e.target.value)} /></label>
        <label className="wide">{t("Blocker")} <span className="optional">{t("OPTIONAL")}</span><input value={blocker} onChange={(e) => setBlocker(e.target.value)} maxLength={500} placeholder={t("e.g. Coating line down; porosity on 20 castings")} /></label>
        {correcting && <label className="wide">{t("Why correct it")}<input value={reason} onChange={(e) => setReason(e.target.value)} required minLength={3} maxLength={500} placeholder={t("e.g. Supervisor read out yesterday's count")} /></label>}
      </div>
      <p className="hint">{t("Saved as")} <b>{t("entered by you, supplier confirmation pending")}</b>{t(". It does not count as received and does not change any customer promise.")}</p>
      {submit.error && <div className="form-error" role="alert"><AlertCircle size={15} /><span>{submit.error.message}{stale && t(" Close this and reopen the batch to see the latest version.")}</span></div>}
      <footer><span className="toolbar-spacer" /><button type="button" className="quiet-button" onClick={onClose}>{t("Back")}</button><button type="submit" className="primary-button compact" disabled={submit.isPending || !fits}>{submit.isPending ? <LoaderCircle className="spin" size={15} /> : <Check size={15} />} {correcting ? t("Save correction") : t("Save update")}</button></footer>
    </form>
  </div>;
}
