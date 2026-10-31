import { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, Check, LoaderCircle, Plus, Search, Send, Truck, Upload, X } from "lucide-react";
import { api, type ApiError } from "./api";
import { Badge, fmtDate, useLookups } from "./orders";
import { ReceiptsPanel } from "./receipts";
import { ReportBrief, SupplierPanel } from "./supplierUpdates";
import type { AllocationCandidate, BatchAllocationDetail, BatchDetail, BatchSummary, MasterRecord, Page } from "./types";
import { t, locale } from "./i18n";

const today = () => new Date().toISOString().slice(0, 10);

export function OutsourcingPage({ sub, permissions }: { sub: string; permissions: string[] }) {
  const canManage = permissions.includes("outsourcing:manage");
  const [path, query = ""] = sub.split("?");
  if (path === "new" && canManage) return <NewBatch prefill={new URLSearchParams(query)} />;
  if (path === "import" && canManage) return <BatchImport />;
  if (path && path !== "new" && path !== "import") return <BatchView id={path} canManage={canManage} canRecord={permissions.includes("supplier_updates:record")} canReceive={permissions.includes("receipts:record")} canDecide={permissions.includes("quality:decide")} canPlan={permissions.includes("orders:plan")} />;
  return <BatchList canManage={canManage} />;
}

