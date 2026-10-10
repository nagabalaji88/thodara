import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Check, Copy, LoaderCircle, Plus, Trash2, X } from "lucide-react";
import { api, type ApiError } from "./api";
import type { DependencyTemplate, LineComponent, LineOperation, MasterRecord, OrderDetail, OrderLine, Page } from "./types";

export const fmtDuration = (minutes: number) => {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h && m ? `${h} h ${m} min` : h ? `${h} h` : `${m} min`;
};

/** What one order line needs before it can ship. */
export function LineDependencies({ order, line, canPlan, onSaved, renderAllocations }: {
  order: OrderDetail; line: OrderLine; canPlan: boolean; onSaved: (o: OrderDetail) => void;
  renderAllocations?: (component: LineComponent) => React.ReactNode;
}) {
  const [editing, setEditing] = useState(false);
  const editable = canPlan && line.status === "open" && (order.status === "draft" || order.status === "confirmed");
  const empty = line.components.length === 0 && line.operations.length === 0;
  const total = line.operations.reduce((sum, o) => sum + o.duration_minutes, 0);
  return <section className="panel dependency-panel" aria-labelledby={`deps-${line.id}`}>
    <header className="dependency-head">
      <div><span className="eyebrow">LINE {line.line_no} · {line.item_code}</span><h2 id={`deps-${line.id}`} className="panel-title">What this line needs</h2></div>
      {editable && <button className="quiet-button" onClick={() => setEditing(true)}>{empty ? <><Plus size={14} /> Add dependencies</> : "Edit dependencies"}</button>}
    </header>
    {empty ? <p className="muted-line">No components or remaining work recorded yet. Without them Thodara cannot tell which outsourced work can delay this line.</p> : <>
      {line.components.length > 0 && <div className="table-wrap"><table className="data-table compact-table">
        <thead><tr><th scope="col">Component</th><th scope="col" className="num">Per unit</th><th scope="col" className="num">Needed</th><th scope="col">Outsourced step</th><th scope="col">Batches</th></tr></thead>
        <tbody>{line.components.map((c) => <tr key={c.id} className="static-row">
          <td><b className="mono">{c.item_code}</b><small className="cell-sub">{c.item_name}</small></td>
          <td className="num">{c.qty_per_unit} <small>{c.unit_code}</small></td>
          <td className="num strong">{c.required_qty} <small>{c.unit_code}</small></td>
          <td>{c.outsourced_operation ?? <span className="muted">Not outsourced</span>}</td>
          <td>{renderAllocations ? renderAllocations(c) : <span className="muted">—</span>}</td>
        </tr>)}</tbody>
      </table></div>}
      {line.operations.length > 0 && <div className="op-path">
        <span className="field-label">After components are ready · {fmtDuration(total)} of working time</span>
        <ol>{line.operations.map((o) => <li key={o.id}><b>{o.name}</b><span>{o.kind === "transport" ? "Transport" : "In-house"} · {fmtDuration(o.duration_minutes)}</span></li>)}</ol>
      </div>}
    </>}
    {editing && <DependencyEditor order={order} line={line} onClose={() => setEditing(false)} onSaved={(o) => { setEditing(false); onSaved(o); }} />}
  </section>;
}

type CompDraft = { item_id: string; qty_per_unit: string; outsourced_operation: string };
type OpDraft = { name: string; kind: "in_house" | "transport"; hours: string };
const toComp = (c: LineComponent): CompDraft => ({ item_id: c.item_id, qty_per_unit: c.qty_per_unit, outsourced_operation: c.outsourced_operation ?? "" });
const toOp = (o: LineOperation): OpDraft => ({ name: o.name, kind: o.kind, hours: String(Math.round((o.duration_minutes / 60) * 100) / 100) });

