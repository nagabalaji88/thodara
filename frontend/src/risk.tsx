import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ChevronDown, LoaderCircle, Plus } from "lucide-react";
import { ActionChips, NewActionDialog, type Suggestion, useOrderActions } from "./actions";
import { api } from "./api";
import { fmtDuration } from "./dependencies";
import { fmtDate } from "./orders";
import { locale, t, tk } from "./i18n";

export type Headline = "confirmed_late" | "quantity_shortage" | "at_risk" | "quality_hold" | "unknown" | "on_track" | "ready";

export interface RiskIssue { code: Headline; message: string }
export interface RiskAllocation {
  batch_number: string; batch_id: string; supplier_name: string; batch_status: string;
  allocated: string; accepted: string; awaiting: string; held: string; from_supplier: string; short: string;
  estimate_date: string | null; estimate_source: string | null; last_update_at: string | null; stale: boolean; ahead: string[];
}
export interface RiskComponent { item_code: string; unit_code: string; required: string; outsourced_operation: string | null; uncovered: string; usable_now: string; allocations: RiskAllocation[]; stock_tracked: boolean; in_stock: string; stock_ahead: string[] }
export interface LineRisk {
  line_id: string; order_id: string; order_number: string; customer_name: string; line_no: number; item_code: string; unit_code: string;
  remaining: string; promised_date: string | null; headline: Headline; issues: RiskIssue[]; notes: string[];
  components_ready_date: string | null; projected_finish: string | null; projected_date: string | null; slack_days: number | null;
  operation_minutes: number; components: RiskComponent[]; time_zone: string | null; suggestions: Suggestion[];
  stock_tracked: boolean; from_stock: string; stock_ahead: string[];
}
export interface RiskReport { computed_at: string; stale_after_hours: number; counts: Record<Headline, number>; lines: LineRisk[] }

export const HEADLINES: [Headline, string, string][] = [
  ["confirmed_late", tk("Late"), tk("The promised date has passed")],
  ["quantity_shortage", tk("Short"), tk("Not enough usable material is coming")],
  ["at_risk", tk("At risk"), tk("Projected to finish after the promise")],
  ["quality_hold", tk("Quality hold"), tk("Needed material is on hold")],
  ["unknown", tk("Unknown"), tk("Missing or stale information")],
  ["on_track", tk("On track"), tk("Projected to finish in time")],
  ["ready", tk("Ready"), tk("All outsourced material is usable")],
];
const LABEL = Object.fromEntries(HEADLINES.map(([k, l]) => [k, l])) as Record<Headline, string>;

export function RiskBadge({ headline }: { headline: Headline }) {
  return <span className={`badge risk-${headline}`}>{t(LABEL[headline])}</span>;
}

const slackText = (r: LineRisk) => r.slack_days === null ? "—" : r.slack_days >= 0 ? t(r.slack_days === 1 ? "{0} day spare" : "{0} days spare", [r.slack_days]) : t(r.slack_days === -1 ? "{0} day late" : "{0} days late", [-r.slack_days]);
const untracked = (r: { components: RiskComponent[] }) => r.components.filter((c) => !c.stock_tracked && !c.outsourced_operation && !c.allocations.length && Number(c.required) > 0).map((c) => c.item_code);
const computed = (iso: string) => new Date(iso).toLocaleTimeString(locale(), { hour: "2-digit", minute: "2-digit" });

export function useRiskBoard() {
  return useQuery({ queryKey: ["risk-board"], queryFn: () => api<RiskReport>("/api/v1/fulfillment/risk"), staleTime: 0 });
}