function BatchList({ canManage }: { canManage: boolean }) {
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
    <header className="page-head"><div><span className="eyebrow">{t("WORK OUTSIDE THE FACTORY")}</span><h1 className="page-title">{t("Outsourcing")}</h1></div><p className="lede small">{t("Every batch sent to a job-work supplier, the customer orders waiting on it, and what the supplier last told you.")}</p></header>
    <div className="panel data-panel">
      <div className="toolbar">
        <label className="search-field"><Search size={14} /><input aria-label={t("Search batches")} placeholder={t("Batch, supplier, item, operation or challan")} value={q} maxLength={80} onChange={(e) => setQ(e.target.value)} /></label>
        <select aria-label={t("Status")} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">{t("All statuses")}</option><option value="planned">{t("Planned")}</option><option value="at_supplier">{t("At supplier")}</option><option value="closed">{t("Closed")}</option><option value="cancelled">{t("Cancelled")}</option></select>
        <span className="toolbar-spacer" />
        {canManage && <a className="quiet-button" href="#outsourcing/import"><Upload size={14} /> {t("Import batches")}</a>}
        {canManage && <a className="primary-button compact" href="#outsourcing/new"><Plus size={15} /> {t("New batch")}</a>}
      </div>
      {list.isError ? <div className="form-error" role="alert"><AlertCircle size={15} />{list.error.message}</div>
        : list.isPending ? <div className="table-state"><LoaderCircle className="spin" size={16} /> {t("Loading…")}</div>
          : total === 0 ? <div className="table-state">{q || status ? t("No batches match.") : t("No outsourced batches yet.")}</div>
            : <div className="table-wrap"><table className="data-table">
              <thead><tr><th scope="col">{t("Batch")}</th><th scope="col">{t("Supplier")}</th><th scope="col">{t("Item · operation")}</th><th scope="col" className="num">{t("Quantity")}</th><th scope="col">{t("Orders")}</th><th scope="col">{t("Sent")}</th><th scope="col">{t("Expected back")}</th><th scope="col">{t("Supplier says")}</th><th scope="col">{t("Back · accepted")}</th><th scope="col">{t("Status")}</th></tr></thead>
              <tbody>{list.data.items.map((b) => <tr key={b.id} tabIndex={0} aria-label={t("Open {0}", [b.number])} onClick={() => { window.location.hash = `outsourcing/${b.id}`; }} onKeyDown={(e) => { if (e.key === "Enter") window.location.hash = `outsourcing/${b.id}`; }}>
                <td className="mono">{b.number}</td><td>{b.supplier_name}</td><td><b className="mono">{b.item_code}</b><small className="cell-sub">{b.operation}</small></td>
                <td className="num">{b.quantity} <small>{b.unit_code}</small></td><td>{b.order_count === 0 ? <span className="muted-inline">{t("None")}</span> : `${b.order_count} · ${b.allocated_qty} ${b.unit_code}`}</td>
                <td className="date">{fmtDate(b.sent_date)}</td><td className="date">{fmtDate(b.expected_return_date)}</td><td>{b.status === "planned" ? <span className="muted-inline">{t("Not sent")}</span> : <ReportBrief r={b} unit={b.unit_code} empty={b.status === "at_supplier" ? t("No update since sent {0}", [fmtDate(b.sent_date)]) : undefined} />}</td><td className="num">{b.received_qty ? <>{b.received_qty} · <b>{b.accepted_qty}</b>{Number(b.held_qty) > 0 && <small className="cell-sub">{t("{0} on hold", [b.held_qty])}</small>}</> : <span className="muted-inline">—</span>}</td><td><Badge status={b.status} /></td>
              </tr>)}</tbody>
            </table></div>}
      {total > limit && <div className="pager"><span>{offset + 1}–{t("{0} of {1}", [Math.min(offset + limit, total), total])}</span><button className="quiet-button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>{t("Previous")}</button><button className="quiet-button" disabled={offset + limit >= total} onClick={() => setOffset(offset + limit)}>{t("Next")}</button></div>}
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
  const [material, setMaterial] = useState<Material>({ reference: "", owner: "own", customerId: "" });
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
      site_id: siteId, supplier_id: supplierId, item_id: itemId, operation, quantity, expected_return_date: expected, notes, ...materialBody(material),
      allocations: Object.entries(picked).map(([component_id, qty]) => ({ component_id, quantity: qty })),
    }) }),
    onSuccess: (batch) => { for (const key of ["batches", "order", "candidates"]) void queryClient.invalidateQueries({ queryKey: [key] }); window.location.hash = `outsourcing/${batch.id}`; },
  });
  return <section className="wrap page">
    <a className="back-link" href="#outsourcing"><ArrowLeft size={15} /> {t("Outsourcing")}</a>
    <header className="page-head"><div><span className="eyebrow">{t("NEW OUTSOURCED BATCH")}</span><h1 className="page-title">{t("New batch")}</h1></div><p className="lede small">{t("One item, one operation, one supplier. Link it to the customer orders it serves so a delay here shows up on those orders.")}</p></header>
    <form className="panel" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
      <div className="form-grid four">
        <label>{t("Item sent")}<select value={itemId} onChange={(e) => { setItemId(e.target.value); setPicked({}); }} required><option value="" disabled>{t("Choose an item")}</option>{items.map((it) => <option key={it.id} value={it.id}>{it.code} · {it.name}</option>)}</select></label>
        <label>{t("Operation")}<input value={operation} onChange={(e) => setOperation(e.target.value)} maxLength={80} required placeholder={t("e.g. Powder coating")} /></label>
        <label>{t("Job-work supplier")}<select value={supplierId} onChange={(e) => setSupplierId(e.target.value)} required><option value="" disabled>{jobWorkers.length ? t("Choose a supplier") : t("No job-work suppliers yet")}</option>{jobWorkers.map((s) => <option key={s.id} value={s.id}>{s.code} · {s.name}</option>)}</select></label>
        <label>{t("Site")}<select value={siteId} onChange={(e) => { setSiteId(e.target.value); setPicked({}); }} required>{sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
        <label>{t("Quantity")}<input inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} required /></label>
        <label>{t("Expected back")}<input type="date" value={expected} onChange={(e) => setExpected(e.target.value)} required /></label>
        <label className="span-2">{t("Notes")} <span className="optional">{t("OPTIONAL")}</span><input value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={2000} /></label>
        <MaterialFields value={material} onChange={setMaterial} />
      </div>
      {jobWorkers.length === 0 && suppliers.isSuccess && <p className="hint">{t("Mark a supplier as providing job work under Master data → Suppliers first.")}</p>}
      <fieldset className="dep-fieldset">
        <legend>{t("Customer orders waiting for this item")} <span className="hint">{t("Open lines of confirmed orders at this site that still need it. Allocated {0} of {1}", [allocatedTotal, quantity || 0])}.</span></legend>
        {!itemId ? <p className="muted-line">{t("Choose the item first.")}</p>
          : candidates.isPending ? <p className="muted-line">{t("Loading…")}</p>
            : (candidates.data ?? []).length === 0 ? <p className="muted-line">{t("No open order lines need this item. You can still create the batch and link orders later.")}</p>
              : <div className="table-wrap"><table className="data-table compact-table">
                <thead><tr><th scope="col"><span className="sr-only">{t("Use")}</span></th><th scope="col">{t("Order")}</th><th scope="col">{t("Customer")}</th><th scope="col">{t("Promised")}</th><th scope="col">{t("Step")}</th><th scope="col" className="num">{t("Still open")}</th><th scope="col" className="num">{t("From this batch")}</th></tr></thead>
                <tbody>{candidates.data!.map((c) => { const on = c.component_id in picked; return <tr key={c.component_id} className="static-row">
                  <td><input type="checkbox" aria-label={t("Use for {0} line {1}", [c.order_number, c.line_no])} checked={on} onChange={(e) => setPicked((p) => { const next = { ...p }; if (e.target.checked) next[c.component_id] = c.open_qty; else delete next[c.component_id]; return next; })} /></td>
                  <td className="mono">{c.order_number} / {c.line_no}<small className="cell-sub">{c.line_item_code}</small></td><td>{c.customer_name}</td><td className="date">{fmtDate(c.promised_date)}</td><td>{c.outsourced_operation ?? "—"}</td>
                  <td className="num">{c.open_qty}</td>
                  <td className="num">{on ? <input className="qty-input" aria-label={t("Quantity for {0} line {1}", [c.order_number, c.line_no])} inputMode="decimal" value={picked[c.component_id]} onChange={(e) => setPicked((p) => ({ ...p, [c.component_id]: e.target.value }))} /> : "—"}</td>
                </tr>; })}</tbody>
              </table></div>}
      </fieldset>
      {create.error && <div className="form-error" role="alert"><AlertCircle size={15} />{create.error.message}</div>}
      <div className="form-actions"><a className="quiet-button" href="#outsourcing">{t("Cancel")}</a><button className="primary-button compact" type="submit" disabled={create.isPending}>{create.isPending ? <LoaderCircle className="spin" size={15} /> : <Check size={15} />} {t("Create planned batch")}</button></div>
    </form>
  </section>;
}

