import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle, Info, LoaderCircle } from "lucide-react";
import { api } from "./api";
import { fmtDate } from "./orders";
import { HEADLINES } from "./risk";

interface Report {
  computed_at: string; date_from: string; date_to: string; time_zone: string; stale_after_hours: number;
  delivery: { dispatch_lines: number; with_promise: number; on_time: number; late: number; on_time_rate: number | null; average_days_late: number | null; by_customer: { customer_name: string; lines: number; on_time: number; late: number }[] };
  open_risk: Record<string, number>;
  stale_batches: { batch_id: string; number: string; supplier_name: string; sent_date: string | null; last_update_at: string | null; hours_since: number; orders_waiting: number }[];
  actions: { open: number; overdue: number; awaiting_approval: number; age: { label: string; count: number }[]; closed_in_period: number; median_hours_to_close: number | null; outcomes: Record<string, number> };
  early_warning: { lines_with_actions: number; average_days_ahead: number | null; acted_after_promise: number };
  quality_checks: { decisions: number; same_person: number };
  definitions: Record<string, string>;
}

function Def({ text }: { text: string }) {
  return <p className="definition"><Info size={12} /> {text}</p>;
}

export function ReportsPage() {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const params = new URLSearchParams();
  if (from) params.set("date_from", from);
  if (to) params.set("date_to", to);
  const report = useQuery({ queryKey: ["report", from, to], queryFn: () => api<Report>(`/api/v1/reports/fulfillment?${params}`), staleTime: 0 });
  const r = report.data;
  const pct = (v: number | null) => (v === null ? "—" : `${Math.round(v * 100)}%`);
  const ageMax = Math.max(1, ...(r?.actions.age.map((b) => b.count) ?? [1]));
  return <section className="wrap page">
    <header className="page-head"><div><span className="eyebrow">HOW ARE WE DOING?</span><h1 className="page-title">Reports</h1></div><p className="lede small">Delivery performance, open risk, stale supplier information and how quickly the team acts. Each figure says exactly how it is counted.</p></header>
    <div className="toolbar report-range">
      <label>From<input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
      <label>To<input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
      {r && <span className="hint">{fmtDate(r.date_from)} – {fmtDate(r.date_to)} ({r.time_zone}) · worked out {new Date(r.computed_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}</span>}
    </div>
    {report.isError ? <div className="form-error" role="alert"><AlertCircle size={15} />{report.error.message}</div>
      : !r ? <div className="table-state"><LoaderCircle className="spin" size={16} /> Working it out…</div> : <>
        <section className="wrap-none figures report-figures" aria-label="Delivery">
          <div className="figure"><strong>{pct(r.delivery.on_time_rate)}</strong><span>On time</span><small>{r.delivery.on_time} of {r.delivery.with_promise} dispatched lines with a promise</small></div>
          <div className="figure"><strong>{r.delivery.late}</strong><span>Shipped late</span><small>{r.delivery.average_days_late === null ? "None late" : `${r.delivery.average_days_late} days late on average`}</small></div>
          <div className="figure"><strong>{r.actions.overdue}</strong><span>Overdue actions</span><small>{r.actions.open} open · {r.actions.awaiting_approval} awaiting approval</small></div>
          <div className="figure"><strong>{r.early_warning.average_days_ahead ?? "—"}</strong><span>Days of warning</span><small>{r.early_warning.lines_with_actions} shipped lines had actions; {r.early_warning.acted_after_promise} acted after the promise</small></div>
        </section>
        <Def text={r.definitions["on_time_rate"] ?? ""} />
        <Def text={r.definitions["early_warning"] ?? ""} />
        <div className="report-grid">
          <div className="panel data-panel">
            <h2 className="panel-title">Delivery by customer</h2>
            {r.delivery.by_customer.length === 0 ? <p className="muted-line">Nothing dispatched in this period.</p>
              : <div className="table-wrap"><table className="data-table compact-table"><thead><tr><th scope="col">Customer</th><th scope="col" className="num">Lines</th><th scope="col" className="num">On time</th><th scope="col" className="num">Late</th></tr></thead>
                <tbody>{r.delivery.by_customer.map((c) => <tr key={c.customer_name} className="static-row"><td>{c.customer_name}</td><td className="num">{c.lines}</td><td className="num">{c.on_time}</td><td className={`num ${c.late ? "late-text" : ""}`}>{c.late}</td></tr>)}</tbody></table></div>}
            <Def text={r.definitions["days_late"] ?? ""} />
          </div>
          <div className="panel data-panel">
            <h2 className="panel-title">Open lines by risk, now</h2>
            <ul className="risk-bars">{HEADLINES.map(([k, label]) => <li key={k}><a href="#risk"><span className={`badge risk-${k}`}>{label}</span><b>{r.open_risk[k] ?? 0}</b></a></li>)}</ul>
            <Def text={r.definitions["open_risk"] ?? ""} />
          </div>
          <div className="panel data-panel">
            <h2 className="panel-title">Stale supplier information</h2>
            {r.stale_batches.length === 0 ? <p className="muted-line">Every batch at a supplier has an update within {r.stale_after_hours} hours.</p>
              : <div className="table-wrap"><table className="data-table compact-table"><thead><tr><th scope="col">Batch</th><th scope="col">Supplier</th><th scope="col">Last heard</th><th scope="col" className="num">Orders waiting</th></tr></thead>
                <tbody>{r.stale_batches.map((b) => <tr key={b.batch_id} className="static-row"><td><a className="mono" href={`#outsourcing/${b.batch_id}`}>{b.number}</a></td><td>{b.supplier_name}</td><td className="late-text">{b.last_update_at ? `${Math.round(b.hours_since / 24)} days ago` : `never (sent ${fmtDate(b.sent_date)})`}</td><td className="num">{b.orders_waiting}</td></tr>)}</tbody></table></div>}
            <Def text={r.definitions["stale_updates"] ?? ""} />
          </div>
          <div className="panel data-panel">
            <h2 className="panel-title">Action ageing</h2>
            <ul className="age-bars">{r.actions.age.map((b) => <li key={b.label}><span>{b.label}</span><span className="bar"><i style={{ width: `${(b.count / ageMax) * 100}%` }} /></span><b>{b.count}</b></li>)}</ul>
            <p className="muted-line">{r.actions.closed_in_period} closed in the period{r.actions.median_hours_to_close !== null ? `, median ${r.actions.median_hours_to_close} h to close` : ""}{Object.keys(r.actions.outcomes).length ? ` · ${Object.entries(r.actions.outcomes).map(([k, v]) => `${v} ${k.replace(/_/g, " ")}`).join(", ")}` : ""}.</p>
            <Def text={`${r.definitions["action_age"] ?? ""} ${r.definitions["time_to_close"] ?? ""}`} />
          </div>
          <div className="panel data-panel">
            <h2 className="panel-title">Quality checks</h2>
            <p className="muted-line"><b>{r.quality_checks.decisions}</b> quality decisions in the period; <b className={r.quality_checks.same_person ? "late-text" : undefined}>{r.quality_checks.same_person}</b> made by the person who also received the material.</p>
            <Def text={r.definitions["quality_checks"] ?? ""} />
          </div>
        </div>
      </>}
  </section>;
}
