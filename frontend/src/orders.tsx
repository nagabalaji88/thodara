import { useEffect, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, Check, FileUp, History, LoaderCircle, Plus, Search, Trash2, X } from "lucide-react";
import { api, type ApiError } from "./api";
import type { MasterRecord, OrderDetail, OrderImportReport, OrderLine, OrderSummary, Page, Site } from "./types";

const STATUS_LABEL: Record<string, string> = { draft: "Draft", confirmed: "Confirmed", closed: "Closed", cancelled: "Cancelled", open: "Open", short_closed: "Short-closed", fulfilled: "Fulfilled" };
const REASONS: [string, string][] = [["customer_request", "Customer request"], ["supplier_delay", "Supplier delay"], ["material_shortage", "Material shortage"], ["capacity", "Capacity"], ["quality", "Quality"], ["transport", "Transport"], ["other", "Other"]];
const REASON_LABEL: Record<string, string> = Object.fromEntries([["initial", "First promise"], ...REASONS]);
const fmtDate = (value: string | null) => value ? new Date(`${value}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "—";
const today = () => new Date().toISOString().slice(0, 10);

export function OrdersPage({ sub, permissions }: { sub: string; permissions: string[] }) {
  const canManage = permissions.includes("orders:manage");
  if (sub === "new" && canManage) return <NewOrder />;
  if (sub === "import" && canManage) return <OrderImport />;
  if (sub && sub !== "new" && sub !== "import") return <OrderView id={sub} canManage={canManage} />;
  return <OrderList canManage={canManage} />;
}

function Badge({ status }: { status: string }) {
  return <span className={`badge status-${status}`}>{STATUS_LABEL[status] ?? status}</span>;
}

function useLookups() {
  const customers = useQuery({ queryKey: ["md", "customers", "lookup"], queryFn: () => api<Page<MasterRecord>>("/api/v1/master-data/customers?status=active&limit=200") });
  const items = useQuery({ queryKey: ["md", "items", "lookup"], queryFn: () => api<Page<MasterRecord>>("/api/v1/master-data/items?status=active&limit=200") });
  const sites = useQuery({ queryKey: ["sites"], queryFn: () => api<Site[]>("/api/v1/organization/sites") });
  return { customers: customers.data?.items ?? [], items: items.data?.items ?? [], sites: (sites.data ?? []).filter((s) => s.status === "active") };
}

function OrderList({ canManage }: { canManage: boolean }) {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const limit = 25;
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (q.trim()) params.set("q", q.trim());
  if (status) params.set("status", status);
  const list = useQuery({ queryKey: ["orders", q, status, offset], queryFn: () => api<Page<OrderSummary>>(`/api/v1/orders?${params}`), placeholderData: keepPreviousData });
  useEffect(() => setOffset(0), [q, status]);
  const total = list.data?.total ?? 0;
  return <section className="wrap page">
    <header className="page-head"><div><span className="eyebrow">CUSTOMER COMMITMENTS</span><h1 className="page-title">Orders</h1></div><p className="lede small">What each customer is owed and when you promised it. Every promise change keeps its reason and who made it.</p></header>
    <div className="panel data-panel">
      <div className="toolbar">
        <label className="search-field"><Search size={14} /><input aria-label="Search orders" placeholder="Order number, PO or customer" value={q} maxLength={80} onChange={(e) => setQ(e.target.value)} /></label>
        <select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All statuses</option><option value="draft">Draft</option><option value="confirmed">Confirmed</option><option value="closed">Closed</option><option value="cancelled">Cancelled</option></select>
        <span className="toolbar-spacer" />
        {canManage && <><a className="quiet-button" href="#orders/import"><FileUp size={15} /> Import</a><a className="primary-button compact" href="#orders/new"><Plus size={15} /> New order</a></>}
      </div>
      {list.isError ? <div className="form-error" role="alert"><AlertCircle size={15} />{list.error.message}</div>
        : list.isPending ? <div className="table-state"><LoaderCircle className="spin" size={16} /> Loading…</div>
          : total === 0 ? <div className="table-state">{q || status ? "No orders match." : "No customer orders yet."}{canManage && !q && !status && <a className="quiet-button" href="#orders/new"><Plus size={14} /> Enter the first order</a>}</div>
            : <div className="table-wrap"><table className="data-table">
              <thead><tr><th scope="col">Order</th><th scope="col">Customer</th><th scope="col">Customer PO</th><th scope="col">Site</th><th scope="col">Ordered</th><th scope="col">Next promise</th><th scope="col">Open lines</th><th scope="col">Status</th></tr></thead>
              <tbody>{list.data.items.map((o) => <tr key={o.id} tabIndex={0} aria-label={`Open ${o.number}`} onClick={() => { window.location.hash = `orders/${o.id}`; }} onKeyDown={(e) => { if (e.key === "Enter") window.location.hash = `orders/${o.id}`; }}>
                <td className="mono">{o.number}</td><td>{o.customer_name}</td><td className="mono">{o.customer_reference ?? "—"}</td><td>{o.site_name}</td><td>{fmtDate(o.order_date)}</td><td>{fmtDate(o.next_promised_date)}</td><td>{o.open_lines} of {o.line_count}</td><td><Badge status={o.status} /></td>
              </tr>)}</tbody>
            </table></div>}
      {total > limit && <div className="pager"><span>{offset + 1}–{Math.min(offset + limit, total)} of {total}</span><button className="quiet-button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>Previous</button><button className="quiet-button" disabled={offset + limit >= total} onClick={() => setOffset(offset + limit)}>Next</button></div>}
    </div>
  </section>;
}

type DraftLine = { item_id: string; quantity: string; requested_date: string; promised_date: string };
const emptyLine = (): DraftLine => ({ item_id: "", quantity: "", requested_date: "", promised_date: "" });

function NewOrder() {
  const { customers, items, sites } = useLookups();
  const queryClient = useQueryClient();
  const [siteId, setSiteId] = useState("");
  const [customerId, setCustomerId] = useState("");
  const [reference, setReference] = useState("");
  const [orderDate, setOrderDate] = useState(today());
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<DraftLine[]>([emptyLine()]);
  useEffect(() => { if (!siteId && sites[0]) setSiteId(sites[0].id); }, [sites, siteId]);
  const create = useMutation({
    mutationFn: () => api<OrderDetail>("/api/v1/orders", { method: "POST", body: JSON.stringify({
      site_id: siteId, customer_id: customerId, customer_reference: reference, order_date: orderDate, notes,
      lines: lines.map((l) => ({ item_id: l.item_id, quantity: l.quantity, requested_date: l.requested_date, promised_date: l.promised_date || null })),
    }) }),
    onSuccess: (order) => { void queryClient.invalidateQueries({ queryKey: ["orders"] }); window.location.hash = `orders/${order.id}`; },
  });
  const set = (i: number, field: keyof DraftLine, value: string) => setLines((ls) => ls.map((l, j) => j === i ? { ...l, [field]: value } : l));
  const unitOf = (itemId: string) => items.find((it) => it.id === itemId);
  return <section className="wrap page">
    <a className="back-link" href="#orders"><ArrowLeft size={15} /> Orders</a>
    <header className="page-head"><div><span className="eyebrow">NEW CUSTOMER ORDER</span><h1 className="page-title">New order</h1></div><p className="lede small">Saved as a draft with the next order number. Confirm it once every line has a promised date.</p></header>
    <form className="panel" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
      <div className="form-grid four">
        <label>Customer<select value={customerId} onChange={(e) => setCustomerId(e.target.value)} required><option value="" disabled>Choose a customer</option>{customers.map((c) => <option key={c.id} value={c.id}>{c.code} · {c.name}</option>)}</select></label>
        <label>Customer PO / reference <span className="optional">OPTIONAL</span><input value={reference} onChange={(e) => setReference(e.target.value)} maxLength={80} /></label>
        <label>Fulfilling site<select value={siteId} onChange={(e) => setSiteId(e.target.value)} required>{sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
        <label>Order date<input type="date" value={orderDate} onChange={(e) => setOrderDate(e.target.value)} required /></label>
      </div>
      <div className="table-wrap"><table className="data-table line-editor">
        <thead><tr><th scope="col">#</th><th scope="col">Item</th><th scope="col">Quantity</th><th scope="col">Requested</th><th scope="col">Promised <span className="optional-inline">optional</span></th><th scope="col"><span className="sr-only">Remove</span></th></tr></thead>
        <tbody>{lines.map((l, i) => <tr key={i} className="static-row">
          <td>{i + 1}</td>
          <td><select aria-label={`Line ${i + 1} item`} value={l.item_id} onChange={(e) => set(i, "item_id", e.target.value)} required><option value="" disabled>Choose an item</option>{items.map((it) => <option key={it.id} value={it.id}>{it.code} · {it.name}</option>)}</select></td>
          <td><input aria-label={`Line ${i + 1} quantity`} inputMode="decimal" value={l.quantity} onChange={(e) => set(i, "quantity", e.target.value)} required placeholder={unitOf(l.item_id) ? "0" : ""} /></td>
          <td><input aria-label={`Line ${i + 1} requested date`} type="date" value={l.requested_date} onChange={(e) => set(i, "requested_date", e.target.value)} required /></td>
          <td><input aria-label={`Line ${i + 1} promised date`} type="date" value={l.promised_date} onChange={(e) => set(i, "promised_date", e.target.value)} /></td>
          <td>{lines.length > 1 && <button type="button" className="icon-button small" aria-label={`Remove line ${i + 1}`} onClick={() => setLines((ls) => ls.filter((_, j) => j !== i))}><Trash2 size={13} /></button>}</td>
        </tr>)}</tbody>
      </table></div>
      <div><button type="button" className="quiet-button" onClick={() => setLines((ls) => [...ls, emptyLine()])}><Plus size={14} /> Add line</button></div>
      <label className="notes-field">Notes <span className="optional">OPTIONAL</span><textarea rows={2} maxLength={2000} value={notes} onChange={(e) => setNotes(e.target.value)} /></label>
      {create.error && <div className="form-error" role="alert"><AlertCircle size={15} />{create.error.message}</div>}
      <div className="form-actions"><a className="quiet-button" href="#orders">Cancel</a><button className="primary-button compact" type="submit" disabled={create.isPending}>{create.isPending ? <LoaderCircle className="spin" size={15} /> : <Check size={15} />} Save draft order</button></div>
    </form>
  </section>;
}

type Action =
  | { kind: "cancel" }
  | { kind: "promise"; line: OrderLine }
  | { kind: "short"; line: OrderLine }
  | { kind: "edit"; line: OrderLine }
  | { kind: "add" };

function OrderView({ id, canManage }: { id: string; canManage: boolean }) {
  const queryClient = useQueryClient();
  const order = useQuery({ queryKey: ["order", id], queryFn: () => api<OrderDetail>(`/api/v1/orders/${id}`) });
  const [action, setAction] = useState<Action | null>(null);
  const [history, setHistory] = useState<string | null>(null);
  const done = (value: OrderDetail) => { queryClient.setQueryData(["order", id], value); void queryClient.invalidateQueries({ queryKey: ["orders"] }); setAction(null); };
  const confirm = useMutation({ mutationFn: (version: number) => api<OrderDetail>(`/api/v1/orders/${id}/confirm`, { method: "POST", body: JSON.stringify({ version }) }), onSuccess: done });
  if (order.isPending) return <section className="wrap page"><div className="table-state"><LoaderCircle className="spin" size={16} /> Loading…</div></section>;
  if (order.isError) return <section className="wrap page"><a className="back-link" href="#orders"><ArrowLeft size={15} /> Orders</a><div className="form-error" role="alert"><AlertCircle size={15} />{order.error.message}</div></section>;
  const o = order.data;
  const active = o.status === "draft" || o.status === "confirmed";
  const missingPromise = o.lines.filter((l) => l.status === "open" && !l.promised_date).length;
  return <section className="wrap page">
    <a className="back-link" href="#orders"><ArrowLeft size={15} /> Orders</a>
    <header className="page-head order-head">
      <div><span className="eyebrow">{o.customer_code} · {o.site_name.toUpperCase()}</span><h1 className="page-title">{o.number} <Badge status={o.status} /></h1></div>
      <dl className="facts">
        <div><dt>Customer</dt><dd>{o.customer_name}</dd></div>
        <div><dt>Customer PO</dt><dd className="mono">{o.customer_reference ?? "—"}</dd></div>
        <div><dt>Ordered</dt><dd>{fmtDate(o.order_date)}</dd></div>
        {o.confirmed_at && <div><dt>Confirmed</dt><dd>{new Date(o.confirmed_at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</dd></div>}
      </dl>
    </header>
    {o.status_reason && <div className="notice-line"><AlertCircle size={16} /><span>{STATUS_LABEL[o.status]}: {o.status_reason}</span></div>}
    {canManage && active && <div className="action-bar">
      {o.status === "draft" && <button className="primary-button compact" disabled={confirm.isPending || missingPromise > 0} title={missingPromise ? "Every line needs a promised date first" : undefined} onClick={() => confirm.mutate(o.version)}><Check size={15} /> Confirm order</button>}
      {o.status === "draft" && missingPromise > 0 && <span className="hint">{missingPromise} line{missingPromise > 1 ? "s need" : " needs"} a promised date before confirming.</span>}
      <span className="toolbar-spacer" />
      <button className="quiet-button" onClick={() => setAction({ kind: "add" })}><Plus size={14} /> Add line</button>
      <button className="quiet-button danger" onClick={() => setAction({ kind: "cancel" })}>Cancel order</button>
    </div>}
    {confirm.error && <div className="form-error" role="alert"><AlertCircle size={15} />{confirm.error.message}</div>}
    <div className="panel data-panel">
      <div className="table-wrap"><table className="data-table order-lines">
        <thead><tr><th scope="col">#</th><th scope="col">Item</th><th scope="col" className="num">Ordered</th><th scope="col" className="num">Shipped</th><th scope="col" className="num">Closed</th><th scope="col" className="num">Remaining</th><th scope="col">Requested</th><th scope="col">Promised</th><th scope="col">Status</th>{canManage && active && <th scope="col"><span className="sr-only">Actions</span></th>}</tr></thead>
        <tbody>{o.lines.map((l) => <LineRow key={l.id} line={l} order={o} canManage={canManage && active} showHistory={history === l.id} onToggleHistory={() => setHistory(history === l.id ? null : l.id)} onAction={setAction} />)}</tbody>
      </table></div>
      <p className="hint">Remaining = ordered − shipped − closed. Shipments appear here once dispatch is recorded.</p>
    </div>
    {o.notes && <div className="panel"><span className="field-label">Notes</span><p className="notes-text">{o.notes}</p></div>}
    {action && <ActionDialog action={action} order={o} onClose={() => setAction(null)} onDone={done} />}
  </section>;
}

function LineRow({ line: l, order, canManage, showHistory, onToggleHistory, onAction }: {
  line: OrderLine; order: OrderDetail; canManage: boolean; showHistory: boolean; onToggleHistory: () => void; onAction: (a: Action) => void;
}) {
  const closed = (Number(l.cancelled_qty) + Number(l.short_closed_qty)).toString();
  const changes = l.promise_history.length;
  return <>
    <tr className="static-row">
      <td data-label="Line">{l.line_no}</td>
      <td className="item-cell"><b className="mono">{l.item_code}</b><small className="cell-sub">{l.item_name}</small></td>
      <td className="num" data-label="Ordered">{l.ordered_qty} <small>{l.unit_code}</small></td>
      <td className="num" data-label="Shipped">{l.shipped_qty}</td>
      <td className="num" data-label="Closed">{closed}</td>
      <td className="num strong" data-label="Remaining">{l.remaining_qty}</td>
      <td className="date" data-label="Requested">{fmtDate(l.requested_date)}</td>
      <td className="date" data-label="Promised">{fmtDate(l.promised_date)}{changes > 0 && <button className="text-button history-toggle" onClick={onToggleHistory} aria-expanded={showHistory}><History size={12} /> {changes === 1 ? "history" : `${changes - 1} change${changes > 2 ? "s" : ""}`}</button>}</td>
      <td data-label="Status"><Badge status={l.status} />{l.status_reason && <small className="cell-sub">{l.status_reason}</small>}</td>
      {canManage && <td className="row-actions">{l.status === "open" && <>
        {order.status === "draft" && <button className="text-button" onClick={() => onAction({ kind: "edit", line: l })}>Edit</button>}
        {order.status === "confirmed" && <>
          <button className="text-button" onClick={() => onAction({ kind: "promise", line: l })}>Change promise</button>
          <button className="text-button" onClick={() => onAction({ kind: "edit", line: l })}>Amend qty</button>
          <button className="text-button" onClick={() => onAction({ kind: "short", line: l })}>Short-close</button>
        </>}
      </>}</td>}
    </tr>
    {showHistory && <tr className="static-row history-row"><td /><td colSpan={canManage ? 9 : 8}>
      <ol className="timeline">{l.promise_history.map((h, i) => <li key={i}><b>{h.previous_date ? `${fmtDate(h.previous_date)} → ${fmtDate(h.new_date)}` : fmtDate(h.new_date)}</b><span>{REASON_LABEL[h.reason_code] ?? h.reason_code}{h.note ? ` — ${h.note}` : ""}</span><small>{h.changed_by_label?.split(" <")[0] ?? "Unknown user"} · {new Date(h.changed_at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</small></li>)}</ol>
    </td></tr>}
  </>;
}

function ActionDialog({ action, order, onClose, onDone }: { action: Action; order: OrderDetail; onClose: () => void; onDone: (o: OrderDetail) => void }) {
  const { items } = useLookups();
  const line = "line" in action ? action.line : null;
  const [reason, setReason] = useState("");
  const [reasonCode, setReasonCode] = useState("supplier_delay");
  const [date, setDate] = useState(line?.promised_date ?? "");
  const [quantity, setQuantity] = useState(line ? String(Number(line.ordered_qty)) : "");
  const [requested, setRequested] = useState(line?.requested_date ?? "");
  const [itemId, setItemId] = useState("");
  useEffect(() => { const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); }; window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k); }, [onClose]);
  const base = `/api/v1/orders/${order.id}`;
  const submit = useMutation({
    mutationFn: () => {
      const send = (path: string, body: object, method = "POST") => api<OrderDetail>(path, { method, body: JSON.stringify(body) });
      switch (action.kind) {
        case "cancel": return send(`${base}/cancel`, { version: order.version, reason });
        case "short": return send(`${base}/lines/${action.line.id}/short-close`, { version: action.line.version, reason });
        case "promise": return send(`${base}/lines/${action.line.id}/promise`, { version: action.line.version, new_date: date, reason_code: reasonCode, note: reason });
        case "edit": {
          const body: Record<string, unknown> = { version: action.line.version, quantity };
          if (order.status === "draft") { body["requested_date"] = requested; body["promised_date"] = date || null; }
          return send(`${base}/lines/${action.line.id}`, body, "PATCH");
        }
        case "add": return send(`${base}/lines`, { order_version: order.version, item_id: itemId, quantity, requested_date: requested, promised_date: date || null });
      }
    },
    onSuccess: onDone,
  });
  const titles = { cancel: `Cancel ${order.number}`, short: `Short-close line ${line?.line_no}`, promise: `Change promise · line ${line?.line_no}`, edit: order.status === "draft" ? `Edit line ${line?.line_no}` : `Amend quantity · line ${line?.line_no}`, add: "Add a line" };
  const stale = (submit.error as ApiError | null)?.status === 409;
  return <div className="dialog-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <form className="dialog" role="dialog" aria-modal="true" aria-labelledby="action-title" onSubmit={(e) => { e.preventDefault(); submit.mutate(); }}>
      <header><div><span className="eyebrow">{order.number}</span><h2 id="action-title">{titles[action.kind]}</h2></div><button type="button" className="icon-button" onClick={onClose} aria-label="Close"><X size={16} /></button></header>
      <div className="dialog-grid">
        {action.kind === "promise" && <>
          <label>New promised date<input type="date" value={date} onChange={(e) => setDate(e.target.value)} required autoFocus /></label>
          <label>Reason<select value={reasonCode} onChange={(e) => setReasonCode(e.target.value)}>{REASONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
          <label className="wide">Note <span className="optional">OPTIONAL</span><input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} placeholder="e.g. Coating batch returned short" /></label>
        </>}
        {(action.kind === "cancel" || action.kind === "short") && <label className="wide">Reason<input value={reason} onChange={(e) => setReason(e.target.value)} required minLength={3} maxLength={500} autoFocus placeholder={action.kind === "cancel" ? "Why is this order cancelled?" : "Why will the rest not be delivered?"} /></label>}
        {action.kind === "short" && <p className="hint wide">{line?.remaining_qty} {line?.unit_code} still open will be closed and no longer owed.</p>}
        {action.kind === "add" && <label className="wide">Item<select value={itemId} onChange={(e) => setItemId(e.target.value)} required><option value="" disabled>Choose an item</option>{items.map((it) => <option key={it.id} value={it.id}>{it.code} · {it.name}</option>)}</select></label>}
        {(action.kind === "edit" || action.kind === "add") && <label>Quantity{line && <span className="optional">{line.unit_code}</span>}<input inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} required autoFocus /></label>}
        {(action.kind === "add" || (action.kind === "edit" && order.status === "draft")) && <>
          <label>Requested date<input type="date" value={requested} onChange={(e) => setRequested(e.target.value)} required /></label>
          <label>Promised date{order.status === "draft" && <span className="optional">OPTIONAL</span>}<input type="date" value={date} onChange={(e) => setDate(e.target.value)} required={order.status === "confirmed"} /></label>
        </>}
      </div>
      {submit.error && <div className="form-error" role="alert"><AlertCircle size={15} /><span>{submit.error.message}{stale && " Close this and reopen the order to see the latest version."}</span></div>}
      <footer><span className="toolbar-spacer" /><button type="button" className="quiet-button" onClick={onClose}>Back</button><button type="submit" className={`primary-button compact ${action.kind === "cancel" ? "danger-fill" : ""}`} disabled={submit.isPending}>{submit.isPending ? <LoaderCircle className="spin" size={15} /> : <Check size={15} />} {action.kind === "cancel" ? "Cancel order" : "Save"}</button></footer>
    </form>
  </div>;
}

const ORDER_TEMPLATE = "customer_reference,customer_code,item_code,quantity,requested_date,promised_date,order_date,notes\n";

function OrderImport() {
  const { sites } = useLookups();
  const queryClient = useQueryClient();
  const [siteId, setSiteId] = useState("");
  const [csvText, setCsvText] = useState("");
  const [fileName, setFileName] = useState("");
  const [report, setReport] = useState<OrderImportReport | null>(null);
  useEffect(() => { if (!siteId && sites[0]) setSiteId(sites[0].id); }, [sites, siteId]);
  const run = useMutation({
    mutationFn: (commit: boolean) => api<OrderImportReport>("/api/v1/orders/import", { method: "POST", body: JSON.stringify({ site_id: siteId, csv_text: csvText, commit }) }),
    onSuccess: (value) => { setReport(value); if (value.committed) void queryClient.invalidateQueries({ queryKey: ["orders"] }); },
    onError: (error: ApiError) => { const body = error.body as OrderImportReport | undefined; if (body && "errors" in body) setReport(body); },
  });
  return <section className="wrap page">
    <a className="back-link" href="#orders"><ArrowLeft size={15} /> Orders</a>
    <header className="page-head"><div><span className="eyebrow">CUSTOMER COMMITMENTS</span><h1 className="page-title">Import orders</h1></div><p className="lede small">One row per order line; rows with the same customer and PO reference become one draft order. Preview first; a file with any problem is rejected as a whole, and re-importing creates nothing new.</p></header>
    <div className="panel data-panel">
      <div className="import-controls">
        <label>Fulfilling site<select value={siteId} onChange={(e) => { setSiteId(e.target.value); setReport(null); }}>{sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
        <label>CSV file (max 500 KB)<input type="file" accept=".csv,text/csv" onChange={(e) => { const f = e.target.files?.[0]; setReport(null); setCsvText(""); setFileName(f?.name ?? ""); if (f && f.size <= 500_000) void f.text().then(setCsvText); }} /></label>
        <a className="text-link" href={`data:text/csv;charset=utf-8,${encodeURIComponent(ORDER_TEMPLATE)}`} download="orders-template.csv">Download a blank template</a>
      </div>
      <div className="import-actions">
        <button className="quiet-button" disabled={!csvText || !siteId || run.isPending} onClick={() => run.mutate(false)}>Preview {fileName && `“${fileName}”`}</button>
        <button className="primary-button compact" disabled={!report || report.committed || report.errors.length > 0 || report.orders_to_create === 0 || run.isPending} onClick={() => run.mutate(true)}><Check size={15} /> Create {report?.orders_to_create ?? ""} draft {report?.orders_to_create === 1 ? "order" : "orders"}</button>
      </div>
      {run.error && !report && <div className="form-error" role="alert"><AlertCircle size={15} />{run.error.message}</div>}
      {report && <div className="import-report" aria-live="polite">
        <div className="report-stats"><span><b>{report.total_rows}</b> rows</span><span><b>{report.orders_to_create}</b> new orders</span><span><b>{report.lines_to_create}</b> lines</span><span><b>{report.unchanged_orders}</b> already present</span><span className={report.errors.length ? "bad" : "good"}><b>{report.errors.length}</b> {report.errors.length === 1 ? "problem" : "problems"}</span></div>
        {report.committed && <p className="success-line"><Check size={14} /> Created {report.created_numbers.join(", ") || "nothing new"}.</p>}
        {report.errors.length > 0 && <div className="table-wrap"><table className="data-table compact-table"><thead><tr><th scope="col">Row</th><th scope="col">Column</th><th scope="col">Problem</th></tr></thead><tbody>{report.errors.map((err, i) => <tr key={i} className="static-row"><td>{err.row}</td><td className="mono">{err.field ?? "—"}</td><td>{err.message}</td></tr>)}</tbody></table></div>}
      </div>}
    </div>
  </section>;
}
