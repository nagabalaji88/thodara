import { useEffect, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { AlertCircle, Check, ClipboardCheck, LoaderCircle, PackageCheck, X } from "lucide-react";
import { api, type ApiError } from "./api";
import { fmtDate } from "./orders";
import type { BatchDetail, BatchReceipt } from "./types";
import { t, locale } from "./i18n";

const today = () => new Date().toISOString().slice(0, 10);
const person = (label: string | null) => label?.split(" <")[0] ?? t("Unknown user");
const when = (iso: string) => new Date(iso).toLocaleString(locale(), { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const newKey = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`);
const num = (v: string) => Number(v) || 0;

type Mode = { kind: "receive" } | { kind: "inspect"; receipt: BatchReceipt } | { kind: "release"; receipt: BatchReceipt };

/** What physically came back from the supplier and where quality put it. */
export function ReceiptsPanel({ batch: b, canReceive, canDecide, onChange }: { batch: BatchDetail; canReceive: boolean; canDecide: boolean; onChange: (b: BatchDetail) => void }) {
  const [mode, setMode] = useState<Mode | null>(null);
  const q = b.quantities;
  const outstanding = num(q.still_at_supplier);
  return <section className="panel" aria-labelledby="receipts-title">
    <header className="dependency-head">
      <div><span className="eyebrow">{t("RECEIPTS AND QUALITY")}</span><h2 id="receipts-title" className="panel-title">{b.receipts.length ? t("{0} of {1} {2} back", [q.received, q.sent, b.unit_code]) : t("Nothing received yet")}</h2></div>
      {canReceive && b.status === "at_supplier" && outstanding > 0 && <button className="primary-button compact" onClick={() => setMode({ kind: "receive" })}><PackageCheck size={15} /> {t("Record receipt")}</button>}
    </header>
    <dl className="qty-picture quality" aria-label={t("Quality outcome")}>
      <div><dt>{t("At supplier")}</dt><dd>{q.still_at_supplier}</dd><small>{t("not yet back")}</small></div>
      <div className={num(q.awaiting_inspection) ? "reported" : undefined}><dt>{t("Awaiting inspection")}</dt><dd>{q.awaiting_inspection}</dd><small>{t("received, not usable")}</small></div>
      <div className="usable"><dt>{t("Accepted")}</dt><dd>{q.accepted}</dd><small>{t("usable")}</small></div>
      <div className={num(q.held) ? "reported" : undefined}><dt>{t("On hold")}</dt><dd>{q.held}</dd><small>{t("needs a release decision")}</small></div>
      <div><dt>{t("Rework")}</dt><dd>{q.rework}</dd><small>{t("not usable")}</small></div>
      <div className={num(q.rejected_at_inspection) ? "reported bad" : undefined}><dt>{t("Rejected")}</dt><dd>{q.rejected_at_inspection}</dd><small>{t("by our inspection")}</small></div>
    </dl>
    {b.receipts.length > 0 && <div className="table-wrap"><table className="data-table compact-table">
      <thead><tr><th scope="col">{t("Received")}</th><th scope="col" className="num">{t("Quantity")}</th><th scope="col">{t("Document")}</th><th scope="col">{t("Quality")}</th><th scope="col"><span className="sr-only">{t("Actions")}</span></th></tr></thead>
      <tbody>{b.receipts.map((r) => <tr key={r.id} className="static-row">
        <td className="date">{fmtDate(r.receipt_date)}<small className="cell-sub">{t("by {0}", [person(r.received_by_label)])}</small></td>
        <td className="num strong">{r.received_qty} <small>{b.unit_code}</small></td>
        <td className="mono">{r.document_reference ?? "—"}</td>
        <td>{r.status === "awaiting_inspection" ? <span className="stale-note">{t("Awaiting inspection")}</span> : <span className="outcome">
          <span>{t("{0} accepted{1}{2}{3}", [r.accepted_qty, num(r.held_qty) ? t(" · {0} held", [r.held_qty]) : "", num(r.rework_qty) ? t(" · {0} rework", [r.rework_qty]) : "", num(r.rejected_qty) ? t(" · {0} rejected", [r.rejected_qty]) : ""])}</span>
          {r.decisions.map((d, i) => <small key={i}>{t("{0} by {1} {2}{3}", [d.kind === "inspection" ? t("Inspected") : t("Hold released"), person(d.decided_by_label), when(d.decided_at), d.note ? ` — ${d.note}` : ""])}{d.same_person && <span className="late-text"> {t("· same person received and inspected")}</span>}</small>)}
        </span>}</td>
        <td className="row-actions">
          {canDecide && r.status === "awaiting_inspection" && <button className="text-button" onClick={() => setMode({ kind: "inspect", receipt: r })}>{t("Record inspection")}</button>}
          {canDecide && num(r.held_qty) > 0 && <button className="text-button" onClick={() => setMode({ kind: "release", receipt: r })}>{t("Release hold")}</button>}
        </td>
      </tr>)}</tbody>
    </table></div>}
    {mode && <ReceiptDialog mode={mode} batch={b} onClose={() => setMode(null)} onDone={(value) => { setMode(null); onChange(value); }} />}
  </section>;
}

function ReceiptDialog({ mode, batch: b, onClose, onDone }: { mode: Mode; batch: BatchDetail; onClose: () => void; onDone: (b: BatchDetail) => void }) {
  const receipt = mode.kind === "receive" ? null : mode.receipt;
  const target = mode.kind === "inspect" ? num(receipt!.received_qty) : mode.kind === "release" ? num(receipt!.held_qty) : num(b.quantities.still_at_supplier);
  const [quantity, setQuantity] = useState(String(target));
  const [date, setDate] = useState(today());
  const [reference, setReference] = useState("");
  const [note, setNote] = useState("");
  const [accepted, setAccepted] = useState(String(target));
  const [rejected, setRejected] = useState("0");
  const [held, setHeld] = useState("0");
  const [rework, setRework] = useState("0");
  const submissionKey = useMemo(newKey, []);
  useEffect(() => { const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); }; window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k); }, [onClose]);
  const base = `/api/v1/outsourcing/batches/${b.id}/receipts`;
  const split = num(accepted) + num(rejected) + num(rework) + (mode.kind === "inspect" ? num(held) : 0);
  const balanced = mode.kind === "receive" || (mode.kind === "inspect" ? Math.abs(split - target) < 1e-9 : split > 0 && split <= target);
  const notAccepted = num(rejected) + num(rework) + (mode.kind === "inspect" ? num(held) : 0) > 0;
  const submit = useMutation({
    mutationFn: () => {
      const send = (path: string, body: object) => api<BatchDetail>(path, { method: "POST", body: JSON.stringify(body) });
      if (mode.kind === "receive") return send(base, { version: b.version, submission_key: submissionKey, received_qty: quantity, receipt_date: date, document_reference: reference, note });
      if (mode.kind === "inspect") return send(`${base}/${mode.receipt.id}/inspection`, { version: mode.receipt.version, accepted_qty: accepted, rejected_qty: rejected, held_qty: held, rework_qty: rework, note });
      return send(`${base}/${mode.receipt.id}/release`, { version: mode.receipt.version, accepted_qty: accepted, rejected_qty: rejected, rework_qty: rework, reason: note });
    },
    onSuccess: onDone,
  });
  const titles = { receive: t("Record material received"), inspect: t("Record inspection"), release: t("Release held material") };
  const stale = (submit.error as ApiError | null)?.status === 409;
  return <div className="dialog-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <form className="dialog" role="dialog" aria-modal="true" aria-labelledby="receipt-title" onSubmit={(e) => { e.preventDefault(); submit.mutate(); }}>
      <header><div><span className="eyebrow">{b.number} · {b.supplier_name} · {b.item_code}</span><h2 id="receipt-title">{titles[mode.kind]}</h2></div><button type="button" className="icon-button" onClick={onClose} aria-label={t("Close")}><X size={16} /></button></header>
      {mode.kind === "receive" ? <div className="dialog-grid">
        <label>{t("Quantity received")}<input inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} required autoFocus /></label>
        <label>{t("Received on")}<input type="date" value={date} min={b.sent_date ?? undefined} max={today()} onChange={(e) => setDate(e.target.value)} required /></label>
        <label className="wide">{t("Supplier challan / inward number")} <span className="optional">{t("OPTIONAL")}</span><input value={reference} onChange={(e) => setReference(e.target.value)} maxLength={80} /></label>
        <label className="wide">{t("Note")} <span className="optional">{t("OPTIONAL")}</span><input value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} /></label>
        <p className="hint wide">{t("{0} {1} is still at the supplier. Received material waits for inspection before it is usable.", [b.quantities.still_at_supplier, b.unit_code])}</p>
      </div> : <>
        <p className="hint">{mode.kind === "inspect" ? t("Split the {0} {1} received on {2}.", [receipt!.received_qty, b.unit_code, fmtDate(receipt!.receipt_date)]) : t("{0} {1} is on hold. Release some or all of it; the rest stays held.", [receipt!.held_qty, b.unit_code])}</p>
        <div className={`dialog-grid ${mode.kind === "inspect" ? "four-up" : "three"}`}>
          <label>{t("Accepted")}<input inputMode="decimal" value={accepted} onChange={(e) => setAccepted(e.target.value)} required autoFocus /></label>
          {mode.kind === "inspect" && <label>{t("On hold")}<input inputMode="decimal" value={held} onChange={(e) => setHeld(e.target.value)} required /></label>}
          <label>{t("Rework")}<input inputMode="decimal" value={rework} onChange={(e) => setRework(e.target.value)} required /></label>
          <label>{t("Rejected")}<input inputMode="decimal" value={rejected} onChange={(e) => setRejected(e.target.value)} required /></label>
          <p className={`reconcile wide ${balanced ? "ok" : "off"}`} aria-live="polite">{balanced ? <><Check size={13} /> {mode.kind === "inspect" ? t("Accounts for all {0} {1}.", [target, b.unit_code]) : t("Releases {0} of {1} {2}.", [split, target, b.unit_code])}</> : <><AlertCircle size={13} /> {mode.kind === "inspect" ? t("Accounts for {0} of {1} {2}.", [split, target, b.unit_code]) : t("Release between 1 and {0} {1}.", [target, b.unit_code])}</>}</p>
          <label className="wide">{mode.kind === "release" ? t("Reason for release") : <>{t("Findings")} {!notAccepted && <span className="optional">{t("OPTIONAL")}</span>}</>}<input value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} required={mode.kind === "release" || notAccepted} minLength={mode.kind === "release" ? 3 : undefined} placeholder={mode.kind === "release" ? t("e.g. Pressure test passed") : t("e.g. Porosity on 20; coating thickness below spec on 4")} /></label>
        </div>
      </>}
      {submit.error && <div className="form-error" role="alert"><AlertCircle size={15} /><span>{submit.error.message}{stale && t(" Close this and reopen the batch to see the latest version.")}</span></div>}
      <footer><span className="toolbar-spacer" /><button type="button" className="quiet-button" onClick={onClose}>{t("Back")}</button><button type="submit" className="primary-button compact" disabled={submit.isPending || !balanced}>{submit.isPending ? <LoaderCircle className="spin" size={15} /> : mode.kind === "receive" ? <PackageCheck size={15} /> : <ClipboardCheck size={15} />} {t("Save")}</button></footer>
    </form>
  </div>;
}