type BatchAction = "send" | "edit" | "allocate" | "cancel" | "close";

function BatchView({ id, canManage, canRecord, canReceive, canDecide, canPlan }: { id: string; canManage: boolean; canRecord: boolean; canReceive: boolean; canDecide: boolean; canPlan: boolean }) {
  const queryClient = useQueryClient();
  const batch = useQuery({ queryKey: ["batch", id], queryFn: () => api<BatchDetail>(`/api/v1/outsourcing/batches/${id}`), staleTime: 0 });
  const [action, setAction] = useState<BatchAction | null>(null);
  const [ranking, setRanking] = useState<BatchAllocationDetail | null>(null);
  const done = (value: BatchDetail) => {
    queryClient.setQueryData(["batch", id], value);
    for (const key of ["batches", "order", "candidates", "order-risk", "risk-board"]) void queryClient.invalidateQueries({ queryKey: [key] });
    setAction(null);
    setRanking(null);
  };
  const unallocate = useMutation({
    mutationFn: (allocationId: string) => api<BatchDetail>(`/api/v1/outsourcing/batches/${id}/allocations/${allocationId}?version=${batch.data!.version}`, { method: "DELETE" }),
    onSuccess: done,
  });
  if (batch.isPending) return <section className="wrap page"><div className="table-state"><LoaderCircle className="spin" size={16} /> {t("Loading…")}</div></section>;
  if (batch.isError) return <section className="wrap page"><a className="back-link" href="#outsourcing"><ArrowLeft size={15} /> {t("Outsourcing")}</a><div className="form-error" role="alert"><AlertCircle size={15} />{batch.error.message}</div></section>;
  const b = batch.data;
  const active = b.status === "planned" || b.status === "at_supplier";
  const free = Number(b.quantity) - Number(b.allocated_qty);
  return <section className="wrap page">
    <a className="back-link" href="#outsourcing"><ArrowLeft size={15} /> {t("Outsourcing")}</a>
    <header className="page-head order-head">
      <div><span className="eyebrow">{b.supplier_code} · {b.site_name.toUpperCase()}</span><h1 className="page-title">{b.number} <Badge status={b.status} /></h1></div>
      <dl className="facts">
        <div><dt>{t("Supplier")}</dt><dd>{b.supplier_name}</dd></div>
        <div><dt>{t("Item · operation")}</dt><dd><span className="mono">{b.item_code}</span> · {b.operation}</dd></div>
        <div><dt>{t("Quantity")}</dt><dd>{b.quantity} {b.unit_code}</dd></div>
        <div><dt>{t("Expected back")}</dt><dd>{fmtDate(b.expected_return_date)}</dd></div>
        {b.sent_date && <div><dt>{t("Sent")}</dt><dd>{fmtDate(b.sent_date)}</dd></div>}
        {b.challan_reference && <div><dt>{t("Challan")}</dt><dd className="mono">{b.challan_reference}</dd></div>}
        {b.reference && <div><dt>{t("Batch reference")}</dt><dd className="mono">{b.reference}</dd></div>}
        <div><dt>{t("Material owner")}</dt><dd>{b.material_owner === "customer" ? t("Customer-supplied: {0}", [b.owner_customer_name]) : t("Our material")}</dd></div>
      </dl>
    </header>
    {b.status_reason && <div className="notice-line"><AlertCircle size={16} /><span>{b.status === "closed" ? t("Closed") : t("Cancelled")}: {b.status_reason}</span></div>}
    {canManage && active && <div className="action-bar">
      {b.status === "planned" && <button className="primary-button compact" onClick={() => setAction("send")}><Send size={15} /> {t("Record sent to supplier")}</button>}
      <span className="toolbar-spacer" />
      <button className="quiet-button" onClick={() => setAction("allocate")} disabled={free <= 0}><Plus size={14} /> {t("Link an order")}</button>
      <button className="quiet-button" onClick={() => setAction("edit")}>{t("Edit")}</button>
      {b.status === "planned" ? <button className="quiet-button danger" onClick={() => setAction("cancel")}>{t("Cancel batch")}</button> : <button className="quiet-button danger" onClick={() => setAction("close")}>{t("Close batch")}</button>}
    </div>}
    {b.status !== "planned" && <SupplierPanel batch={b} canRecord={canRecord} onChange={done} />}
    {b.status !== "planned" && (b.status === "at_supplier" || b.receipts.length > 0) && <ReceiptsPanel batch={b} canReceive={canReceive} canDecide={canDecide} onChange={done} />}
    <section className="panel data-panel" aria-labelledby="alloc-title">
      <div><span className="eyebrow">{t("DEPENDENT CUSTOMER ORDERS")}</span><h2 id="alloc-title" className="panel-title">{t("Orders waiting on this batch")}</h2></div>
      {b.allocations.length === 0 ? <p className="muted-line">{t("Not linked to any order line.")} {free > 0 && t("A delay here will not show on any customer order until you link one.")}</p>
        : <div className="table-wrap"><table className="data-table compact-table">
          <thead><tr><th scope="col">{t("Order / line")}</th><th scope="col">{t("Customer")}</th><th scope="col">{t("Promised")}</th><th scope="col" className="num">{t("Line needs")}</th><th scope="col" className="num">{t("From this batch")}</th><th scope="col">{t("Served")}</th>{canManage && active && <th scope="col"><span className="sr-only">{t("Actions")}</span></th>}</tr></thead>
          <tbody>{b.allocations.map((a) => <tr key={a.id} className="static-row">
            <td><a className="mono" href={`#orders/${a.order_id}`}>{a.order_number} / {a.line_no}</a><small className="cell-sub">{a.line_item_code}</small></td>
            <td>{a.customer_name}</td><td className="date">{fmtDate(a.promised_date)}</td>
            <td className="num">{a.component_required_qty} <small>{b.unit_code}</small></td><td className="num strong">{a.quantity} <small>{b.unit_code}</small></td>
            <td>{a.priority_rank !== null ? <><span className="badge status-pending">{t("Priority {0}", [a.priority_rank])}</span><small className="cell-sub">{a.priority_reason} · {a.priority_set_by_label?.split(" <")[0] ?? t("Unknown user")}</small></> : <span className="muted-inline">{t("By promised date")}</span>}
              {canPlan && active && <button className="text-button" onClick={() => setRanking(a)}>{a.priority_rank !== null ? t("Change") : t("Set priority")}</button>}</td>
            {canManage && active && <td className="row-actions"><button className="text-button" disabled={unallocate.isPending} onClick={() => unallocate.mutate(a.id)}>{t("Unlink")}</button></td>}
          </tr>)}</tbody>
        </table></div>}
      <p className="hint">{t("{0} of {1} {2} linked to orders{3}. Usable material goes to prioritised lines first (1 is first), then by earliest promised date.", [b.allocated_qty, b.quantity, b.unit_code, free > 0 ? t("; {0} {1} not linked (spare or for future orders)", [free, b.unit_code]) : ""])}</p>
      {unallocate.error && <div className="form-error" role="alert"><AlertCircle size={15} />{unallocate.error.message}</div>}
    </section>
    <section className="panel" aria-labelledby="custody-title">
      <div><span className="eyebrow">{t("CUSTODY")}</span><h2 id="custody-title" className="panel-title">{t("Material movements")}</h2></div>
      {b.movements.length === 0 ? <p className="muted-line">{t("Nothing has left the factory yet.")}</p>
        : <ol className="timeline">{b.movements.map((m, i) => <li key={i}><b><Truck size={13} /> {m.kind === "sent_to_supplier" ? t("Sent to supplier") : t("Received from supplier")} · {m.quantity} {b.unit_code}</b><span>{fmtDate(m.movement_date)}{m.document_reference ? ` · ${m.kind === "sent_to_supplier" ? t("our challan") : t("document")} ${m.document_reference}` : ""}</span><small>{t("{0} · recorded {1}", [m.recorded_by_label?.split(" <")[0] ?? t("Unknown user"), new Date(m.recorded_at).toLocaleString(locale(), { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })])}</small></li>)}</ol>}
    </section>
    {b.notes && <div className="panel"><span className="field-label">{t("Notes")}</span><p className="notes-text">{b.notes}</p></div>}
    {action && <BatchDialog action={action} batch={b} onClose={() => setAction(null)} onDone={done} />}
    {ranking && <PriorityDialog batch={b} allocation={ranking} onClose={() => setRanking(null)} onDone={done} />}
  </section>;
}

