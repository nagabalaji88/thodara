import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Check, LoaderCircle, Truck, X } from "lucide-react";
import { api, type ApiError } from "./api";
import { fmtDate } from "./orders";
import type { OrderDetail } from "./types";

interface ReadinessLine { line_id: string; line_no: number; item_code: string; unit_code: string; remaining: string; promised_date: string | null; shippable: string | null; components: { item_code: string; unit_code: string; qty_per_unit: string; usable_for_line: string }[] }
interface DispatchNote {
  id: string; number: string; dispatch_date: string; carrier: string | null; vehicle_reference: string | null; document_reference: string | null; note: string | null;
  status: "posted" | "cancelled"; cancel_reason: string | null; created_by_label: string | null; cancelled_by_label: string | null; version: number;
  lines: { line_id: string; line_no: number; item_code: string; unit_code: string; quantity: string; promised_date: string | null; on_time: boolean | null; exception_reason: string | null }[];
}
const person = (label: string | null) => label?.split(" <")[0] ?? "Unknown user";
const newKey = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`);
const today = () => new Date().toISOString().slice(0, 10);

/** What can ship now, what has shipped, and recording a dispatch. */
export function DispatchPanel({ order, canDispatch, canOverride }: { order: OrderDetail; canDispatch: boolean; canOverride: boolean }) {
  const queryClient = useQueryClient();
  const ready = useQuery({ queryKey: ["readiness", order.id, order.version], queryFn: () => api<{ lines: ReadinessLine[] }>(`/api/v1/dispatch/readiness?order_id=${order.id}`), enabled: order.status === "confirmed", staleTime: 0 });
  const notes = useQuery({ queryKey: ["dispatches", order.id, order.version], queryFn: () => api<DispatchNote[]>(`/api/v1/dispatch?order_id=${order.id}`), staleTime: 0 });
  const [open, setOpen] = useState(false);
  const [cancelling, setCancelling] = useState<DispatchNote | null>(null);
  const refresh = () => { for (const k of ["order", "orders", "readiness", "dispatches", "order-risk", "risk-board", "batch"]) void queryClient.invalidateQueries({ queryKey: [k] }); };
  const lines = ready.data?.lines ?? [];
  if (order.status !== "confirmed" && (notes.data ?? []).length === 0) return null;
  return <section className="panel" aria-labelledby="dispatch-title">
    <header className="dependency-head">
      <div><span className="eyebrow">DISPATCH</span><h2 id="dispatch-title" className="panel-title">{order.status === "confirmed" ? "Ready to ship" : "Shipments"}</h2></div>
      {canDispatch && order.status === "confirmed" && lines.length > 0 && <button className="primary-button compact" onClick={() => setOpen(true)}><Truck size={15} /> Record dispatch</button>}
    </header>
    {lines.length > 0 && <div className="table-wrap"><table className="data-table compact-table">
      <thead><tr><th scope="col">Line</th><th scope="col" className="num">Still to ship</th><th scope="col" className="num">Can ship now</th><th scope="col">Limited by</th></tr></thead>
      <tbody>{lines.map((l) => <tr key={l.line_id} className="static-row">
        <td className="mono">{l.line_no} · {l.item_code}</td><td className="num">{l.remaining} <small>{l.unit_code}</small></td>
        <td className="num strong">{l.shippable ?? "—"}{l.shippable && <small> {l.unit_code}</small>}</td>
        <td>{l.shippable === null ? <span className="muted-inline">Nothing outsourced to check</span> : l.components.map((c) => <span key={c.item_code} className="cell-sub">{c.usable_for_line} {c.unit_code} accepted {c.item_code} ({c.qty_per_unit} per unit)</span>)}</td>
      </tr>)}</tbody>
    </table></div>}
    {(notes.data ?? []).length > 0 && <ol className="timeline">{notes.data!.map((n) => <li key={n.id} className={n.status === "cancelled" ? "superseded" : undefined}>
      <b><Truck size={13} /> {n.number} · {fmtDate(n.dispatch_date)}{n.status === "cancelled" ? " (cancelled)" : ""}</b>
      <span>{n.lines.map((l) => `${l.quantity} ${l.unit_code} line ${l.line_no}${l.on_time === true ? " on time" : l.on_time === false ? " late" : ""}${l.exception_reason ? ` · exception: ${l.exception_reason}` : ""}`).join("; ")}{n.carrier ? ` · ${n.carrier}` : ""}{n.document_reference ? ` · LR ${n.document_reference}` : ""}</span>
      <small>{person(n.created_by_label)}{n.cancel_reason ? ` · cancelled by ${person(n.cancelled_by_label)}: ${n.cancel_reason}` : ""}{canDispatch && n.status === "posted" && <> · <button type="button" className="text-button" onClick={() => setCancelling(n)}>Cancel dispatch</button></>}</small>
    </li>)}</ol>}
    {open && <DispatchDialog order={order} lines={lines} canOverride={canOverride} onClose={() => setOpen(false)} onDone={() => { setOpen(false); refresh(); }} />}
    {cancelling && <CancelDialog note={cancelling} onClose={() => setCancelling(null)} onDone={() => { setCancelling(null); refresh(); }} />}
  </section>;
}

function DispatchDialog({ order, lines, canOverride, onClose, onDone }: { order: OrderDetail; lines: ReadinessLine[]; canOverride: boolean; onClose: () => void; onDone: () => void }) {
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
      <header><div><span className="eyebrow">{order.number} · {order.customer_name}</span><h2 id="dispatch-dialog-title">Record dispatch</h2></div><button type="button" className="icon-button" onClick={onClose} aria-label="Close"><X size={16} /></button></header>
      <div className="dialog-grid">
        <label>Dispatched on<input type="date" value={date} max={today()} onChange={(e) => setDate(e.target.value)} required /></label>
        <label>Transporter <span className="optional">OPTIONAL</span><input value={carrier} onChange={(e) => setCarrier(e.target.value)} maxLength={120} /></label>
        <label>Vehicle <span className="optional">OPTIONAL</span><input value={vehicle} onChange={(e) => setVehicle(e.target.value)} maxLength={80} placeholder="e.g. KA-01-AB-1234" /></label>
        <label>LR / delivery note <span className="optional">OPTIONAL</span><input value={lr} onChange={(e) => setLr(e.target.value)} maxLength={80} /></label>
      </div>
      <div className="dep-fieldset">
        {lines.map((l) => <div key={l.line_id} className="dispatch-row">
          <label>Line {l.line_no} · {l.item_code} <small>{l.remaining} {l.unit_code} to ship{l.shippable !== null ? ` · ${l.shippable} buildable from accepted material` : ""}</small><input aria-label={`Quantity for line ${l.line_no}`} inputMode="decimal" value={qty[l.line_id] ?? ""} onChange={(e) => setQty({ ...qty, [l.line_id]: e.target.value })} /></label>
          {over(l) && (canOverride
            ? <label className="exception">Exception reason (owner/administrator)<input value={why[l.line_id] ?? ""} onChange={(e) => setWhy({ ...why, [l.line_id]: e.target.value })} required minLength={3} maxLength={500} placeholder="Why ship more than accepted material allows?" /></label>
            : <p className="late-text small-note">More than accepted material allows; an owner or administrator must record an exception.</p>)}
        </div>)}
      </div>
      <p className="hint">Posting updates shipped quantities at once and uses up the accepted batch material behind them. It can only be undone by cancelling the dispatch with a reason.</p>
      {save.error && <div className="form-error" role="alert"><AlertCircle size={15} /><span>{save.error.message}{(save.error as ApiError).status === 409 && " Reload the order."}</span></div>}
      <footer><span className="toolbar-spacer" /><button type="button" className="quiet-button" onClick={onClose}>Back</button><button type="submit" className="primary-button compact" disabled={save.isPending || chosen.length === 0 || (!canOverride && chosen.some(over))}>{save.isPending ? <LoaderCircle className="spin" size={15} /> : <Check size={15} />} Post dispatch</button></footer>
    </form>
  </div>;
}

function CancelDialog({ note, onClose, onDone }: { note: DispatchNote; onClose: () => void; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const cancel = useMutation({ mutationFn: () => api(`/api/v1/dispatch/${note.id}/cancel`, { method: "POST", body: JSON.stringify({ version: note.version, reason }) }), onSuccess: onDone });
  return <div className="dialog-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <form className="dialog" role="dialog" aria-modal="true" aria-labelledby="cancel-dn-title" onSubmit={(e) => { e.preventDefault(); cancel.mutate(); }}>
      <header><div><span className="eyebrow">{note.number}</span><h2 id="cancel-dn-title">Cancel dispatch</h2></div><button type="button" className="icon-button" onClick={onClose} aria-label="Close"><X size={16} /></button></header>
      <div className="dialog-grid"><label className="wide">Reason<input value={reason} onChange={(e) => setReason(e.target.value)} required minLength={3} maxLength={500} autoFocus placeholder="e.g. Truck turned back at the gate" /></label>
        <p className="hint wide">Shipped quantities and the batch material they used are restored exactly.</p></div>
      {cancel.error && <div className="form-error" role="alert"><AlertCircle size={15} />{cancel.error.message}</div>}
      <footer><span className="toolbar-spacer" /><button type="button" className="quiet-button" onClick={onClose}>Back</button><button type="submit" className="primary-button compact danger-fill" disabled={cancel.isPending}>Cancel dispatch</button></footer>
    </form>
  </div>;
}
