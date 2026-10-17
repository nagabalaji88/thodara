import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle, ChevronDown, LoaderCircle } from "lucide-react";
import { api } from "./api";
import { fmtDuration } from "./dependencies";
import { fmtDate } from "./orders";

export type Headline = "confirmed_late" | "quantity_shortage" | "at_risk" | "quality_hold" | "unknown" | "on_track" | "ready";

export interface RiskIssue { code: Headline; message: string }
export interface RiskAllocation {
  batch_number: string; batch_id: string; supplier_name: string; batch_status: string;
  allocated: string; accepted: string; awaiting: string; held: string; from_supplier: string; short: string;
  estimate_date: string | null; estimate_source: string | null; last_update_at: string | null; stale: boolean; ahead: string[];
}
export interface RiskComponent { item_code: string; unit_code: string; required: string; outsourced_operation: string | null; uncovered: string; usable_now: string; allocations: RiskAllocation[] }
export interface LineRisk {
  line_id: string; order_id: string; order_number: string; customer_name: string; line_no: number; item_code: string; unit_code: string;
  remaining: string; promised_date: string | null; headline: Headline; issues: RiskIssue[]; notes: string[];
  components_ready_date: string | null; projected_finish: string | null; projected_date: string | null; slack_days: number | null;
  operation_minutes: number; components: RiskComponent[]; time_zone: string | null;
}
export interface RiskReport { computed_at: string; stale_after_hours: number; counts: Record<Headline, number>; lines: LineRisk[] }

export const HEADLINES: [Headline, string, string][] = [
  ["confirmed_late", "Late", "The promised date has passed"],
  ["quantity_shortage", "Short", "Not enough usable material is coming"],
  ["at_risk", "At risk", "Projected to finish after the promise"],
  ["quality_hold", "Quality hold", "Needed material is on hold"],
  ["unknown", "Unknown", "Missing or stale information"],
  ["on_track", "On track", "Projected to finish in time"],
  ["ready", "Ready", "All outsourced material is usable"],
];
const LABEL = Object.fromEntries(HEADLINES.map(([k, l]) => [k, l])) as Record<Headline, string>;

export function RiskBadge({ headline }: { headline: Headline }) {
  return <span className={`badge risk-${headline}`}>{LABEL[headline]}</span>;
}

const slackText = (r: LineRisk) => r.slack_days === null ? "—" : r.slack_days >= 0 ? `${r.slack_days} day${r.slack_days === 1 ? "" : "s"} spare` : `${-r.slack_days} day${r.slack_days === -1 ? "" : "s"} late`;
const computed = (iso: string) => new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });

export function useRiskBoard() {
  return useQuery({ queryKey: ["risk-board"], queryFn: () => api<RiskReport>("/api/v1/fulfillment/risk"), staleTime: 0 });
}

/** Every open order line, most severe first. */
export function RiskBoard() {
  const board = useRiskBoard();
  const [filter, setFilter] = useState<Headline | "">("");
  const lines = (board.data?.lines ?? []).filter((l) => !filter || l.headline === filter);
  return <section className="wrap page">
    <header className="page-head"><div><span className="eyebrow">WILL IT SHIP ON TIME?</span><h1 className="page-title">Delivery risk</h1></div><p className="lede small">Every open order line, worked out from usable material, the supplier’s latest word and the remaining work on your site calendar. Missing information is shown as unknown, never as late.</p></header>
    {board.isError ? <div className="form-error" role="alert"><AlertCircle size={15} />{board.error.message}</div>
      : board.isPending ? <div className="table-state"><LoaderCircle className="spin" size={16} /> Working it out…</div> : <>
        <div className="risk-tiles" role="group" aria-label="Filter by status">
          {HEADLINES.map(([key, label, note]) => <button key={key} type="button" className={`risk-tile risk-${key} ${filter === key ? "selected" : ""}`} aria-pressed={filter === key} onClick={() => setFilter(filter === key ? "" : key)}><strong>{board.data.counts[key]}</strong><span>{label}</span><small>{note}</small></button>)}
        </div>
        <div className="panel data-panel">
          {lines.length === 0 ? <div className="table-state">{filter ? "No lines in this state." : "No open lines on confirmed orders."}</div>
            : <div className="table-wrap"><table className="data-table">
              <thead><tr><th scope="col">Status</th><th scope="col">Order / line</th><th scope="col">Customer</th><th scope="col">Promised</th><th scope="col">Projected</th><th scope="col">Margin</th><th scope="col">Why</th></tr></thead>
              <tbody>{lines.map((l) => <tr key={l.line_id} tabIndex={0} aria-label={`Open ${l.order_number}`} onClick={() => { window.location.hash = `orders/${l.order_id}`; }} onKeyDown={(e) => { if (e.key === "Enter") window.location.hash = `orders/${l.order_id}`; }}>
                <td><RiskBadge headline={l.headline} /></td>
                <td className="mono">{l.order_number} / {l.line_no}<small className="cell-sub">{l.remaining} {l.unit_code} {l.item_code}</small></td>
                <td>{l.customer_name}</td><td className="date">{fmtDate(l.promised_date)}</td><td className="date">{fmtDate(l.projected_date)}</td>
                <td className={l.slack_days !== null && l.slack_days < 0 ? "late-text" : undefined}>{slackText(l)}</td>
                <td className="why">{l.issues[0]?.message ?? (l.headline === "ready" ? "Outsourced material accepted and usable." : "On plan.")}{l.issues.length > 1 && <small className="cell-sub">+{l.issues.length - 1} more</small>}</td>
              </tr>)}</tbody>
            </table></div>}
          <p className="hint">Worked out at {computed(board.data.computed_at)}. A supplier is treated as stale after {board.data.stale_after_hours} hours without an update (Company &amp; sites).</p>
        </div>
      </>}
  </section>;
}