function BatchDialog({ action, batch: b, onClose, onDone }: { action: BatchAction; batch: BatchDetail; onClose: () => void; onDone: (b: BatchDetail) => void }) {
  const [date, setDate] = useState(action === "send" ? today() : b.expected_return_date);
  const [reference, setReference] = useState("");
  const [reason, setReason] = useState("");
  const [quantity, setQuantity] = useState(b.quantity);
  const [operation, setOperation] = useState(b.operation);
  const [notes, setNotes] = useState(b.notes ?? "");
  const [material, setMaterial] = useState<Material>({ reference: b.reference ?? "", owner: b.material_owner, customerId: b.owner_customer_id ?? "" });
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
        case "edit": return send(base, b.status === "planned" ? { version: b.version, quantity, operation, expected_return_date: date, notes, ...materialBody(material) } : { version: b.version, notes, ...materialBody(material) }, "PATCH");
      }
    },
    onSuccess: onDone,
  });
  const titles: Record<BatchAction, string> = { send: t("Record sent to supplier"), edit: t("Edit {0}", [b.number]), allocate: t("Link a customer order"), cancel: t("Cancel {0}", [b.number]), close: t("Close {0}", [b.number]) };
  const stale = (submit.error as ApiError | null)?.status === 409;
  return <div className="dialog-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <form className="dialog" role="dialog" aria-modal="true" aria-labelledby="batch-action-title" onSubmit={(e) => { e.preventDefault(); submit.mutate(); }}>
      <header><div><span className="eyebrow">{b.number} · {b.supplier_name}</span><h2 id="batch-action-title">{titles[action]}</h2></div><button type="button" className="icon-button" onClick={onClose} aria-label={t("Close")}><X size={16} /></button></header>
      <div className="dialog-grid">
        {action === "send" && <>
          <label>{t("Sent on")}<input type="date" value={date} max={today()} onChange={(e) => setDate(e.target.value)} required autoFocus /></label>
          <label>{t("Delivery challan")} <span className="optional">{t("OPTIONAL")}</span><input value={reference} onChange={(e) => setReference(e.target.value)} maxLength={80} placeholder={t("e.g. DC-1182")} /></label>
          <p className="hint wide">{t("Records {0} {1} {2} as handed over to {3}", [b.quantity, b.unit_code, b.item_code, b.supplier_name])}.</p>
        </>}
        {(action === "cancel" || action === "close") && <label className="wide">{t("Reason")}<input value={reason} onChange={(e) => setReason(e.target.value)} required minLength={3} maxLength={500} autoFocus placeholder={action === "cancel" ? t("Why is this batch not going ahead?") : t("Why is this batch being closed without receipts?")} /></label>}
        {(action === "cancel" || action === "close") && b.allocations.length > 0 && <p className="hint wide">{t("The {0} {1} linked to customer orders will be unlinked; those orders will need another batch.", [b.allocated_qty, b.unit_code])}</p>}
        {action === "edit" && b.status === "planned" && <>
          <label>{t("Quantity")}<input inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} required /></label>
          <label>{t("Expected back")}<input type="date" value={date} onChange={(e) => setDate(e.target.value)} required /></label>
          <label className="wide">{t("Operation")}<input value={operation} onChange={(e) => setOperation(e.target.value)} maxLength={80} required /></label>
        </>}
        {action === "edit" && b.status !== "planned" && <p className="hint wide">{t("At the supplier, quantities and dates change only through supplier updates.")}</p>}
        {action === "edit" && <label className="wide">{t("Notes")} <span className="optional">{t("OPTIONAL")}</span><input value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={2000} /></label>}
        {action === "edit" && <MaterialFields value={material} onChange={setMaterial} />}
        {action === "allocate" && <>
          <label className="wide">{t("Order line")}<select value={componentId} onChange={(e) => { setComponentId(e.target.value); const c = options.find((o) => o.component_id === e.target.value); const free = Number(b.quantity) - Number(b.allocated_qty); if (c) setAllocQty(String(Math.min(Number(c.open_qty), free))); }} required autoFocus><option value="" disabled>{options.length ? t("Choose an order line") : t("No open order lines need this item")}</option>{options.map((c) => <option key={c.component_id} value={c.component_id}>{c.order_number} / {c.line_no} · {t("{0} · needs {1} · promised {2}", [c.customer_name, c.open_qty, fmtDate(c.promised_date)])}</option>)}</select></label>
          <label>{t("Quantity from this batch")}<input inputMode="decimal" value={allocQty} onChange={(e) => setAllocQty(e.target.value)} required /></label>
        </>}
      </div>
      {submit.error && <div className="form-error" role="alert"><AlertCircle size={15} /><span>{submit.error.message}{stale && t(" Close this and reopen the batch to see the latest version.")}</span></div>}
      <footer><span className="toolbar-spacer" /><button type="button" className="quiet-button" onClick={onClose}>{t("Back")}</button><button type="submit" className={`primary-button compact ${action === "cancel" || action === "close" ? "danger-fill" : ""}`} disabled={submit.isPending}>{submit.isPending ? <LoaderCircle className="spin" size={15} /> : <Check size={15} />} {action === "cancel" ? t("Cancel batch") : action === "close" ? t("Close batch") : t("Save")}</button></footer>
    </form>
  </div>;
}

