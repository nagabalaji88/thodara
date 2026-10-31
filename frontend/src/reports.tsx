import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle, Info, LoaderCircle } from "lucide-react";
import { api } from "./api";
import { fmtDate } from "./orders";
import { HEADLINES } from "./risk";
import { locale, t, tk } from "./i18n";

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

// Outcome and status words the report counts by (stored as codes).
tk("resolved"); tk("partly resolved"); tk("not resolved"); tk("cancelled"); tk("rejected"); tk("done");

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
    <header className="page-head"><div><span className="eyebrow">{t("HOW ARE WE DOING?")}</span><h1 className="page-title">{t("Reports")}</h1></div><p className="lede small">{t("Delivery performance, open risk, stale supplier information and how quickly the team acts. Each figure says exactly how it is counted.")}</p></header>
    <div className="toolbar report-range">
      <label>{t("From")}<input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
      <label>{t("To")}<input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
      {r && <span className="hint">{fmtDate(r.date_from)} – {fmtDate(r.date_to)} ({t("{0}) · worked out {1}", [r.time_zone, new Date(r.computed_at).toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" })])}</span>}
    </div>
    {report.isError ? <div className="form-error" role="alert"><AlertCircle size={15} />{report.error.message}</div>
      : !r ? <div className="table-state"><LoaderCircle className="spin" size={16} /> {t("Working it out…")}</div> : <>
        <section className="wrap-none figures report-figures" aria-label={t("Delivery")}>
          <div className="figure"><strong>{pct(r.delivery.on_time_rate)}</strong><span>{t("On time")}</span><small>{t("{0} of {1} dispatched lines with a promise", [r.delivery.on_time, r.delivery.with_promise])}</small></div>
          <div className="figure"><strong>{r.delivery.late}</strong><span>{t("Shipped late")}</span><small>{r.delivery.average_days_late === null ? t("None late") : t("{0} days late on average", [r.delivery.average_days_late])}</small></div>
          <div className="figure"><strong>{r.actions.overdue}</strong><span>{t("Overdue actions")}</span><small>{t("{0} open · {1} awaiting approval", [r.actions.open, r.actions.awaiting_approval])}</small></div>
          <div className="figure"><strong>{r.early_warning.average_days_ahead ?? "—"}</strong><span>{t("Days of warning")}</span><small>{t("{0} shipped lines had actions; {1} acted after the promise", [r.early_warning.lines_with_actions, r.early_warning.acted_after_promise])}</small></div>
        </section>
        <Def text={r.definitions["on_time_rate"] ?? ""} />
        <Def text={r.definitions["early_warning"] ?? ""} />
        <div className="report-grid">
          <div className="panel data-panel">
            <h2 className="panel-title">{t("Delivery by customer")}</h2>
            {r.delivery.by_customer.length === 0 ? <p className="muted-line">{t("Nothing dispatched in this period.")}</p>
              : <div className="table-wrap"><table className="data-table compact-table"><thead><tr><th scope="col">{t("Customer")}</th><th scope="col" className="num">{t("Lines")}</th><th scope="col" className="num">{t("On time")}</th><th scope="col" className="num">{t("Late")}</th></tr></thead>
                <tbody>{r.delivery.by_customer.map((c) => <tr key={c.customer_name} className="static-row"><td>{c.customer_name}</td><td className="num">{c.lines}</td><td className="num">{c.on_time}</td><td className={`num ${c.late ? "late-text" : ""}`}>{c.late}</td></tr>)}</tbody></table></div>}
            <Def text={r.definitions["days_late"] ?? ""} />
          </div>
          <div className="panel data-panel">
            <h2 className="panel-title">{t("Open lines by risk, now")}</h2>
            <ul className="risk-bars">{HEADLINES.map(([k, label]) => <li key={k}><a href="#risk"><span className={`badge risk-${k}`}>{t(label)}</span><b>{r.open_risk[k] ?? 0}</b></a></li>)}</ul>
            <Def text={r.definitions["open_risk"] ?? ""} />
          </div>
          <div className="panel data-panel">
            <h2 className="panel-title">{t("Stale supplier information")}</h2>
            {r.stale_batches.length === 0 ? <p className="muted-line">{t("Every batch at a supplier has an update within {0} hours.", [r.stale_after_hours])}</p>
              : <div className="table-wrap"><table className="data-table compact-table"><thead><tr><th scope="col">{t("Batch")}</th><th scope="col">{t("Supplier")}</th><th scope="col">{t("Last heard")}</th><th scope="col" className="num">{t("Orders waiting")}</th></tr></thead>
                <tbody>{r.stale_batches.map((b) => <tr key={b.batch_id} className="static-row"><td><a className="mono" href={`#outsourcing/${b.batch_id}`}>{b.number}</a></td><td>{b.supplier_name}</td><td className="late-text">{b.last_update_at ? t("{0} days ago", [Math.round(b.hours_since / 24)]) : t("never (sent {0})", [fmtDate(b.sent_date)])}</td><td className="num">{b.orders_waiting}</td></tr>)}</tbody></table></div>}
            <Def text={r.definitions["stale_updates"] ?? ""} />
          </div>
          <div className="panel data-panel">
            <h2 className="panel-title">{t("Action ageing")}</h2>
            <ul className="age-bars">{r.actions.age.map((b) => <li key={b.label}><span>{b.label}</span><span className="bar"><i style={{ width: `${(b.count / ageMax) * 100}%` }} /></span><b>{b.count}</b></li>)}</ul>
            <p className="muted-line">{t("{0} closed in the period{1}", [r.actions.closed_in_period, r.actions.median_hours_to_close !== null ? t(", median {0} h to close", [r.actions.median_hours_to_close]) : ""])}{Object.keys(r.actions.outcomes).length ? ` · ${Object.entries(r.actions.outcomes).map(([k, v]) => `${v} ${t(k.replace(/_/g, " "))}`).join(", ")}` : ""}.</p>
            <Def text={`${r.definitions["action_age"] ?? ""} ${r.definitions["time_to_close"] ?? ""}`} />
          </div>
          <div className="panel data-panel">
            <h2 className="panel-title">{t("Quality checks")}</h2>
            <p className="muted-line"><b>{r.quality_checks.decisions}</b> {t("quality decisions in the period;")} <b className={r.quality_checks.same_person ? "late-text" : undefined}>{r.quality_checks.same_person}</b> {t("made by the person who also received the material.")}</p>
            <Def text={r.definitions["quality_checks"] ?? ""} />
          </div>
        </div>
      </>}
  </section>;
}
