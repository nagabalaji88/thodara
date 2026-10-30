import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Boxes, Check, LoaderCircle, Plus, RotateCcw, Search, X } from "lucide-react";
import { api, type ApiError } from "./api";
import { fmtDate, useLookups } from "./orders";
import type { MasterRecord, Page } from "./types";
import { t, tk } from "./i18n";

type Kind = "opening" | "receipt" | "issue" | "adjustment" | "dispatch" | "reversal";
interface Balance { site_id: string; site_name: string; warehouse_id: string; warehouse_code: string; warehouse_name: string; item_id: string; item_code: string; item_name: string; item_type: string; unit_code: string; on_hand: string; pending: number }
interface Movement {
  id: string; site_name: string; warehouse_code: string; item_id: string; item_code: string; item_name: string; unit_code: string; kind: Kind; quantity: string;
  status: "pending_approval" | "posted" | "rejected"; movement_date: string; reason: string | null; reference: string | null; balance_after: string | null;
  dispatch_number: string | null; reverses_id: string | null; reversed: boolean; created_by_label: string | null; created_at: string;
  decided_by_label: string | null; decision_note: string | null; can_decide: boolean; can_reverse: boolean; version: number;
}

const KIND: Record<Kind, string> = { opening: tk("Opening balance"), receipt: tk("Receipt"), issue: tk("Issue"), adjustment: tk("Adjustment"), dispatch: tk("Dispatch"), reversal: tk("Reversal") };
const person = (label: string | null) => label?.split(" <")[0] ?? t("Unknown user");
const newKey = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`);
const today = () => new Date().toISOString().slice(0, 10);
const signed = (q: string) => (Number(q) > 0 ? `+${q}` : q);

function useEscape(onClose: () => void) {
  useEffect(() => { const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); }; window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k); }, [onClose]);
}

/** Stock per warehouse: balances, entries waiting for approval, and the ledger of one item. */
export function StockPage({ permissions }: { permissions: string[] }) {
  const canRecord = permissions.includes("stock:record");
  const queryClient = useQueryClient();
  const [q, setQ] = useState("");
  const [itemId, setItemId] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [deciding, setDeciding] = useState<{ m: Movement; approve: boolean } | null>(null);
  const [reversing, setReversing] = useState<Movement | null>(null);
  const params = new URLSearchParams(q.trim() ? { q: q.trim() } : {});
  const summary = useQuery({ queryKey: ["stock", "balances", q], queryFn: () => api<{ balances: Balance[]; pending_for_me: number }>(`/api/v1/stock/balances?${params}`), staleTime: 0 });
  const pending = useQuery({ queryKey: ["stock", "pending"], queryFn: () => api<Movement[]>("/api/v1/stock/movements?status=pending_approval"), staleTime: 0 });
  const history = useQuery({ queryKey: ["stock", "history", itemId], queryFn: () => api<Movement[]>(`/api/v1/stock/movements?item_id=${itemId}`), enabled: !!itemId, staleTime: 0 });
  const refresh = () => { for (const k of ["stock", "order-risk", "risk-board", "readiness"]) void queryClient.invalidateQueries({ queryKey: [k] }); };
  const balances = summary.data?.balances ?? [];
  const chosen = balances.find((b) => b.item_id === itemId) ?? history.data?.[0];
  const waiting = pending.data ?? [];
  return <section className="wrap page">
    <header className="page-head"><div><span className="eyebrow">{t("STORES")}</span><h1 className="page-title">{t("Stock")}</h1></div><p className="lede small">{t("On hand per warehouse. Receipts and issues count at once; opening balances and adjustments count only after someone else approves them. Stock never goes below zero.")}</p></header>
    {waiting.length > 0 && <div className="panel data-panel">
      <h2 className="panel-title">{t("Waiting for approval")}</h2>
      <div className="table-wrap"><table className="data-table compact-table">
        <thead><tr><th scope="col">{t("Entry")}</th><th scope="col">{t("Item")}</th><th scope="col">{t("Warehouse")}</th><th scope="col" className="num">{t("Change")}</th><th scope="col">{t("Why")}</th><th scope="col">{t("Entered by")}</th><th scope="col"><span className="sr-only">{t("Decide")}</span></th></tr></thead>
        <tbody>{waiting.map((m) => <tr key={m.id} className="static-row">
          <td>{t(KIND[m.kind])}<small className="cell-sub">{fmtDate(m.movement_date)}</small></td>
          <td className="mono">{m.item_code}<small className="cell-sub">{m.item_name}</small></td>
          <td className="mono">{m.warehouse_code}<small className="cell-sub">{m.site_name}</small></td>
          <td className="num strong">{signed(m.quantity)} <small>{m.unit_code}</small></td>
          <td>{m.reason ?? "—"}{m.reference && <small className="cell-sub">{m.reference}</small>}</td>
          <td>{person(m.created_by_label)}</td>
          <td className="row-actions">{m.can_decide ? <><button className="text-button" onClick={() => setDeciding({ m, approve: true })}>{t("Approve")}</button> · <button className="text-button" onClick={() => setDeciding({ m, approve: false })}>{t("Reject")}</button></> : <span className="muted-inline">{t("Needs someone else")}</span>}</td>
        </tr>)}</tbody>
      </table></div>
    </div>}
    <div className="panel data-panel">
      <div className="toolbar">
        <label className="search-field"><Search size={14} /><input aria-label={t("Search items")} placeholder={t("Search item code or name")} value={q} maxLength={80} onChange={(e) => setQ(e.target.value)} /></label>
        <span className="toolbar-spacer" />
        {canRecord && <button className="primary-button compact" onClick={() => setRecording(true)}><Plus size={15} /> {t("Record stock")}</button>}
      </div>
      {summary.isError ? <div className="form-error" role="alert"><AlertCircle size={15} />{summary.error.message}</div>
        : summary.isPending ? <div className="table-state"><LoaderCircle className="spin" size={16} /> {t("Loading…")}</div>
          : balances.length === 0 ? <div className="table-state">{q ? t("No stock for that item.") : t("No stock entered yet. Items without stock are assumed available in delivery risk until you enter some.")}</div>
            : <div className="table-wrap"><table className="data-table">
              <thead><tr><th scope="col">{t("Item")}</th><th scope="col">{t("Warehouse")}</th><th scope="col" className="num">{t("On hand")}</th><th scope="col">{t("Waiting")}</th></tr></thead>
              <tbody>{balances.map((b) => <tr key={`${b.warehouse_id}-${b.item_id}`} tabIndex={0} aria-label={t("Show history of {0}", [b.item_code])} className={b.item_id === itemId ? "selected-row" : undefined} onClick={() => setItemId(b.item_id)} onKeyDown={(e) => { if (e.key === "Enter") setItemId(b.item_id); }}>
                <td><b className="mono">{b.item_code}</b><small className="cell-sub">{b.item_name} · {t(b.item_type.replace(/_/g, " "))}</small></td>
                <td className="mono">{b.warehouse_code}<small className="cell-sub">{b.warehouse_name} · {b.site_name}</small></td>
                <td className={`num strong ${Number(b.on_hand) === 0 ? "late-text" : ""}`}>{b.on_hand} <small>{b.unit_code}</small></td>
                <td>{b.pending > 0 ? <span className="badge status-pending">{t("{0} awaiting approval", [b.pending])}</span> : <span className="muted-inline">—</span>}</td>
              </tr>)}</tbody>
            </table></div>}
    </div>
    {itemId && <section className="panel" aria-labelledby="ledger-title">
      <header className="dependency-head"><div><span className="eyebrow">{t("LEDGER")}</span><h2 id="ledger-title" className="panel-title">{chosen ? `${chosen.item_code} · ${chosen.item_name}` : t("History")}</h2></div><button className="icon-button" onClick={() => setItemId(null)} aria-label={t("Close history")}><X size={16} /></button></header>
      {history.isPending ? <div className="table-state"><LoaderCircle className="spin" size={16} /> {t("Loading…")}</div>
        : <ol className="timeline">{(history.data ?? []).map((m) => <li key={m.id} className={m.status === "rejected" || m.reversed ? "superseded" : undefined}>
          <b><Boxes size={13} /> {t(KIND[m.kind])} · {signed(m.quantity)} {m.unit_code} · {m.warehouse_code}{m.status === "pending_approval" ? t(" (awaiting approval)") : m.status === "rejected" ? t(" (rejected)") : m.balance_after !== null ? t(" → {0} on hand", [m.balance_after]) : ""}{m.reversed ? t(" (reversed)") : ""}</b>
          <span>{fmtDate(m.movement_date)}{m.dispatch_number ? t(" · dispatch {0}", [m.dispatch_number]) : ""}{m.reference && !m.dispatch_number ? ` · ${m.reference}` : ""}{m.reason ? ` · ${m.reason}` : ""}</span>
          <small>{person(m.created_by_label)}{m.decided_by_label ? t(m.status === "rejected" ? " · rejected by {0}{1}" : " · approved by {0}{1}", [person(m.decided_by_label), m.decision_note ? `: ${m.decision_note}` : ""]) : ""}
            {m.can_reverse && <> · <button type="button" className="text-button" onClick={() => setReversing(m)}><RotateCcw size={11} /> {t("Reverse")}</button></>}</small>
        </li>)}</ol>}
    </section>}
    {recording && <RecordDialog onClose={() => setRecording(false)} onDone={(m) => { setRecording(false); setItemId(m.item_id); refresh(); }} />}
    {deciding && <DecideDialog {...deciding} onClose={() => setDeciding(null)} onDone={() => { setDeciding(null); refresh(); }} />}
    {reversing && <ReverseDialog m={reversing} onClose={() => setReversing(null)} onDone={() => { setReversing(null); refresh(); }} />}
  </section>;
}

function RecordDialog({ onClose, onDone }: { onClose: () => void; onDone: (m: Movement) => void }) {
  const { items, sites } = useLookups();
  const warehouses = useQuery({ queryKey: ["md", "warehouses", "lookup"], queryFn: () => api<Page<MasterRecord>>("/api/v1/master-data/warehouses?status=active&limit=200") });
  const [kind, setKind] = useState<"receipt" | "issue" | "opening" | "adjustment">("receipt");
  const [direction, setDirection] = useState<"in" | "out">("in");
  const [warehouseId, setWarehouseId] = useState("");
  const [itemId, setItemId] = useState("");
  const [quantity, setQuantity] = useState("");
  const [date, setDate] = useState(today());
  const [reason, setReason] = useState("");
  const [reference, setReference] = useState("");
  const key = useMemo(newKey, []);
  useEscape(onClose);
  const stockable = items.filter((i) => i.item_type !== "service");
  const siteName = (id?: string) => sites.find((s) => s.id === id)?.name ?? "";
  const needsApproval = kind === "opening" || kind === "adjustment";
  const save = useMutation({
    mutationFn: () => api<Movement>("/api/v1/stock/movements", { method: "POST", body: JSON.stringify({
      submission_key: key, warehouse_id: warehouseId, item_id: itemId, kind, quantity, movement_date: date,
      direction: kind === "adjustment" ? direction : null, reason: reason || null, reference: reference || null,
    }) }),
    onSuccess: onDone,
  });
  return <div className="dialog-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <form className="dialog wide-dialog" role="dialog" aria-modal="true" aria-labelledby="record-stock-title" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      <header><div><span className="eyebrow">{t("STOCK")}</span><h2 id="record-stock-title">{t("Record stock")}</h2></div><button type="button" className="icon-button" onClick={onClose} aria-label={t("Close")}><X size={16} /></button></header>
      <div className="segmented" role="radiogroup" aria-label={t("Kind of entry")}>{([["receipt", t("Receipt")], ["issue", t("Issue")], ["opening", t("Opening balance")], ["adjustment", t("Adjustment")]] as const).map(([k, label]) => <button key={k} type="button" role="radio" aria-checked={kind === k} className={kind === k ? "on" : undefined} onClick={() => setKind(k)}>{label}</button>)}</div>
      <div className="dialog-grid">
        <label>{t("Warehouse")}<select value={warehouseId} onChange={(e) => setWarehouseId(e.target.value)} required><option value="" disabled>{t("Choose a warehouse")}</option>{(warehouses.data?.items ?? []).map((w) => <option key={w.id} value={w.id}>{w.code} · {w.name}{siteName(w.site_id) ? ` (${siteName(w.site_id)})` : ""}</option>)}</select></label>
        <label>{t("Item")}<select value={itemId} onChange={(e) => setItemId(e.target.value)} required><option value="" disabled>{t("Choose an item")}</option>{stockable.map((i) => <option key={i.id} value={i.id}>{i.code} · {i.name}</option>)}</select></label>
        {kind === "adjustment" && <label>{t("Direction")}<select value={direction} onChange={(e) => setDirection(e.target.value as "in" | "out")}><option value="in">{t("Add to stock (found, recount up)")}</option><option value="out">{t("Remove from stock (damaged, recount down)")}</option></select></label>}
        <label>{t("Quantity")}<input inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} required placeholder={t("In the item's base unit")} /></label>
        <label>{t("Date")}<input type="date" value={date} max={today()} onChange={(e) => setDate(e.target.value)} required /></label>
        <label>{t("Reference")} <span className="optional">{t("OPTIONAL")}</span><input value={reference} onChange={(e) => setReference(e.target.value)} maxLength={80} placeholder={t("e.g. GRN-1042, count sheet 7")} /></label>
        <label className="wide">{t("Reason")}{kind === "receipt" || kind === "opening" ? <span className="optional"> {t("OPTIONAL")}</span> : ""}<input value={reason} onChange={(e) => setReason(e.target.value)} required={kind === "issue" || kind === "adjustment"} minLength={kind === "issue" || kind === "adjustment" ? 3 : undefined} maxLength={500} placeholder={kind === "issue" ? t("e.g. Issued to assembly line 2") : kind === "adjustment" ? t("e.g. Cycle count found 3 damaged") : t("e.g. Physical count on 1 Oct")} /></label>
      </div>
      <p className="hint">{t("{0} Entries are never edited; a mistake is reversed by an opposite entry.", [needsApproval ? t("This counts only after someone other than you approves it.") : kind === "issue" ? t("Counts at once. It is refused if the warehouse does not have enough.") : t("Counts at once.")])}</p>
      {save.error && <div className="form-error" role="alert"><AlertCircle size={15} />{save.error.message}</div>}
      <footer><span className="toolbar-spacer" /><button type="button" className="quiet-button" onClick={onClose}>{t("Back")}</button><button type="submit" className="primary-button compact" disabled={save.isPending}>{save.isPending ? <LoaderCircle className="spin" size={15} /> : <Check size={15} />} {needsApproval ? t("Send for approval") : t("Save")}</button></footer>
    </form>
  </div>;
}

function DecideDialog({ m, approve, onClose, onDone }: { m: Movement; approve: boolean; onClose: () => void; onDone: () => void }) {
  const [text, setText] = useState("");
  useEscape(onClose);
  const decide = useMutation({
    mutationFn: () => api(`/api/v1/stock/movements/${m.id}/${approve ? "approve" : "reject"}`, { method: "POST", body: JSON.stringify(approve ? { version: m.version, note: text || null } : { version: m.version, reason: text }) }),
    onSuccess: onDone,
  });
  return <div className="dialog-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <form className="dialog" role="dialog" aria-modal="true" aria-labelledby="decide-stock-title" onSubmit={(e) => { e.preventDefault(); decide.mutate(); }}>
      <header><div><span className="eyebrow">{t("{0} · entered by {1}", [t(KIND[m.kind]), person(m.created_by_label)])}</span><h2 id="decide-stock-title">{approve ? t("Approve stock entry") : t("Reject stock entry")}</h2></div><button type="button" className="icon-button" onClick={onClose} aria-label={t("Close")}><X size={16} /></button></header>
      <div className="dialog-grid">
        <p className="wide"><b>{signed(m.quantity)} {m.unit_code} {m.item_code}</b> {t("in {0}{1}", [m.warehouse_code, m.reason ? ` — ${m.reason}` : ""])}</p>
        <label className="wide">{approve ? <>{t("Note")} <span className="optional">{t("OPTIONAL")}</span></> : t("Reason")}<input value={text} onChange={(e) => setText(e.target.value)} required={!approve} minLength={approve ? undefined : 3} maxLength={500} autoFocus placeholder={approve ? t("e.g. Checked against the count sheet") : t("e.g. Count sheet does not match")} /></label>
        <p className="hint wide">{approve ? t("Approving posts it now. It is refused if it would take the warehouse below zero.") : t("Nothing changes in stock. The entry stays in the history.")}</p>
      </div>
      {decide.error && <div className="form-error" role="alert"><AlertCircle size={15} /><span>{decide.error.message}{(decide.error as ApiError).status === 409 && t(" Reload the page.")}</span></div>}
      <footer><span className="toolbar-spacer" /><button type="button" className="quiet-button" onClick={onClose}>{t("Back")}</button><button type="submit" className={`primary-button compact${approve ? "" : " danger-fill"}`} disabled={decide.isPending}>{approve ? t("Approve") : t("Reject")}</button></footer>
    </form>
  </div>;
}

function ReverseDialog({ m, onClose, onDone }: { m: Movement; onClose: () => void; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const key = useMemo(newKey, []);
  useEscape(onClose);
  const reverse = useMutation({ mutationFn: () => api(`/api/v1/stock/movements/${m.id}/reverse`, { method: "POST", body: JSON.stringify({ version: m.version, submission_key: key, reason }) }), onSuccess: onDone });
  return <div className="dialog-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <form className="dialog" role="dialog" aria-modal="true" aria-labelledby="reverse-stock-title" onSubmit={(e) => { e.preventDefault(); reverse.mutate(); }}>
      <header><div><span className="eyebrow">{t(KIND[m.kind])} · {signed(m.quantity)} {m.unit_code} {m.item_code} · {m.warehouse_code}</span><h2 id="reverse-stock-title">{t("Reverse this entry")}</h2></div><button type="button" className="icon-button" onClick={onClose} aria-label={t("Close")}><X size={16} /></button></header>
      <div className="dialog-grid"><label className="wide">{t("Reason")}<input value={reason} onChange={(e) => setReason(e.target.value)} required minLength={3} maxLength={500} autoFocus placeholder={t("e.g. Booked against the wrong item")} /></label>
        <p className="hint wide">{t("Records the opposite quantity; the original stays in the history.{0}", [m.kind === "opening" || m.kind === "adjustment" ? t(" Like the original, the reversal needs someone else’s approval.") : ""])}</p></div>
      {reverse.error && <div className="form-error" role="alert"><AlertCircle size={15} />{reverse.error.message}</div>}
      <footer><span className="toolbar-spacer" /><button type="button" className="quiet-button" onClick={onClose}>{t("Back")}</button><button type="submit" className="primary-button compact danger-fill" disabled={reverse.isPending}>{t("Reverse")}</button></footer>
    </form>
  </div>;
}