function PriorityDialog({ batch: b, allocation: a, onClose, onDone }: { batch: BatchDetail; allocation: BatchAllocationDetail; onClose: () => void; onDone: (b: BatchDetail) => void }) {
  const [rank, setRank] = useState(a.priority_rank !== null ? String(a.priority_rank) : "1");
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: (clear: boolean) => api<BatchDetail>(`/api/v1/outsourcing/batches/${b.id}/allocations/${a.id}/priority`, { method: "POST", body: JSON.stringify({ version: b.version, rank: clear ? null : Number(rank), reason }) }),
    onSuccess: onDone,
  });
  useEffect(() => { const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); }; window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k); }, [onClose]);
  return <div className="dialog-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <form className="dialog" role="dialog" aria-modal="true" aria-labelledby="priority-title" onSubmit={(e) => { e.preventDefault(); save.mutate(false); }}>
      <header><div><span className="eyebrow">{b.number} · {a.order_number} / {a.line_no} · {a.customer_name}</span><h2 id="priority-title">{t("Serve this line first")}</h2></div><button type="button" className="icon-button" onClick={onClose} aria-label={t("Close")}><X size={16} /></button></header>
      <div className="dialog-grid">
        <label>{t("Priority")}<input type="number" min={1} max={99} value={rank} onChange={(e) => setRank(e.target.value)} required /></label>
        <label className="wide">{t("Reason")}<input value={reason} onChange={(e) => setReason(e.target.value)} required minLength={3} maxLength={500} autoFocus placeholder={t("e.g. Key account; their line-side stock is out")} /></label>
        <p className="hint wide">{t("Material from this batch goes to prioritised lines first (1 before 2), ahead of earlier promised dates. Other orders may become at risk; check the risk board after saving. The change is recorded with your name.")}</p>
      </div>
      {save.error && <div className="form-error" role="alert"><AlertCircle size={15} /><span>{save.error.message}{(save.error as ApiError).status === 409 && t(" Reload the batch.")}</span></div>}
      <footer>{a.priority_rank !== null && <button type="button" className="quiet-button danger" disabled={save.isPending || reason.trim().length < 3} onClick={() => save.mutate(true)}>{t("Back to promised-date order")}</button>}<span className="toolbar-spacer" /><button type="button" className="quiet-button" onClick={onClose}>{t("Back")}</button><button type="submit" className="primary-button compact" disabled={save.isPending}>{save.isPending ? <LoaderCircle className="spin" size={15} /> : <Check size={15} />} {t("Save priority")}</button></footer>
    </form>
  </div>;
}