function DependencyEditor({ order, line, onClose, onSaved }: { order: OrderDetail; line: OrderLine; onClose: () => void; onSaved: (o: OrderDetail) => void }) {
  const items = useQuery({ queryKey: ["md", "items", "lookup"], queryFn: () => api<Page<MasterRecord>>("/api/v1/master-data/items?status=active&limit=200") });
  const template = useQuery({ queryKey: ["dependency-template", line.item_id], queryFn: () => api<DependencyTemplate>(`/api/v1/orders/dependency-template?item_id=${line.item_id}`) });
  const queryClient = useQueryClient();
  const [components, setComponents] = useState<CompDraft[]>(line.components.map(toComp));
  const [operations, setOperations] = useState<OpDraft[]>(line.operations.map(toOp));
  useEffect(() => { const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); }; window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k); }, [onClose]);
  const save = useMutation({
    mutationFn: () => api<OrderDetail>(`/api/v1/orders/${order.id}/lines/${line.id}/dependencies`, { method: "PUT", body: JSON.stringify({
      order_version: order.version,
      components: components.map((c) => ({ ...c, outsourced_operation: c.outsourced_operation || null })),
      operations: operations.map((o) => ({ name: o.name, kind: o.kind, duration_minutes: Math.round(Number(o.hours) * 60) })),
    }) }),
    onSuccess: (o) => {
      // New dependencies change what later orders can copy and which lines need batches.
      void queryClient.invalidateQueries({ queryKey: ["dependency-template"] });
      void queryClient.invalidateQueries({ queryKey: ["candidates"] });
      onSaved(o);
    },
  });
  const choices = (items.data?.items ?? []).filter((it) => it.id !== line.item_id);
  const setC = (i: number, patch: Partial<CompDraft>) => setComponents((cs) => cs.map((c, j) => j === i ? { ...c, ...patch } : c));
  const setO = (i: number, patch: Partial<OpDraft>) => setOperations((os) => os.map((o, j) => j === i ? { ...o, ...patch } : o));
  const source = template.data?.source_order_number;
  const isOwn = source === order.number;
  const stale = (save.error as ApiError | null)?.status === 409;
  return <div className="dialog-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <form className="dialog wide-dialog" role="dialog" aria-modal="true" aria-labelledby="dep-title" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      <header><div><span className="eyebrow">{order.number} · LINE {line.line_no} · {line.ordered_qty} {line.unit_code} {line.item_code}</span><h2 id="dep-title">What this line needs</h2></div><button type="button" className="icon-button" onClick={onClose} aria-label="Close"><X size={16} /></button></header>
      {source && !isOwn && <div className="notice-line"><Copy size={16} /><span>{order.number} can start from the dependencies used on {source}. <button type="button" className="text-button" onClick={() => { setComponents(template.data!.components.map(toComp)); setOperations(template.data!.operations.map(toOp)); }}>Copy from {source}</button></span></div>}
      <fieldset className="dep-fieldset">
        <legend>Components <span className="hint">Quantity per unit of {line.item_code}. Name the outsourced step if a supplier works on it first.</span></legend>
        {components.map((c, i) => <div className="dep-row" key={i}>
          <select aria-label={`Component ${i + 1} item`} value={c.item_id} onChange={(e) => setC(i, { item_id: e.target.value })} required><option value="" disabled>Choose an item</option>{choices.map((it) => <option key={it.id} value={it.id}>{it.code} · {it.name}</option>)}</select>
          <input aria-label={`Component ${i + 1} quantity per unit`} inputMode="decimal" placeholder="Per unit" value={c.qty_per_unit} onChange={(e) => setC(i, { qty_per_unit: e.target.value })} required />
          <input aria-label={`Component ${i + 1} outsourced step`} placeholder="Outsourced step, e.g. Powder coating" value={c.outsourced_operation} maxLength={80} onChange={(e) => setC(i, { outsourced_operation: e.target.value })} />
          <button type="button" className="icon-button small" aria-label={`Remove component ${i + 1}`} onClick={() => setComponents((cs) => cs.filter((_, j) => j !== i))}><Trash2 size={13} /></button>
        </div>)}
        <button type="button" className="text-button" onClick={() => setComponents((cs) => [...cs, { item_id: "", qty_per_unit: "", outsourced_operation: "" }])}><Plus size={12} /> Add component</button>
      </fieldset>
      <fieldset className="dep-fieldset">
        <legend>Remaining work after components arrive <span className="hint">In order, in working hours on the site calendar.</span></legend>
        {operations.map((o, i) => <div className="dep-row" key={i}>
          <input aria-label={`Step ${i + 1} name`} placeholder="e.g. Assembly" value={o.name} maxLength={80} onChange={(e) => setO(i, { name: e.target.value })} required />
          <select aria-label={`Step ${i + 1} kind`} value={o.kind} onChange={(e) => setO(i, { kind: e.target.value as OpDraft["kind"] })}><option value="in_house">In-house</option><option value="transport">Transport</option></select>
          <input aria-label={`Step ${i + 1} hours`} inputMode="decimal" placeholder="Hours" value={o.hours} onChange={(e) => setO(i, { hours: e.target.value })} required />
          <button type="button" className="icon-button small" aria-label={`Remove step ${i + 1}`} onClick={() => setOperations((os) => os.filter((_, j) => j !== i))}><Trash2 size={13} /></button>
        </div>)}
        <button type="button" className="text-button" onClick={() => setOperations((os) => [...os, { name: "", kind: "in_house", hours: "" }])}><Plus size={12} /> Add step</button>
      </fieldset>
      {save.error && <div className="form-error" role="alert"><AlertCircle size={15} /><span>{save.error.message}{stale && " Close this and reopen the order to see the latest version."}</span></div>}
      <footer><span className="toolbar-spacer" /><button type="button" className="quiet-button" onClick={onClose}>Back</button><button type="submit" className="primary-button compact" disabled={save.isPending}>{save.isPending ? <LoaderCircle className="spin" size={15} /> : <Check size={15} />} Save</button></footer>
    </form>
  </div>;
}
