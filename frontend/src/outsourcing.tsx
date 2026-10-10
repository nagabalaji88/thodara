import { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, Check, LoaderCircle, Plus, Search, Send, Truck, X } from "lucide-react";
import { api, type ApiError } from "./api";
import { Badge, fmtDate, useLookups } from "./orders";
import type { AllocationCandidate, BatchDetail, BatchSummary, MasterRecord, Page } from "./types";

const today = () => new Date().toISOString().slice(0, 10);

/** Extra panels rendered on the batch page by later slices (supplier updates). */
export type BatchExtras = (batch: BatchDetail, onChange: (b: BatchDetail) => void) => React.ReactNode;

export function OutsourcingPage({ sub, permissions, extras, summaryExtra }: {
  sub: string; permissions: string[]; extras?: BatchExtras; summaryExtra?: { header: string; cell: (b: BatchSummary) => React.ReactNode };
}) {
  const canManage = permissions.includes("outsourcing:manage");
  const [path, query = ""] = sub.split("?");
  if (path === "new" && canManage) return <NewBatch prefill={new URLSearchParams(query)} />;
  if (path && path !== "new") return <BatchView id={path} canManage={canManage} extras={extras} />;
  return <BatchList canManage={canManage} summaryExtra={summaryExtra} />;
}