interface Material { reference: string; owner: "own" | "customer"; customerId: string }
const materialBody = (m: Material) => ({ reference: m.reference || null, material_owner: m.owner, owner_customer_id: m.owner === "customer" ? m.customerId || null : null });

/** Batch reference and whose material it is (ADR-0014). */
function MaterialFields({ value, onChange }: { value: Material; onChange: (m: Material) => void }) {
  const { customers } = useLookups();
  return <>
    <label>{t("Batch reference")} <span className="optional">{t("OPTIONAL")}</span><input value={value.reference} onChange={(e) => onChange({ ...value, reference: e.target.value })} maxLength={80} placeholder={t("e.g. PC-2210")} /></label>
    <label>{t("Material owner")}<select value={value.owner} onChange={(e) => onChange({ ...value, owner: e.target.value as Material["owner"] })}><option value="own">{t("Our material")}</option><option value="customer">{t("Customer-supplied (free issue)")}</option></select></label>
    {value.owner === "customer" && <label>{t("Customer")}<select value={value.customerId} onChange={(e) => onChange({ ...value, customerId: e.target.value })} required><option value="" disabled>{t("Choose a customer")}</option>{customers.map((c) => <option key={c.id} value={c.id}>{c.code} · {c.name}</option>)}</select></label>}
  </>;
}