/** Every open order line, most severe first. */
export function RiskBoard() {
  const board = useRiskBoard();
  const [filter, setFilter] = useState<Headline | "">("");
  const lines = (board.data?.lines ?? []).filter((l) => !filter || l.headline === filter);
  return <section className="wrap page">
    <header className="page-head"><div><span className="eyebrow">{t("WILL IT SHIP ON TIME?")}</span><h1 className="page-title">{t("Delivery risk")}</h1></div><p className="lede small">{t("Every open order line, worked out from usable material, the supplier’s latest word and the remaining work on your site calendar. Missing information is shown as unknown, never as late.")}</p></header>
    {board.isError ? <div className="form-error" role="alert"><AlertCircle size={15} />{board.error.message}</div>
      : board.isPending ? <div className="table-state"><LoaderCircle className="spin" size={16} /> {t("Working it out…")}</div> : <>
        <div className="risk-tiles" role="group" aria-label={t("Filter by status")}>
          {HEADLINES.map(([key, label, note]) => <button key={key} type="button" className={`risk-tile risk-${key} ${filter === key ? "selected" : ""}`} aria-pressed={filter === key} onClick={() => setFilter(filter === key ? "" : key)}><strong>{board.data.counts[key]}</strong><span>{t(label)}</span><small>{t(note)}</small></button>)}
        </div>
        <div className="panel data-panel">
          {lines.length === 0 ? <div className="table-state">{filter ? t("No lines in this state.") : t("No open lines on confirmed orders.")}</div>
            : <div className="table-wrap"><table className="data-table">
              <thead><tr><th scope="col">{t("Status")}</th><th scope="col">{t("Order / line")}</th><th scope="col">{t("Customer")}</th><th scope="col">{t("Promised")}</th><th scope="col">{t("Projected")}</th><th scope="col">{t("Margin")}</th><th scope="col">{t("Why")}</th></tr></thead>
              <tbody>{lines.map((l) => <tr key={l.line_id} tabIndex={0} aria-label={t("Open {0}", [l.order_number])} onClick={() => { window.location.hash = `orders/${l.order_id}`; }} onKeyDown={(e) => { if (e.key === "Enter") window.location.hash = `orders/${l.order_id}`; }}>
                <td><RiskBadge headline={l.headline} /></td>
                <td className="mono">{l.order_number} / {l.line_no}<small className="cell-sub">{l.remaining} {l.unit_code} {l.item_code}</small></td>
                <td>{l.customer_name}</td><td className="date">{fmtDate(l.promised_date)}</td><td className="date">{fmtDate(l.projected_date)}</td>
                <td className={l.slack_days !== null && l.slack_days < 0 ? "late-text" : undefined}>{slackText(l)}</td>
                <td className="why">{l.issues[0]?.message ?? (l.headline === "ready" ? t("Outsourced material accepted and usable.") : t("On plan."))}{l.issues.length > 1 && <small className="cell-sub">+{t("{0} more", [l.issues.length - 1])}</small>}</td>
              </tr>)}</tbody>
            </table></div>}
          <p className="hint">{t("Worked out at {0}. A supplier is treated as stale after {1} hours without an update (Company & sites).", [computed(board.data.computed_at), board.data.stale_after_hours])}</p>
        </div>
      </>}
  </section>;
}

/** Risk for each open line of one order, with the full calculation. */
export function OrderRiskPanel({ orderId, version, siteId, canAct }: { orderId: string; version: number; siteId: string; canAct: boolean }) {
  const risk = useQuery({ queryKey: ["order-risk", orderId, version], queryFn: () => api<RiskReport>(`/api/v1/orders/${orderId}/risk`), staleTime: 0 });
  if (risk.isPending || risk.isError || risk.data.lines.length === 0) return null;
  return <>{risk.data.lines.map((l) => <LineRiskCard key={l.line_id} risk={l} report={risk.data} siteId={siteId} canAct={canAct} />)}</>;
}