function BatchList({ canManage, summaryExtra }: { canManage: boolean; summaryExtra?: { header: string; cell: (b: BatchSummary) => React.ReactNode } }) {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const limit = 25;
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (q.trim()) params.set("q", q.trim());
  if (status) params.set("status", status);
  const list = useQuery({ queryKey: ["batches", q, status, offset], queryFn: () => api<Page<BatchSummary>>(`/api/v1/outsourcing/batches?${params}`), placeholderData: keepPreviousData });
  useEffect(() => setOffset(0), [q, status]);
  const total = list.data?.total ?? 0;
  return <section className="wrap page">
    <header className="page-head"><div><span className="eyebrow">WORK OUTSIDE THE FACTORY</span><h1 className="page-title">Outsourcing</h1></div><p className="lede small">Every batch sent to a job-work supplier, the customer orders waiting on it, and what the supplier last told you.</p></header>
    <div className="panel data-panel">
      <div className="toolbar">
        <label className="search-field"><Search size={14} /><input aria-label="Search batches" placeholder="Batch, supplier, item, operation or challan" value={q} maxLength={80} onChange={(e) => setQ(e.target.value)} /></label>
        <select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All statuses</option><option value="planned">Planned</option><option value="at_supplier">At supplier</option><option value="closed">Closed</option><option value="cancelled">Cancelled</option></select>
        <span className="toolbar-spacer" />
        {canManage && <a className="primary-button compact" href="#outsourcing/new"><Plus size={15} /> New batch</a>}
      </div>
      {list.isError ? <div className="form-error" role="alert"><AlertCircle size={15} />{list.error.message}</div>
        : list.isPending ? <div className="table-state"><LoaderCircle className="spin" size={16} /> Loading…</div>
          : total === 0 ? <div className="table-state">{q || status ? "No batches match." : "No outsourced batches yet."}</div>
            : <div className="table-wrap"><table className="data-table">
              <thead><tr><th scope="col">Batch</th><th scope="col">Supplier</th><th scope="col">Item · operation</th><th scope="col" className="num">Quantity</th><th scope="col">Orders</th><th scope="col">Sent</th><th scope="col">Expected back</th>{summaryExtra && <th scope="col">{summaryExtra.header}</th>}<th scope="col">Status</th></tr></thead>
              <tbody>{list.data.items.map((b) => <tr key={b.id} tabIndex={0} aria-label={`Open ${b.number}`} onClick={() => { window.location.hash = `outsourcing/${b.id}`; }} onKeyDown={(e) => { if (e.key === "Enter") window.location.hash = `outsourcing/${b.id}`; }}>
                <td className="mono">{b.number}</td><td>{b.supplier_name}</td><td><b className="mono">{b.item_code}</b><small className="cell-sub">{b.operation}</small></td>
                <td className="num">{b.quantity} <small>{b.unit_code}</small></td><td>{b.order_count === 0 ? <span className="muted-inline">None</span> : `${b.order_count} · ${b.allocated_qty} ${b.unit_code}`}</td>
                <td className="date">{fmtDate(b.sent_date)}</td><td className="date">{fmtDate(b.expected_return_date)}</td>{summaryExtra && <td>{summaryExtra.cell(b)}</td>}<td><Badge status={b.status} /></td>
              </tr>)}</tbody>
            </table></div>}
      {total > limit && <div className="pager"><span>{offset + 1}–{Math.min(offset + limit, total)} of {total}</span><button className="quiet-button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>Previous</button><button className="quiet-button" disabled={offset + limit >= total} onClick={() => setOffset(offset + limit)}>Next</button></div>}
    </div>
  </section>;
}

function useCandidates(itemId: string, siteId: string) {
  return useQuery({
    queryKey: ["candidates", itemId, siteId],
    queryFn: () => api<AllocationCandidate[]>(`/api/v1/outsourcing/candidates?item_id=${itemId}&site_id=${siteId}`),
    enabled: Boolean(itemId && siteId),
  });
}

function NewBatch({ prefill }: { prefill: URLSearchParams }) {
  const { items, sites } = useLookups();
  const suppliers = useQuery({ queryKey: ["md", "suppliers", "lookup"], queryFn: () => api<Page<MasterRecord>>("/api/v1/master-data/suppliers?status=active&limit=200") });
  const jobWorkers = (suppliers.data?.items ?? []).filter((s) => s.provides_job_work);
  const queryClient = useQueryClient();
  const [siteId, setSiteId] = useState(prefill.get("site") ?? "");
  const [supplierId, setSupplierId] = useState("");
  const [itemId, setItemId] = useState(prefill.get("item") ?? "");
  const [operation, setOperation] = useState(prefill.get("operation") ?? "");
  const [quantity, setQuantity] = useState("");
  const [expected, setExpected] = useState("");
  const [notes, setNotes] = useState("");
  const [picked, setPicked] = useState<Record<string, string>>({});
  useEffect(() => { if (!siteId && sites[0]) setSiteId(sites[0].id); }, [sites, siteId]);
  const candidates = useCandidates(itemId, siteId);
  const preselect = prefill.get("component");
  useEffect(() => {
    const match = candidates.data?.find((c) => c.component_id === preselect);
    if (match) { setPicked({ [match.component_id]: match.open_qty }); setQuantity((q) => q || match.open_qty); if (!operation && match.outsourced_operation) setOperation(match.outsourced_operation); }
  }, [candidates.data, preselect]); // eslint-disable-line react-hooks/exhaustive-deps
  const allocatedTotal = Object.values(picked).reduce((sum, v) => sum + (Number(v) || 0), 0);
  const create = useMutation({
    mutationFn: () => api<BatchDetail>("/api/v1/outsourcing/batches", { method: "POST", body: JSON.stringify({
      site_id: siteId, supplier_id: supplierId, item_id: itemId, operation, quantity, expected_return_date: expected, notes,
      allocations: Object.entries(picked).map(([component_id, qty]) => ({ component_id, quantity: qty })),
    }) }),
    onSuccess: (batch) => { void queryClient.invalidateQueries({ queryKey: ["batches"] }); void queryClient.invalidateQueries({ queryKey: ["order"] }); window.location.hash = `outsourcing/${batch.id}`; },
  });
  return <section className="wrap page">
    <a className="back-link" href="#outsourcing"><ArrowLeft size={15} /> Outsourcing</a>
    <header className="page-head"><div><span className="eyebrow">NEW OUTSOURCED BATCH</span><h1 className="page-title">New batch</h1></div><p className="lede small">One item, one operation, one supplier. Link it to the customer orders it serves so a delay here shows up on those orders.</p></header>
    <form className="panel" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
      <div className="form-grid four">
        <label>Item sent<select value={itemId} onChange={(e) => { setItemId(e.target.value); setPicked({}); }} required><option value="" disabled>Choose an item</option>{items.map((it) => <option key={it.id} value={it.id}>{it.code} · {it.name}</option>)}</select></label>
        <label>Operation<input value={operation} onChange={(e) => setOperation(e.target.value)} maxLength={80} required placeholder="e.g. Powder coating" /></label>
        <label>Job-work supplier<select value={supplierId} onChange={(e) => setSupplierId(e.target.value)} required><option value="" disabled>{jobWorkers.length ? "Choose a supplier" : "No job-work suppliers yet"}</option>{jobWorkers.map((s) => <option key={s.id} value={s.id}>{s.code} · {s.name}</option>)}</select></label>
        <label>Site<select value={siteId} onChange={(e) => { setSiteId(e.target.value); setPicked({}); }} required>{sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
        <label>Quantity<input inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} required /></label>
        <label>Expected back<input type="date" value={expected} onChange={(e) => setExpected(e.target.value)} required /></label>
        <label className="span-2">Notes <span className="optional">OPTIONAL</span><input value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={2000} /></label>
      </div>
      {jobWorkers.length === 0 && suppliers.isSuccess && <p className="hint">Mark a supplier as providing job work under Master data → Suppliers first.</p>}
      <fieldset className="dep-fieldset">
        <legend>Customer orders waiting for this item <span className="hint">Open lines of confirmed orders at this site that still need it. Allocated {allocatedTotal} of {quantity || 0}.</span></legend>
        {!itemId ? <p className="muted-line">Choose the item first.</p>
          : candidates.isPending ? <p className="muted-line">Loading…</p>
            : (candidates.data ?? []).length === 0 ? <p className="muted-line">No open order lines need this item. You can still create the batch and link orders later.</p>
              : <div className="table-wrap"><table className="data-table compact-table">
                <thead><tr><th scope="col"><span className="sr-only">Use</span></th><th scope="col">Order</th><th scope="col">Customer</th><th scope="col">Promised</th><th scope="col">Step</th><th scope="col" className="num">Still open</th><th scope="col" className="num">From this batch</th></tr></thead>
                <tbody>{candidates.data!.map((c) => { const on = c.component_id in picked; return <tr key={c.component_id} className="static-row">
                  <td><input type="checkbox" aria-label={`Use for ${c.order_number} line ${c.line_no}`} checked={on} onChange={(e) => setPicked((p) => { const next = { ...p }; if (e.target.checked) next[c.component_id] = c.open_qty; else delete next[c.component_id]; return next; })} /></td>
                  <td className="mono">{c.order_number} / {c.line_no}<small className="cell-sub">{c.line_item_code}</small></td><td>{c.customer_name}</td><td className="date">{fmtDate(c.promised_date)}</td><td>{c.outsourced_operation ?? "—"}</td>
                  <td className="num">{c.open_qty}</td>
                  <td className="num">{on ? <input className="qty-input" aria-label={`Quantity for ${c.order_number} line ${c.line_no}`} inputMode="decimal" value={picked[c.component_id]} onChange={(e) => setPicked((p) => ({ ...p, [c.component_id]: e.target.value }))} /> : "—"}</td>
                </tr>; })}</tbody>
              </table></div>}
      </fieldset>
      {create.error && <div className="form-error" role="alert"><AlertCircle size={15} />{create.error.message}</div>}
      <div className="form-actions"><a className="quiet-button" href="#outsourcing">Cancel</a><button className="primary-button compact" type="submit" disabled={create.isPending}>{create.isPending ? <LoaderCircle className="spin" size={15} /> : <Check size={15} />} Create planned batch</button></div>
    </form>
  </section>;
}

type BatchAction = "send" | "edit" | "allocate" | "cancel" | "close";

function BatchView({ id, canManage, extras }: { id: string; canManage: boolean; extras?: BatchExtras }) {
  const queryClient = useQueryClient();
  const batch = useQuery({ queryKey: ["batch", id], queryFn: () => api<BatchDetail>(`/api/v1/outsourcing/batches/${id}`) });
  const [action, setAction] = useState<BatchAction | null>(null);
  const done = (value: BatchDetail) => { queryClient.setQueryData(["batch", id], value); void queryClient.invalidateQueries({ queryKey: ["batches"] }); void queryClient.invalidateQueries({ queryKey: ["order"] }); setAction(null); };
  const unallocate = useMutation({
    mutationFn: (allocationId: string) => api<BatchDetail>(`/api/v1/outsourcing/batches/${id}/allocations/${allocationId}?version=${batch.data!.version}`, { method: "DELETE" }),
    onSuccess: done,
  });
  if (batch.isPending) return <section className="wrap page"><div className="table-state"><LoaderCircle className="spin" size={16} /> Loading…</div></section>;
  if (batch.isError) return <section className="wrap page"><a className="back-link" href="#outsourcing"><ArrowLeft size={15} /> Outsourcing</a><div className="form-error" role="alert"><AlertCircle size={15} />{batch.error.message}</div></section>;
  const b = batch.data;
  const active = b.status === "planned" || b.status === "at_supplier";
  const free = Number(b.quantity) - Number(b.allocated_qty);
  return <section className="wrap page">
    <a className="back-link" href="#outsourcing"><ArrowLeft size={15} /> Outsourcing</a>
    <header className="page-head order-head">
      <div><span className="eyebrow">{b.supplier_code} · {b.site_name.toUpperCase()}</span><h1 className="page-title">{b.number} <Badge status={b.status} /></h1></div>
      <dl className="facts">
        <div><dt>Supplier</dt><dd>{b.supplier_name}</dd></div>
        <div><dt>Item · operation</dt><dd><span className="mono">{b.item_code}</span> · {b.operation}</dd></div>
        <div><dt>Quantity</dt><dd>{b.quantity} {b.unit_code}</dd></div>
        <div><dt>Expected back</dt><dd>{fmtDate(b.expected_return_date)}</dd></div>
        {b.sent_date && <div><dt>Sent</dt><dd>{fmtDate(b.sent_date)}</dd></div>}
        {b.challan_reference && <div><dt>Challan</dt><dd className="mono">{b.challan_reference}</dd></div>}
      </dl>
    </header>
    {b.status_reason && <div className="notice-line"><AlertCircle size={16} /><span>{b.status === "closed" ? "Closed" : "Cancelled"}: {b.status_reason}</span></div>}
    {canManage && active && <div className="action-bar">
      {b.status === "planned" && <button className="primary-button compact" onClick={() => setAction("send")}><Send size={15} /> Record sent to supplier</button>}
      <span className="toolbar-spacer" />
      <button className="quiet-button" onClick={() => setAction("allocate")} disabled={free <= 0}><Plus size={14} /> Link an order</button>
      <button className="quiet-button" onClick={() => setAction("edit")}>Edit</button>
      {b.status === "planned" ? <button className="quiet-button danger" onClick={() => setAction("cancel")}>Cancel batch</button> : <button className="quiet-button danger" onClick={() => setAction("close")}>Close batch</button>}
    </div>}
    {extras?.(b, done)}
    <section className="panel data-panel" aria-labelledby="alloc-title">
      <div><span className="eyebrow">DEPENDENT CUSTOMER ORDERS</span><h2 id="alloc-title" className="panel-title">Orders waiting on this batch</h2></div>
      {b.allocations.length === 0 ? <p className="muted-line">Not linked to any order line. {free > 0 && "A delay here will not show on any customer order until you link one."}</p>
        : <div className="table-wrap"><table className="data-table compact-table">
          <thead><tr><th scope="col">Order / line</th><th scope="col">Customer</th><th scope="col">Promised</th><th scope="col" className="num">Line needs</th><th scope="col" className="num">From this batch</th>{canManage && active && <th scope="col"><span className="sr-only">Actions</span></th>}</tr></thead>
          <tbody>{b.allocations.map((a) => <tr key={a.id} className="static-row">
            <td><a className="mono" href={`#orders/${a.order_id}`}>{a.order_number} / {a.line_no}</a><small className="cell-sub">{a.line_item_code}</small></td>
            <td>{a.customer_name}</td><td className="date">{fmtDate(a.promised_date)}</td>
            <td className="num">{a.component_required_qty} <small>{b.unit_code}</small></td><td className="num strong">{a.quantity} <small>{b.unit_code}</small></td>
            {canManage && active && <td className="row-actions"><button className="text-button" disabled={unallocate.isPending} onClick={() => unallocate.mutate(a.id)}>Unlink</button></td>}
          </tr>)}</tbody>
        </table></div>}
      <p className="hint">{b.allocated_qty} of {b.quantity} {b.unit_code} linked to orders{free > 0 ? `; ${free} ${b.unit_code} not linked (spare or for future orders)` : ""}.</p>
      {unallocate.error && <div className="form-error" role="alert"><AlertCircle size={15} />{unallocate.error.message}</div>}
    </section>
    <section className="panel" aria-labelledby="custody-title">
      <div><span className="eyebrow">CUSTODY</span><h2 id="custody-title" className="panel-title">Material movements</h2></div>
      {b.movements.length === 0 ? <p className="muted-line">Nothing has left the factory yet.</p>
        : <ol className="timeline">{b.movements.map((m, i) => <li key={i}><b><Truck size={13} /> {m.kind === "sent_to_supplier" ? "Sent to supplier" : m.kind} · {m.quantity} {b.unit_code}</b><span>{fmtDate(m.movement_date)}{m.document_reference ? ` · challan ${m.document_reference}` : ""}</span><small>{m.recorded_by_label?.split(" <")[0] ?? "Unknown user"} · recorded {new Date(m.recorded_at).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</small></li>)}</ol>}
    </section>
    {b.notes && <div className="panel"><span className="field-label">Notes</span><p className="notes-text">{b.notes}</p></div>}
    {action && <BatchDialog action={action} batch={b} onClose={() => setAction(null)} onDone={done} />}
  </section>;
}

function BatchDialog({ action, batch: b, onClose, onDone }: { action: BatchAction; batch: BatchDetail; onClose: () => void; onDone: (b: BatchDetail) => void }) {
  const [date, setDate] = useState(action === "send" ? today() : b.expected_return_date);
  const [reference, setReference] = useState("");
  const [reason, setReason] = useState("");
  const [quantity, setQuantity] = useState(b.quantity);
  const [operation, setOperation] = useState(b.operation);
  const [notes, setNotes] = useState(b.notes ?? "");
  const [componentId, setComponentId] = useState("");
  const [allocQty, setAllocQty] = useState("");
  const candidates = useCandidates(action === "allocate" ? b.item_id : "", b.site_id);
  const linked = useMemo(() => new Set(b.allocations.map((a) => a.component_id)), [b.allocations]);
  const options = (candidates.data ?? []).filter((c) => !linked.has(c.component_id));
  useEffect(() => { const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); }; window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k); }, [onClose]);
  const base = `/api/v1/outsourcing/batches/${b.id}`;
  const submit = useMutation({
    mutationFn: () => {
      const send = (path: string, body: object, method = "POST") => api<BatchDetail>(path, { method, body: JSON.stringify(body) });
      switch (action) {
        case "send": return send(`${base}/send`, { version: b.version, sent_date: date, challan_reference: reference });
        case "cancel": return send(`${base}/cancel`, { version: b.version, reason });
        case "close": return send(`${base}/close`, { version: b.version, reason });
        case "allocate": return send(`${base}/allocations`, { version: b.version, component_id: componentId, quantity: allocQty });
        case "edit": return send(base, b.status === "planned" ? { version: b.version, quantity, operation, expected_return_date: date, notes } : { version: b.version, notes }, "PATCH");
      }
    },
    onSuccess: onDone,
  });
  const titles: Record<BatchAction, string> = { send: "Record sent to supplier", edit: `Edit ${b.number}`, allocate: "Link a customer order", cancel: `Cancel ${b.number}`, close: `Close ${b.number}` };
  const stale = (submit.error as ApiError | null)?.status === 409;
  return <div className="dialog-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <form className="dialog" role="dialog" aria-modal="true" aria-labelledby="batch-action-title" onSubmit={(e) => { e.preventDefault(); submit.mutate(); }}>
      <header><div><span className="eyebrow">{b.number} · {b.supplier_name}</span><h2 id="batch-action-title">{titles[action]}</h2></div><button type="button" className="icon-button" onClick={onClose} aria-label="Close"><X size={16} /></button></header>
      <div className="dialog-grid">
        {action === "send" && <>
          <label>Sent on<input type="date" value={date} max={today()} onChange={(e) => setDate(e.target.value)} required autoFocus /></label>
          <label>Delivery challan <span className="optional">OPTIONAL</span><input value={reference} onChange={(e) => setReference(e.target.value)} maxLength={80} placeholder="e.g. DC-1182" /></label>
          <p className="hint wide">Records {b.quantity} {b.unit_code} {b.item_code} as handed over to {b.supplier_name}.</p>
        </>}
        {(action === "cancel" || action === "close") && <label className="wide">Reason<input value={reason} onChange={(e) => setReason(e.target.value)} required minLength={3} maxLength={500} autoFocus placeholder={action === "cancel" ? "Why is this batch not going ahead?" : "Why is this batch being closed without receipts?"} /></label>}
        {(action === "cancel" || action === "close") && b.allocations.length > 0 && <p className="hint wide">The {b.allocated_qty} {b.unit_code} linked to customer orders will be unlinked; those orders will need another batch.</p>}
        {action === "edit" && b.status === "planned" && <>
          <label>Quantity<input inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} required /></label>
          <label>Expected back<input type="date" value={date} onChange={(e) => setDate(e.target.value)} required /></label>
          <label className="wide">Operation<input value={operation} onChange={(e) => setOperation(e.target.value)} maxLength={80} required /></label>
        </>}
        {action === "edit" && b.status !== "planned" && <p className="hint wide">At the supplier, quantities and dates change only through supplier updates.</p>}
        {action === "edit" && <label className="wide">Notes <span className="optional">OPTIONAL</span><input value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={2000} /></label>}
        {action === "allocate" && <>
          <label className="wide">Order line<select value={componentId} onChange={(e) => { setComponentId(e.target.value); const c = options.find((o) => o.component_id === e.target.value); const free = Number(b.quantity) - Number(b.allocated_qty); if (c) setAllocQty(String(Math.min(Number(c.open_qty), free))); }} required autoFocus><option value="" disabled>{options.length ? "Choose an order line" : "No open order lines need this item"}</option>{options.map((c) => <option key={c.component_id} value={c.component_id}>{c.order_number} / {c.line_no} · {c.customer_name} · needs {c.open_qty} · promised {fmtDate(c.promised_date)}</option>)}</select></label>
          <label>Quantity from this batch<input inputMode="decimal" value={allocQty} onChange={(e) => setAllocQty(e.target.value)} required /></label>
        </>}
      </div>
      {submit.error && <div className="form-error" role="alert"><AlertCircle size={15} /><span>{submit.error.message}{stale && " Close this and reopen the batch to see the latest version."}</span></div>}
      <footer><span className="toolbar-spacer" /><button type="button" className="quiet-button" onClick={onClose}>Back</button><button type="submit" className={`primary-button compact ${action === "cancel" || action === "close" ? "danger-fill" : ""}`} disabled={submit.isPending}>{submit.isPending ? <LoaderCircle className="spin" size={15} /> : <Check size={15} />} {action === "cancel" ? "Cancel batch" : action === "close" ? "Close batch" : "Save"}</button></footer>
    </form>
  </div>;
}