const BATCH_TEMPLATE = "supplier_code,item_code,operation,quantity,expected_return_date,sent_date,challan_reference,batch_reference,material_owner,owner_customer_code,order_number,line_no,allocate_qty,notes\n";

interface BatchImportReport { total_rows: number; batches_to_create: number; sent_batches: number; allocations_to_create: number; unchanged_batches: number; errors: { row: number; field: string | null; message: string }[]; committed: boolean; created_numbers: string[] }

/** Load batches already at suppliers, or planned, from a spreadsheet (ADR-0014). */
function BatchImport() {
  const { sites } = useLookups();
  const queryClient = useQueryClient();
  const [siteId, setSiteId] = useState("");
  const [csvText, setCsvText] = useState("");
  const [fileName, setFileName] = useState("");
  const [report, setReport] = useState<BatchImportReport | null>(null);
  useEffect(() => { if (!siteId && sites[0]) setSiteId(sites[0].id); }, [sites, siteId]);
  const run = useMutation({
    mutationFn: (commit: boolean) => api<BatchImportReport>("/api/v1/outsourcing/batches/import", { method: "POST", body: JSON.stringify({ site_id: siteId, csv_text: csvText, commit }) }),
    onSuccess: (value) => { setReport(value); if (value.committed) for (const k of ["batches", "order", "order-risk", "risk-board"]) void queryClient.invalidateQueries({ queryKey: [k] }); },
    onError: (error: ApiError) => { const body = error.body as BatchImportReport | undefined; if (body && "errors" in body) setReport(body); },
  });
  return <section className="wrap page">
    <a className="back-link" href="#outsourcing"><ArrowLeft size={15} /> {t("Outsourcing")}</a>
    <header className="page-head"><div><span className="eyebrow">{t("WORK OUTSIDE THE FACTORY")}</span><h1 className="page-title">{t("Import batches")}</h1></div><p className="lede small">{t("One row per batch, or one row per order line a batch serves. Rows with a sent date and our challan number are recorded as already at the supplier; the others are planned. Preview first; a file with any problem creates nothing, and importing it again creates nothing new.")}</p></header>
    <div className="panel data-panel">
      <div className="import-controls">
        <label>{t("Site")}<select value={siteId} onChange={(e) => { setSiteId(e.target.value); setReport(null); }}>{sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
        <label>{t("CSV file (max 500 KB)")}<input type="file" accept=".csv,text/csv" onChange={(e) => { const f = e.target.files?.[0]; setReport(null); setCsvText(""); setFileName(f?.name ?? ""); if (f && f.size <= 500_000) void f.text().then(setCsvText); }} /></label>
        <a className="text-link" href={`data:text/csv;charset=utf-8,${encodeURIComponent(BATCH_TEMPLATE)}`} download="batches-template.csv">{t("Download a blank template")}</a>
      </div>
      <p className="hint">{t("Required: supplier_code, item_code, operation, quantity, expected_return_date. Each row needs our challan number (with sent_date) or a batch_reference. To link an order line, give order_number, line_no and allocate_qty. material_owner is own or customer (with owner_customer_code).")}</p>
      <div className="import-actions">
        <button className="quiet-button" disabled={!csvText || !siteId || run.isPending} onClick={() => run.mutate(false)}>{fileName ? t("Preview “{0}”", [fileName]) : t("Preview")}</button>
        <button className="primary-button compact" disabled={!report || report.committed || report.errors.length > 0 || report.batches_to_create === 0 || run.isPending} onClick={() => run.mutate(true)}><Check size={15} /> {t(report?.batches_to_create === 1 ? "Create {0} batch" : "Create {0} batches", [report?.batches_to_create ?? ""])}</button>
      </div>
      {run.error && !report && <div className="form-error" role="alert"><AlertCircle size={15} />{run.error.message}</div>}
      {report && <div className="import-report" aria-live="polite">
        <div className="report-stats"><span><b>{report.total_rows}</b> {t("rows")}</span><span><b>{report.batches_to_create}</b> {t("new batches")}</span><span><b>{report.sent_batches}</b> {t("already at the supplier")}</span><span><b>{report.allocations_to_create}</b> {t("order links")}</span><span><b>{report.unchanged_batches}</b> {t("already present")}</span><span className={report.errors.length ? "bad" : "good"}><b>{report.errors.length}</b> {t("problems")}</span></div>
        {report.committed && <p className="success-line"><Check size={14} /> {t("Created {0}", [report.created_numbers.join(", ") || t("nothing new")])}.</p>}
        {report.errors.length > 0 && <div className="table-wrap"><table className="data-table compact-table"><thead><tr><th scope="col">{t("Row")}</th><th scope="col">{t("Column")}</th><th scope="col">{t("Problem")}</th></tr></thead><tbody>{report.errors.map((err, i) => <tr key={i} className="static-row"><td>{err.row}</td><td className="mono">{err.field ?? "—"}</td><td>{err.message}</td></tr>)}</tbody></table></div>}
      </div>}
    </div>
  </section>;
}
