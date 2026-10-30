import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Check, LoaderCircle, Truck, X } from "lucide-react";
import { api, type ApiError } from "./api";
import { fmtDate } from "./orders";
import type { OrderDetail } from "./types";
import { t, tk } from "./i18n";

interface ReadinessLine { line_id: string; line_no: number; item_code: string; unit_code: string; remaining: string; promised_date: string | null; shippable: string | null; finished_stock: string | null; components: { item_code: string; unit_code: string; qty_per_unit: string; usable_for_line: string; source: "batch" | "stock" }[] }
interface DispatchNote {
  id: string; number: string; dispatch_date: string; carrier: string | null; vehicle_reference: string | null; document_reference: string | null; note: string | null;
  status: "pending_approval" | "posted" | "rejected" | "cancelled"; cancel_reason: string | null; created_by_label: string | null; cancelled_by_label: string | null;
  decided_by_label: string | null; decision_note: string | null; can_decide: boolean; version: number;
  lines: { line_id: string; line_no: number; item_code: string; unit_code: string; quantity: string; promised_date: string | null; on_time: boolean | null; exception_reason: string | null }[];
}
const person = (label: string | null) => label?.split(" <")[0] ?? t("Unknown user");
const newKey = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`);
const today = () => new Date().toISOString().slice(0, 10);
const NOTE_STATUS: Record<DispatchNote["status"], string> = { pending_approval: tk(" (awaiting approval)"), posted: "", rejected: tk(" (rejected)"), cancelled: tk(" (cancelled)") };

/** What can ship now, what has shipped, and recording a dispatch. */
export function DispatchPanel({ order, canDispatch }: { order: OrderDetail; canDispatch: boolean }) {
  const queryClient = useQueryClient();
  const ready = useQuery({ queryKey: ["readiness", order.id, order.version], queryFn: () => api<{ lines: ReadinessLine[] }>(`/api/v1/dispatch/readiness?order_id=${order.id}`), enabled: order.status === "confirmed", staleTime: 0 });
  const notes = useQuery({ queryKey: ["dispatches", order.id, order.version], queryFn: () => api<DispatchNote[]>(`/api/v1/dispatch?order_id=${order.id}`), staleTime: 0 });
  const [open, setOpen] = useState(false);
  const [cancelling, setCancelling] = useState<DispatchNote | null>(null);
  const [deciding, setDeciding] = useState<{ note: DispatchNote; approve: boolean } | null>(null);
  const refresh = () => { for (const k of ["order", "orders", "readiness", "dispatches", "order-risk", "risk-board", "batch"]) void queryClient.invalidateQueries({ queryKey: [k] }); };
  const lines = ready.data?.lines ?? [];
  if (order.status !== "confirmed" && (notes.data ?? []).length === 0) return null;
  return <section className="panel" aria-labelledby="dispatch-title">
    <header className="dependency-head">
      <div><span className="eyebrow">{t("DISPATCH")}</span><h2 id="dispatch-title" className="panel-title">{order.status === "confirmed" ? t("Ready to ship") : t("Shipments")}</h2></div>
      {canDispatch && order.status === "confirmed" && lines.length > 0 && <button className="primary-button compact" onClick={() => setOpen(true)}><Truck size={15} /> {t("Record dispatch")}</button>}
    </header>
    {lines.length > 0 && <div className="table-wrap"><table className="data-table compact-table">
      <thead><tr><th scope="col">{t("Line")}</th><th scope="col" className="num">{t("Still to ship")}</th><th scope="col" className="num">{t("Can ship now")}</th><th scope="col">{t("Limited by")}</th></tr></thead>
      <tbody>{lines.map((l) => <tr key={l.line_id} className="static-row">
        <td className="mono">{l.line_no} · {l.item_code}</td><td className="num">{l.remaining} <small>{l.unit_code}</small></td>
        <td className="num strong">{l.shippable ?? "—"}{l.shippable && <small> {l.unit_code}</small>}</td>
        <td>{l.finished_stock !== null && <span className="cell-sub">{t("{0} {1} {2} in finished-goods stock", [l.finished_stock, l.unit_code, l.item_code])}</span>}
          {l.shippable === null ? <span className="muted-inline">{l.finished_stock !== null ? t("Components not tracked; not checked") : t("Nothing tracked to check")}</span> : l.components.map((c) => <span key={c.item_code} className="cell-sub">{c.usable_for_line} {c.unit_code} {c.source === "stock" ? t("in stock") : t("accepted")} {c.item_code} ({t("{0} per unit)", [c.qty_per_unit])}</span>)}</td>
      </tr>)}</tbody>
    </table></div>}
    {(notes.data ?? []).length > 0 && <ol className="timeline">{notes.data!.map((n) => <li key={n.id} className={n.status === "cancelled" || n.status === "rejected" ? "superseded" : undefined}>
      <b><Truck size={13} /> {n.number} · {fmtDate(n.dispatch_date)}{t(NOTE_STATUS[n.status])}</b>
      <span>{n.lines.map((l) => t("{0} {1} line {2}{3}{4}", [l.quantity, l.unit_code, l.line_no, l.on_time === true ? t(" on time") : l.on_time === false ? t(" late") : "", l.exception_reason ? t(" · exception: {0}", [l.exception_reason]) : ""])).join("; ")}{n.carrier ? ` · ${n.carrier}` : ""}{n.document_reference ? t(" · LR {0}", [n.document_reference]) : ""}</span>
      <small>{n.status === "pending_approval" ? t("Requested by {0}; nothing has shipped yet", [person(n.created_by_label)]) : person(n.created_by_label)}
        {n.decided_by_label && t(n.status === "rejected" ? " · rejected by {0}{1}" : " · approved by {0}{1}", [person(n.decided_by_label), n.decision_note ? `: ${n.decision_note}` : ""])}
        {n.cancel_reason ? t(" · cancelled by {0}: {1}", [person(n.cancelled_by_label), n.cancel_reason]) : ""}
        {canDispatch && n.status === "posted" && <> · <button type="button" className="text-button" onClick={() => setCancelling(n)}>{t("Cancel dispatch")}</button></>}
        {n.can_decide && <> · <button type="button" className="text-button" onClick={() => setDeciding({ note: n, approve: true })}>{t("Approve")}</button> · <button type="button" className="text-button" onClick={() => setDeciding({ note: n, approve: false })}>{t("Reject")}</button></>}</small>
    </li>)}</ol>}
    {open && <DispatchDialog order={order} lines={lines} onClose={() => setOpen(false)} onDone={() => { setOpen(false); refresh(); }} />}
    {cancelling && <CancelDialog note={cancelling} onClose={() => setCancelling(null)} onDone={() => { setCancelling(null); refresh(); }} />}
    {deciding && <DecideDialog {...deciding} onClose={() => setDeciding(null)} onDone={() => { setDeciding(null); refresh(); }} />}
  </section>;
}

function DispatchDialog({ order, lines, onClose, onDone }: { order: OrderDetail; lines: ReadinessLine[]; onClose: () => void; onDone: () => void }) {
  const [date, setDate] = useState(today());
  const [carrier, setCarrier] = useState("");
  const [vehicle, setVehicle] = useState("");
  const [lr, setLr] = useState("");
  const [qty, setQty] = useState<Record<string, string>>(Object.fromEntries(lines.map((l) => [l.line_id, l.shippable === null ? l.remaining : l.shippable])));
  const [why, setWhy] = useState<Record<string, string>>({});
  const key = useMemo(newKey, []);
  useEffect(() => { const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); }; window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k); }, [onClose]);
  const over = (l: ReadinessLine) => l.shippable !== null && Number(qty[l.line_id] || 0) > Number(l.shippable);
  const chosen = lines.filter((l) => Number(qty[l.line_id] || 0) > 0);
  const save = useMutation({
    mutationFn: () => api("/api/v1/dispatch", { method: "POST", body: JSON.stringify({
      submission_key: key, order_id: order.id, dispatch_date: date, carrier, vehicle_reference: vehicle, document_reference: lr,
      lines: chosen.map((l) => ({ line_id: l.line_id, quantity: qty[l.line_id], exception_reason: over(l) ? why[l.line_id] : null })),
    }) }),
    onSuccess: onDone,
  });
  return <div className="dialog-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <form className="dialog wide-dialog" role="dialog" aria-modal="true" aria-labelledby="dispatch-dialog-title" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      <header><div><span className="eyebrow">{order.number} · {order.customer_name}</span><h2 id="dispatch-dialog-title">{t("Record dispatch")}</h2></div><button type="button" className="icon-button" onClick={onClose} aria-label={t("Close")}><X size={16} /></button></header>
      <div className="dialog-grid">
        <label>{t("Dispatched on")}<input type="date" value={date} max={today()} onChange={(e) => setDate(e.target.value)} required /></label>
        <label>{t("Transporter")} <span className="optional">{t("OPTIONAL")}</span><input value={carrier} onChange={(e) => setCarrier(e.target.value)} maxLength={120} /></label>
        <label>{t("Vehicle")} <span className="optional">{t("OPTIONAL")}</span><input value={vehicle} onChange={(e) => setVehicle(e.target.value)} maxLength={80} placeholder={t("e.g. KA-01-AB-1234")} /></label>
        <label>{t("LR / delivery note")} <span className="optional">{t("OPTIONAL")}</span><input value={lr} onChange={(e) => setLr(e.target.value)} maxLength={80} /></label>
      </div>
      <div className="dep-fieldset">
        {lines.map((l) => <div key={l.line_id} className="dispatch-row">
          <label>{t("Line {0}", [l.line_no])} · {l.item_code} <small>{t("{0} {1} to ship{2}", [l.remaining, l.unit_code, l.shippable !== null ? t(" · {0} from stock and accepted material", [l.shippable]) : l.finished_stock !== null ? t(" · {0} in finished-goods stock", [l.finished_stock]) : ""])}</small><input aria-label={t("Quantity for line {0}", [l.line_no])} inputMode="decimal" value={qty[l.line_id] ?? ""} onChange={(e) => setQty({ ...qty, [l.line_id]: e.target.value })} /></label>
          {over(l) && <label className="exception">{t("Exception reason — someone else must approve before this ships")}<input value={why[l.line_id] ?? ""} onChange={(e) => setWhy({ ...why, [l.line_id]: e.target.value })} required minLength={3} maxLength={500} placeholder={t("Why ship more than accepted material allows?")} /></label>}
        </div>)}
      </div>
      <p className="hint">{chosen.some(over) ? t("This goes to an approver first. Nothing ships, and no material is used, until someone other than you approves it.") : t("Posting updates shipped quantities at once and uses up finished-goods stock first, then the components and accepted batch material behind the rest. It can only be undone by cancelling the dispatch with a reason.")}</p>
      {save.error && <div className="form-error" role="alert"><AlertCircle size={15} /><span>{save.error.message}{(save.error as ApiError).status === 409 && t(" Reload the order.")}</span></div>}
      <footer><span className="toolbar-spacer" /><button type="button" className="quiet-button" onClick={onClose}>{t("Back")}</button><button type="submit" className="primary-button compact" disabled={save.isPending || chosen.length === 0}>{save.isPending ? <LoaderCircle className="spin" size={15} /> : <Check size={15} />} {chosen.some(over) ? t("Request approval") : t("Post dispatch")}</button></footer>
    </form>
  </div>;
}

function CancelDialog({ note, onClose, onDone }: { note: DispatchNote; onClose: () => void; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const cancel = useMutation({ mutationFn: () => api(`/api/v1/dispatch/${note.id}/cancel`, { method: "POST", body: JSON.stringify({ version: note.version, reason }) }), onSuccess: onDone });
  return <div className="dialog-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <form className="dialog" role="dialog" aria-modal="true" aria-labelledby="cancel-dn-title" onSubmit={(e) => { e.preventDefault(); cancel.mutate(); }}>
      <header><div><span className="eyebrow">{note.number}</span><h2 id="cancel-dn-title">{t("Cancel dispatch")}</h2></div><button type="button" className="icon-button" onClick={onClose} aria-label={t("Close")}><X size={16} /></button></header>
      <div className="dialog-grid"><label className="wide">{t("Reason")}<input value={reason} onChange={(e) => setReason(e.target.value)} required minLength={3} maxLength={500} autoFocus placeholder={t("e.g. Truck turned back at the gate")} /></label>
        <p className="hint wide">{t("Shipped quantities and the batch material they used are restored exactly.")}</p></div>
      {cancel.error && <div className="form-error" role="alert"><AlertCircle size={15} />{cancel.error.message}</div>}
      <footer><span className="toolbar-spacer" /><button type="button" className="quiet-button" onClick={onClose}>{t("Back")}</button><button type="submit" className="primary-button compact danger-fill" disabled={cancel.isPending}>{t("Cancel dispatch")}</button></footer>
    </form>
  </div>;
}

function DecideDialog({ note, approve, onClose, onDone }: { note: DispatchNote; approve: boolean; onClose: () => void; onDone: () => void }) {
  const [text, setText] = useState("");
  const decide = useMutation({
    mutationFn: () => api(`/api/v1/dispatch/${note.id}/${approve ? "approve" : "reject"}`, { method: "POST", body: JSON.stringify(approve ? { version: note.version, note: text || null } : { version: note.version, reason: text }) }),
    onSuccess: onDone,
  });
  return <div className="dialog-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <form className="dialog" role="dialog" aria-modal="true" aria-labelledby="decide-dn-title" onSubmit={(e) => { e.preventDefault(); decide.mutate(); }}>
      <header><div><span className="eyebrow">{t("{0} · requested by {1}", [note.number, person(note.created_by_label)])}</span><h2 id="decide-dn-title">{approve ? t("Approve dispatch exception") : t("Reject dispatch exception")}</h2></div><button type="button" className="icon-button" onClick={onClose} aria-label={t("Close")}><X size={16} /></button></header>
      <div className="dialog-grid">
        <ul className="wide plain-list">{note.lines.map((l) => <li key={l.line_id}>{t("{0} {1} line {2}", [l.quantity, l.unit_code, l.line_no])} · {l.item_code}{l.exception_reason ? ` — ${l.exception_reason}` : ""}</li>)}</ul>
        <label className="wide">{approve ? <>{t("Note")} <span className="optional">{t("OPTIONAL")}</span></> : t("Reason")}<input value={text} onChange={(e) => setText(e.target.value)} required={!approve} minLength={approve ? undefined : 3} maxLength={500} autoFocus placeholder={approve ? t("e.g. Customer agreed in writing") : t("e.g. Wait for the held castings")} /></label>
        <p className="hint wide">{approve ? t("Approving ships these quantities now. Only accepted material is used; the rest ships on the exception.") : t("Nothing ships. The request stays in the history.")}</p>
      </div>
      {decide.error && <div className="form-error" role="alert"><AlertCircle size={15} /><span>{decide.error.message}{(decide.error as ApiError).status === 409 && t(" Reload the order.")}</span></div>}
      <footer><span className="toolbar-spacer" /><button type="button" className="quiet-button" onClick={onClose}>{t("Back")}</button><button type="submit" className={`primary-button compact${approve ? "" : " danger-fill"}`} disabled={decide.isPending}>{approve ? t("Approve and ship") : t("Reject")}</button></footer>
    </form>
  </div>;
}