/** Risk for each open line of one order, with the full calculation. */
export function OrderRiskPanel({ orderId, version }: { orderId: string; version: number }) {
  const risk = useQuery({ queryKey: ["order-risk", orderId, version], queryFn: () => api<RiskReport>(`/api/v1/orders/${orderId}/risk`), staleTime: 0 });
  if (risk.isPending || risk.isError || risk.data.lines.length === 0) return null;
  return <>{risk.data.lines.map((l) => <LineRiskCard key={l.line_id} risk={l} report={risk.data} />)}</>;
}

function LineRiskCard({ risk: r, report }: { risk: LineRisk; report: RiskReport }) {
  const [open, setOpen] = useState(r.headline !== "on_track" && r.headline !== "ready");
  return <section className={`panel risk-panel risk-edge-${r.headline}`} aria-labelledby={`risk-${r.line_id}`}>
    <header className="dependency-head">
      <div><span className="eyebrow">LINE {r.line_no} · DELIVERY RISK</span><h2 id={`risk-${r.line_id}`} className="panel-title"><RiskBadge headline={r.headline} /> {r.projected_date ? `Projected ready ${fmtDate(r.projected_date)}` : "Projected date unknown"}</h2></div>
      <dl className="facts compact"><div><dt>Promised</dt><dd>{fmtDate(r.promised_date)}</dd></div><div><dt>Margin</dt><dd className={r.slack_days !== null && r.slack_days < 0 ? "late-text" : undefined}>{slackText(r)}</dd></div></dl>
    </header>
    {r.issues.length > 0 && <ul className="issue-list">{r.issues.map((i, n) => <li key={n}><RiskBadge headline={i.code} /><span>{i.message}</span></li>)}</ul>}
    {r.notes.map((n, i) => <p key={i} className="notice-line"><AlertCircle size={16} /><span>{n}</span></p>)}
    <button type="button" className="text-button calc-toggle" aria-expanded={open} onClick={() => setOpen(!open)}><ChevronDown size={13} className={open ? "flip" : undefined} /> {open ? "Hide" : "Show"} the calculation</button>
    {open && <ol className="calc">
      {r.components.filter((c) => c.outsourced_operation || c.allocations.length).map((c) => <li key={c.item_code}>
        <b>{c.item_code}: needs {c.required} {c.unit_code}{c.outsourced_operation ? ` after ${c.outsourced_operation}` : ""}; {c.usable_now} usable now.</b>
        {Number(c.uncovered) > 0 && <span className="late-text">{c.uncovered} {c.unit_code} not covered by any batch.</span>}
        {c.allocations.map((a) => <span key={a.batch_id}>
          <a href={`#outsourcing/${a.batch_id}`} className="mono">{a.batch_number}</a> ({a.supplier_name}) linked {a.allocated}: {[
            Number(a.accepted) && `${a.accepted} accepted`, Number(a.awaiting) && `${a.awaiting} awaiting inspection`, Number(a.held) && `${a.held} on hold`,
            Number(a.from_supplier) && `${a.from_supplier} still to come from the supplier`, Number(a.short) && `${a.short} not expected at all`,
          ].filter(Boolean).join(", ")}.
          {a.estimate_date && ` Expected ${fmtDate(a.estimate_date)} (${a.estimate_source}).`}
          {a.ahead.length > 0 && ` Shared: ${a.ahead.join(", ")} ${a.ahead.length === 1 ? "is" : "are"} served first (earlier promise).`}
          {a.stale && " Supplier information is stale."}
        </span>)}
      </li>)}
      <li><b>Material ready {r.components_ready_date ? fmtDate(r.components_ready_date) : "— unknown"}</b>{r.operation_minutes > 0 && <span>then {fmtDuration(r.operation_minutes)} of remaining work on the site calendar{r.projected_finish ? `, finishing ${new Date(r.projected_finish).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: r.time_zone ?? undefined })}` : ""}.</span>}</li>
      <li><span className="hint">Components that are not outsourced are not tracked yet (no stock module); they are assumed available. Worked out at {computed(report.computed_at)}.</span></li>
    </ol>}
  </section>;
}