function LineRiskCard({ risk: r, report, siteId, canAct }: { risk: LineRisk; report: RiskReport; siteId: string; canAct: boolean }) {
  const [open, setOpen] = useState(r.headline !== "on_track" && r.headline !== "ready");
  const [planning, setPlanning] = useState<Suggestion | "blank" | null>(null);
  const queryClient = useQueryClient();
  const actions = useOrderActions(r.order_id);
  const mine = (actions.data?.items ?? []).filter((a) => a.line?.line_id === r.line_id && (a.status === "open" || a.status === "awaiting_approval"));
  const taken = new Set(mine.map((a) => `${a.kind}|${a.batch?.batch_id ?? ""}`));
  const fresh = r.suggestions.filter((sg) => !taken.has(`${sg.kind}|${sg.batch_id ?? ""}`));
  return <section className={`panel risk-panel risk-edge-${r.headline}`} aria-labelledby={`risk-${r.line_id}`}>
    <header className="dependency-head">
      <div><span className="eyebrow">{t("LINE {0} · DELIVERY RISK", [r.line_no])}</span><h2 id={`risk-${r.line_id}`} className="panel-title"><RiskBadge headline={r.headline} /> {r.projected_date ? t("Projected ready {0}", [fmtDate(r.projected_date)]) : t("Projected date unknown")}</h2></div>
      <dl className="facts compact"><div><dt>{t("Promised")}</dt><dd>{fmtDate(r.promised_date)}</dd></div><div><dt>{t("Margin")}</dt><dd className={r.slack_days !== null && r.slack_days < 0 ? "late-text" : undefined}>{slackText(r)}</dd></div></dl>
    </header>
    {r.issues.length > 0 && <ul className="issue-list">{r.issues.map((i, n) => <li key={n}><RiskBadge headline={i.code} /><span>{i.message}</span></li>)}</ul>}
    {r.notes.map((n, i) => <p key={i} className="notice-line"><AlertCircle size={16} /><span>{n}</span></p>)}
    {mine.length > 0 && <div><span className="field-label">{t("Actions in progress")}</span><ActionChips actions={mine} /></div>}
    {canAct && (fresh.length > 0 || r.issues.length > 0) && <div className="suggestions">
      <span className="field-label">{t("Suggested next steps")} <span className="optional-inline">{t("from the rules above; nothing happens until you create one")}</span></span>
      <ul>{fresh.map((sg, i) => <li key={i}><span><b>{sg.title}</b><small>{sg.details}{sg.requires_approval ? t(" Needs approval.") : ""}</small></span><button type="button" className="quiet-button compact-pill" onClick={() => setPlanning(sg)}><Plus size={13} /> {t("Create action")}</button></li>)}</ul>
      <button type="button" className="text-button" onClick={() => setPlanning("blank")}><Plus size={12} /> {t("Plan a different action")}</button>
    </div>}
    {planning && <NewActionDialog siteId={siteId} lineId={r.line_id} suggestion={planning === "blank" ? undefined : planning} onClose={() => setPlanning(null)} onDone={(a) => { setPlanning(null); void queryClient.invalidateQueries({ queryKey: ["order-actions"] }); void queryClient.invalidateQueries({ queryKey: ["actions"] }); window.location.hash = `actions/${a.id}`; }} />}
    <button type="button" className="text-button calc-toggle" aria-expanded={open} onClick={() => setOpen(!open)}><ChevronDown size={13} className={open ? "flip" : undefined} /> {(open ? t("Hide the calculation") : t("Show the calculation"))}</button>
    {open && <ol className="calc">
      {r.stock_tracked && <li><b>{t("Finished goods: {0} {1} of the {2} open come from stock at the site.", [r.from_stock, r.unit_code, r.remaining])}</b>{r.stock_ahead.length > 0 && <span>{t(r.stock_ahead.length === 1 ? "Shared: {0} is served first (earlier promise)." : "Shared: {0} are served first (earlier promise).", [r.stock_ahead.join(", ")])}</span>}{Number(r.from_stock) < Number(r.remaining) && <span>{t("The rest has to be built from the components below.")}</span>}</li>}
      {r.components.filter((c) => c.stock_tracked && Number(c.required) > 0).map((c) => <li key={c.item_code}>
        <b>{t("{0}: needs {1} {2}", [c.item_code, c.required, c.unit_code])}; {t("{0} in stock for this line.", [c.in_stock])}</b>
        {c.stock_ahead.length > 0 && <span>{t(c.stock_ahead.length === 1 ? "Shared: {0} is served first (earlier promise)." : "Shared: {0} are served first (earlier promise).", [c.stock_ahead.join(", ")])}</span>}
      </li>)}
      {r.components.filter((c) => (c.outsourced_operation || c.allocations.length) && Number(c.required) > 0).map((c) => <li key={c.item_code}>
        <b>{t("{0}: needs {1} {2}{3}", [c.item_code, c.required, c.unit_code, c.outsourced_operation ? t(" after {0}", [c.outsourced_operation]) : ""])}; {t("{0} usable now.", [c.usable_now])}</b>
        {Number(c.uncovered) > 0 && <span className="late-text">{t("{0} {1} not covered by any batch.", [c.uncovered, c.unit_code])}</span>}
        {c.allocations.map((a) => <span key={a.batch_id}>
          <a href={`#outsourcing/${a.batch_id}`} className="mono">{a.batch_number}</a> ({t("{0}) linked {1}", [a.supplier_name, a.allocated])}: {[
            Number(a.accepted) && t("{0} accepted", [a.accepted]), Number(a.awaiting) && t("{0} awaiting inspection", [a.awaiting]), Number(a.held) && t("{0} on hold", [a.held]),
            Number(a.from_supplier) && t("{0} still to come from the supplier", [a.from_supplier]), Number(a.short) && t("{0} not expected at all", [a.short]),
          ].filter(Boolean).join(", ")}.
          {a.estimate_date && t(" Expected {0} ({1}).", [fmtDate(a.estimate_date), a.estimate_source])}
          {a.ahead.length > 0 && t(a.ahead.length === 1 ? " Shared: {0} is served first (earlier promise)." : " Shared: {0} are served first (earlier promise).", [a.ahead.join(", ")])}
          {a.stale && t(" Supplier information is stale.")}
        </span>)}
      </li>)}
      <li><b>{t("Material ready {0}", [r.components_ready_date ? fmtDate(r.components_ready_date) : t("— unknown")])}</b>{r.operation_minutes > 0 && <span>{t("then {0} of remaining work on the site calendar{1}", [fmtDuration(r.operation_minutes), r.projected_finish ? t(", finishing {0}", [new Date(r.projected_finish).toLocaleString(locale(), { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: r.time_zone ?? undefined })]) : ""])}.</span>}</li>
      <li><span className="hint">{t("{0}Worked out at {1}", [untracked(r).length > 0 ? t(untracked(r).length === 1 ? "{0} has no stock entered at this site, so it is assumed available. " : "{0} have no stock entered at this site, so they are assumed available. ", [untracked(r).join(", ")]) : "", computed(report.computed_at)])}.</span></li>
    </ol>}
  </section>;
}
