import { useEffect, useMemo, useRef, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowRightLeft, Check, FileUp, LoaderCircle, Plus, Search, Trash2, X } from "lucide-react";
import { api, type ApiError } from "./api";
import type { ImportReport, MasterRecord, Page, Site, UnitConversion } from "./types";
import { locale, t, tk } from "./i18n";

type Entity = "items" | "customers" | "suppliers" | "units" | "warehouses";
type Tab = Entity | "import";
type FieldKind = "text" | "email" | "tel" | "select" | "checkbox" | "number" | "unit" | "site" | "textarea";

interface FieldDef {
  name: string;
  label: string;
  kind: FieldKind;
  required?: boolean;
  createOnly?: boolean;
  options?: [string, string][];
  max?: number;
}

interface EntityDef {
  label: string;
  singular: string;
  permission: string;
  fields: FieldDef[];
  columns: { label: string; render: (row: MasterRecord, lookups: Lookups) => string }[];
}

interface Lookups {
  units: Map<string, string>;
  sites: Map<string, string>;
}

const label = (value: unknown) => t(String(value ?? "").replaceAll("_", " "));
// Phrases label() builds from stored keys, listed so they are translated.
tk("raw material"); tk("component"); tk("intermediate"); tk("finished good"); tk("packaging"); tk("consumable"); tk("service"); tk("lot"); tk("serial");
tk("count"); tk("mass"); tk("length"); tk("area"); tk("volume"); tk("time");
const ITEM_TYPES: [string, string][] = ["raw_material", "component", "intermediate", "finished_good", "packaging", "consumable", "service"].map((v) => [v, label(v)]);
const TRACKING: [string, string][] = [["none", tk("No tracking")], ["lot", tk("Lot / batch")], ["serial", tk("Serial number")]];
const DIMENSIONS: [string, string][] = ["count", "mass", "length", "area", "volume", "time"].map((v) => [v, v]);
const code: FieldDef = { name: "code", label: tk("Code"), kind: "text", required: true, createOnly: true, max: 40 };
const name: FieldDef = { name: "name", label: tk("Name"), kind: "text", required: true, max: 160 };
const contact: FieldDef[] = [
  { name: "contact_email", label: tk("Contact email"), kind: "email", max: 254 },
  { name: "contact_phone", label: tk("Contact phone"), kind: "tel", max: 32 },
  { name: "city", label: tk("City"), kind: "text", max: 120 },
];

export const ENTITIES: Record<Entity, EntityDef> = {
  items: {
    label: tk("Items"), singular: tk("item"), permission: "items:manage",
    fields: [code, name,
      { name: "item_type", label: tk("Item type"), kind: "select", required: true, options: ITEM_TYPES },
      { name: "base_unit_id", label: tk("Base unit"), kind: "unit", required: true },
      { name: "tracking", label: tk("Tracking"), kind: "select", required: true, options: TRACKING },
      { name: "description", label: tk("Description"), kind: "textarea", max: 500 }],
    columns: [
      { label: tk("Type"), render: (r) => label(r.item_type) },
      { label: tk("Unit"), render: (r, l) => l.units.get(String(r.base_unit_id)) ?? "—" },
      { label: tk("Tracking"), render: (r) => (r.tracking === "none" ? "—" : label(r.tracking)) },
    ],
  },
  customers: {
    label: tk("Customers"), singular: tk("customer"), permission: "customers:manage",
    fields: [code, name, ...contact],
    columns: [{ label: tk("City"), render: (r) => String(r.city ?? "—") }, { label: tk("Contact"), render: (r) => String(r.contact_email ?? r.contact_phone ?? "—") }],
  },
  suppliers: {
    label: tk("Suppliers"), singular: tk("supplier"), permission: "suppliers:manage",
    fields: [code, name, ...contact, { name: "provides_job_work", label: tk("Does job work (outsourced operations)"), kind: "checkbox" }],
    columns: [{ label: tk("City"), render: (r) => String(r.city ?? "—") }, { label: tk("Job work"), render: (r) => (r.provides_job_work ? t("Yes") : t("No")) }],
  },
  units: {
    label: tk("Units"), singular: tk("unit"), permission: "units:manage",
    fields: [code, name,
      { name: "dimension", label: tk("Measures"), kind: "select", required: true, createOnly: true, options: DIMENSIONS },
      { name: "decimal_places", label: tk("Decimal places"), kind: "number", required: true }],
    columns: [{ label: tk("Measures"), render: (r) => t(String(r.dimension)) }, { label: tk("Decimals"), render: (r) => String(r.decimal_places) }],
  },
  warehouses: {
    label: tk("Warehouses"), singular: tk("warehouse"), permission: "warehouses:manage",
    fields: [code, name, { name: "site_id", label: tk("Site"), kind: "site", required: true, createOnly: true }],
    columns: [{ label: tk("Site"), render: (r, l) => l.sites.get(String(r.site_id)) ?? "—" }],
  },
};

const TABS: Tab[] = ["items", "customers", "suppliers", "units", "warehouses", "import"];
const DEFAULTS: Record<Entity, Record<string, unknown>> = {
  items: { item_type: "component", tracking: "none" },
  customers: {},
  suppliers: { provides_job_work: false },
  units: { dimension: "count", decimal_places: 0 },
  warehouses: {},
};

function useLookups() {
  const units = useQuery({ queryKey: ["md", "units", "lookup"], queryFn: () => api<Page<MasterRecord>>("/api/v1/master-data/units?limit=200") });
  const sites = useQuery({ queryKey: ["sites"], queryFn: () => api<Site[]>("/api/v1/organization/sites") });
  return useMemo(() => ({
    unitRecords: units.data?.items ?? [],
    siteRecords: sites.data ?? [],
    lookups: {
      units: new Map((units.data?.items ?? []).map((u) => [u.id, u.code])),
      sites: new Map((sites.data ?? []).map((s) => [s.id, s.name])),
    } satisfies Lookups,
  }), [units.data, sites.data]);
}

export function MasterDataPage({ tab, permissions }: { tab: string; permissions: string[] }) {
  const current: Tab = (TABS as string[]).includes(tab) ? (tab as Tab) : "items";
  return <section className="wrap page">
    <header className="page-head"><div><span className="eyebrow">{t("MASTER DATA")}</span><h1 className="page-title">{t("Master data")}</h1></div><p className="lede small">{t("The shared records every order, work order and dispatch will refer to. Codes are unique across your company; records are deactivated, never deleted.")}</p></header>
    <nav className="tabs" aria-label={t("Master data sections")}>{TABS.map((key) => <a key={key} href={`#master-data/${key}`} className={key === current ? "tab active" : "tab"} aria-current={key === current ? "page" : undefined}>{key === "import" ? t("Import") : t(ENTITIES[key].label)}</a>)}</nav>
    {current === "import" ? <ImportPanel permissions={permissions} /> : <EntityPanel key={current} entity={current} canManage={permissions.includes(ENTITIES[current].permission)} />}
  </section>;
}

function EntityPanel({ entity, canManage }: { entity: Entity; canManage: boolean }) {
  const def = ENTITIES[entity];
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("active");
  const [offset, setOffset] = useState(0);
  const [editing, setEditing] = useState<MasterRecord | "new" | null>(null);
  const limit = 25;
  const { lookups, unitRecords, siteRecords } = useLookups();
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (q.trim()) params.set("q", q.trim());
  if (status) params.set("status", status);
  const list = useQuery({
    queryKey: ["md", entity, q, status, offset],
    queryFn: () => api<Page<MasterRecord>>(`/api/v1/master-data/${entity}?${params}`),
    placeholderData: keepPreviousData,
  });
  useEffect(() => setOffset(0), [q, status]);
  const total = list.data?.total ?? 0;

  return <div className="panel data-panel">
    <div className="toolbar">
      <label className="search-field"><Search size={14} /><input aria-label={t("Search {0}", [t(def.label).toLowerCase()])} placeholder={t("Search code or name")} value={q} maxLength={80} onChange={(e) => setQ(e.target.value)} /></label>
      <select aria-label={t("Status")} value={status} onChange={(e) => setStatus(e.target.value)}><option value="active">{t("Active")}</option><option value="inactive">{t("Inactive")}</option><option value="">{t("All")}</option></select>
      <span className="toolbar-spacer" />
      {canManage && <button className="primary-button compact" onClick={() => setEditing("new")}><Plus size={15} /> {t("New {0}", [t(def.singular)])}</button>}
    </div>
    {list.isError ? <div className="form-error" role="alert"><AlertCircle size={15} />{list.error.message}</div>
      : list.isPending ? <div className="table-state"><LoaderCircle className="spin" size={16} /> {t("Loading…")}</div>
        : total === 0 ? <div className="table-state">{q ? t("Nothing matches that search.") : t("No {0} yet.", [t(def.label).toLowerCase()])}{canManage && !q && <button className="quiet-button" onClick={() => setEditing("new")}><Plus size={14} /> {t("Add the first {0}", [t(def.singular)])}</button>}</div>
          : <div className="table-wrap"><table className="data-table">
            <thead><tr><th scope="col">{t("Code")}</th><th scope="col">{t("Name")}</th>{def.columns.map((c) => <th scope="col" key={c.label}>{t(c.label)}</th>)}<th scope="col">{t("Status")}</th></tr></thead>
            <tbody>{list.data.items.map((row) => <tr key={row.id} onClick={() => setEditing(row)} tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter") setEditing(row); }} aria-label={t("Open {0}", [row.code])}>
              <td className="mono">{row.code}</td><td>{row.name}</td>{def.columns.map((c) => <td key={c.label}>{c.render(row, lookups)}</td>)}<td><span className={`badge badge-${row.status}`}>{t(row.status === "active" ? "Active" : "Inactive")}</span></td>
            </tr>)}</tbody>
          </table></div>}
    {total > limit && <div className="pager"><span>{offset + 1}–{t("{0} of {1}", [Math.min(offset + limit, total), total])}</span><button className="quiet-button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>{t("Previous")}</button><button className="quiet-button" disabled={offset + limit >= total} onClick={() => setOffset(offset + limit)}>{t("Next")}</button></div>}
    {entity === "units" && <ConversionsPanel units={unitRecords} canManage={canManage} />}
    {editing && <RecordDialog entity={entity} record={editing === "new" ? null : editing} canManage={canManage} units={unitRecords} sites={siteRecords} onClose={() => setEditing(null)} />}
  </div>;
}

function RecordDialog({ entity, record, canManage, units, sites, onClose }: {
  entity: Entity; record: MasterRecord | null; canManage: boolean; units: MasterRecord[]; sites: Site[]; onClose: () => void;
}) {
  const def = ENTITIES[entity];
  const queryClient = useQueryClient();
  const original = record as unknown as Record<string, unknown> | null;
  const [values, setValues] = useState<Record<string, unknown>>(() => original ? { ...original } : { ...DEFAULTS[entity] });
  const firstInput = useRef<HTMLElement | null>(null);
  useEffect(() => {
    firstInput.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) => record
      ? api<MasterRecord>(`/api/v1/master-data/${entity}/${record.id}`, { method: "PATCH", body: JSON.stringify(body) })
      : api<MasterRecord>(`/api/v1/master-data/${entity}`, { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["md"] }); onClose(); },
  });

  const editable = def.fields.filter((f) => !(record && f.createOnly));
  function submit(extra: Record<string, unknown> = {}) {
    if (!record) {
      const body: Record<string, unknown> = {};
      for (const f of def.fields) if (values[f.name] !== undefined && values[f.name] !== "") body[f.name] = values[f.name];
      save.mutate(body);
      return;
    }
    const body: Record<string, unknown> = { version: record.version, ...extra };
    for (const f of editable) {
      const before = original?.[f.name] ?? (f.kind === "checkbox" ? false : "");
      const after = values[f.name] ?? (f.kind === "checkbox" ? false : "");
      if (before !== after) body[f.name] = after;
    }
    save.mutate(body);
  }

  const activeUnits = units.filter((u) => u.status === "active" || u.id === values["base_unit_id"]);
  const activeSites = sites.filter((s) => s.status === "active");
  const stale = (save.error as ApiError | null)?.status === 409 && save.error?.message.includes("changed by someone else");
  return <div className="dialog-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <form className="dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title" onSubmit={(e) => { e.preventDefault(); submit(); }}>
      <header><div><span className="eyebrow">{t(def.label).toUpperCase()}</span><h2 id="dialog-title">{record ? `${record.code} · ${record.name}` : t("New {0}", [t(def.singular)])}</h2></div><button type="button" className="icon-button" onClick={onClose} aria-label={t("Close")}><X size={16} /></button></header>
      <div className="dialog-grid">{def.fields.map((f, index) => {
        const locked = !canManage || (record !== null && f.createOnly);
        const common = { id: `f-${f.name}`, disabled: locked, required: f.required, ref: index === 0 ? (el: HTMLElement | null) => { firstInput.current = el; } : undefined };
        const value = values[f.name];
        const set = (v: unknown) => setValues((prev) => ({ ...prev, [f.name]: v }));
        let control: React.ReactNode;
        if (f.kind === "select") control = <select {...common} value={String(value ?? "")} onChange={(e) => set(e.target.value)}>{f.options!.map(([v, l]) => <option key={v} value={v}>{t(l)}</option>)}</select>;
        else if (f.kind === "unit") control = <select {...common} value={String(value ?? "")} onChange={(e) => set(e.target.value)}><option value="" disabled>{t("Choose a unit")}</option>{activeUnits.map((u) => <option key={u.id} value={u.id}>{u.code} · {u.name}</option>)}</select>;
        else if (f.kind === "site") control = <select {...common} value={String(value ?? "")} onChange={(e) => set(e.target.value)}><option value="" disabled>{t("Choose a site")}</option>{activeSites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>;
        else if (f.kind === "checkbox") return <label key={f.name} className="check-field wide"><input {...common} type="checkbox" checked={Boolean(value)} onChange={(e) => set(e.target.checked)} />{t(f.label)}</label>;
        else if (f.kind === "number") control = <input {...common} type="number" min={0} max={6} step={1} value={Number(value ?? 0)} onChange={(e) => set(Number(e.target.value))} />;
        else if (f.kind === "textarea") control = <textarea {...common} maxLength={f.max} rows={3} value={String(value ?? "")} onChange={(e) => set(e.target.value)} />;
        else control = <input {...common} type={f.kind} maxLength={f.max} value={String(value ?? "")} onChange={(e) => set(f.name === "code" ? e.target.value.toUpperCase() : e.target.value)} autoComplete="off" />;
        return <label key={f.name} htmlFor={`f-${f.name}`} className={f.kind === "textarea" ? "wide" : undefined}>{t(f.label)}{!f.required && <span className="optional">{t("OPTIONAL")}</span>}{control}</label>;
      })}</div>
      {entity === "units" && !record && <p className="hint">{t("Decimal places set how precisely quantities in this unit are recorded. The kind of measure cannot be changed later.")}</p>}
      {entity === "items" && <p className="hint">{t("Tax classification (HSN/GST) is not captured yet; it waits on confirmed tax scope.")}</p>}
      {save.error && <div className="form-error" role="alert"><AlertCircle size={15} /><span>{save.error.message}{stale && <> <button type="button" className="text-button" onClick={() => { void queryClient.invalidateQueries({ queryKey: ["md"] }); onClose(); }}>{t("Reload list")}</button></>}</span></div>}
      {record && <p className="meta">{t("Version {0} · updated {1}", [record.version, new Date(record.updated_at).toLocaleString(locale())])}</p>}
      {canManage && <footer>
        {record && <button type="button" className="quiet-button" disabled={save.isPending} onClick={() => submit({ status: record.status === "active" ? "inactive" : "active" })}>{record.status === "active" ? t("Deactivate") : t("Reactivate")}</button>}
        <span className="toolbar-spacer" />
        <button type="button" className="quiet-button" onClick={onClose}>{t("Cancel")}</button>
        <button type="submit" className="primary-button compact" disabled={save.isPending}>{save.isPending ? <LoaderCircle className="spin" size={15} /> : <Check size={15} />} {record ? t("Save changes") : t("Create {0}", [t(def.singular)])}</button>
      </footer>}
    </form>
  </div>;
}

function ConversionsPanel({ units, canManage }: { units: MasterRecord[]; canManage: boolean }) {
  const queryClient = useQueryClient();
  const conversions = useQuery({ queryKey: ["md", "conversions"], queryFn: () => api<UnitConversion[]>("/api/v1/master-data/unit-conversions") });
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [factor, setFactor] = useState("");
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["md", "conversions"] });
  const add = useMutation({
    mutationFn: () => api<UnitConversion>("/api/v1/master-data/unit-conversions", { method: "POST", body: JSON.stringify({ from_unit_id: from, to_unit_id: to, factor }) }),
    onSuccess: () => { setFactor(""); refresh(); },
  });
  const remove = useMutation({ mutationFn: (id: string) => api<void>(`/api/v1/master-data/unit-conversions/${id}`, { method: "DELETE" }), onSuccess: refresh });
  const active = units.filter((u) => u.status === "active");
  const fromUnit = active.find((u) => u.id === from);
  return <section className="sub-panel">
    <div className="sub-head"><ArrowRightLeft size={15} /><h3>{t("Unit conversions")}</h3><p>{t("Only units that measure the same thing can be converted, e.g. KG → G, BOX → PCS.")}</p></div>
    {conversions.data?.length ? <ul className="conversion-list">{conversions.data.map((c) => <li key={c.id}><span className="mono">1 {c.from_unit_code} = {trimDecimal(c.factor)} {c.to_unit_code}</span>{canManage && <button className="icon-button small" aria-label={t("Delete conversion {0} to {1}", [c.from_unit_code, c.to_unit_code])} onClick={() => remove.mutate(c.id)}><Trash2 size={13} /></button>}</li>)}</ul> : <p className="muted-line">{t("No conversions defined.")}</p>}
    {canManage && <form className="conversion-form" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
      <span>1</span>
      <select aria-label={t("From unit")} value={from} onChange={(e) => setFrom(e.target.value)} required><option value="" disabled>{t("From")}</option>{active.map((u) => <option key={u.id} value={u.id}>{u.code}</option>)}</select>
      <span>=</span>
      <input aria-label={t("Factor")} inputMode="decimal" pattern="^\d+(\.\d{1,12})?$" placeholder="1000" value={factor} onChange={(e) => setFactor(e.target.value)} required />
      <select aria-label={t("To unit")} value={to} onChange={(e) => setTo(e.target.value)} required><option value="" disabled>{t("To")}</option>{active.filter((u) => !fromUnit || (u.dimension === fromUnit.dimension && u.id !== fromUnit.id)).map((u) => <option key={u.id} value={u.id}>{u.code}</option>)}</select>
      <button className="quiet-button" disabled={add.isPending} type="submit"><Plus size={14} /> {t("Add")}</button>
    </form>}
    {(add.error || remove.error) && <div className="form-error" role="alert"><AlertCircle size={15} />{(add.error ?? remove.error)?.message}</div>}
  </section>;
}

function trimDecimal(value: string) {
  return value.includes(".") ? value.replace(/0+$/, "").replace(/\.$/, "") : value;
}

const TEMPLATES: Record<string, string> = {
  customers: "code,name,contact_email,contact_phone,city\n",
  suppliers: "code,name,contact_email,contact_phone,city,provides_job_work\n",
  items: "code,name,item_type,base_unit_code,tracking,description\n",
};

function ImportPanel({ permissions }: { permissions: string[] }) {
  const allowed = (["customers", "suppliers", "items"] as const).filter((e) => permissions.includes(ENTITIES[e].permission));
  const queryClient = useQueryClient();
  const [entity, setEntity] = useState<string>(allowed[0] ?? "");
  const [csvText, setCsvText] = useState("");
  const [fileName, setFileName] = useState("");
  const [fileError, setFileError] = useState<string | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const run = useMutation({
    mutationFn: (commit: boolean) => api<ImportReport>(`/api/v1/master-data/imports/${entity}`, { method: "POST", body: JSON.stringify({ csv_text: csvText, commit }) }),
    onSuccess: (value) => { setReport(value); if (value.committed) void queryClient.invalidateQueries({ queryKey: ["md"] }); },
    onError: (error: ApiError) => { const body = error.body as ImportReport | undefined; if (body && "errors" in body) setReport(body); },
  });
  if (!allowed.length) return <div className="panel data-panel"><div className="table-state">{t("Your role cannot import master data.")}</div></div>;
  const templateHref = `data:text/csv;charset=utf-8,${encodeURIComponent(TEMPLATES[entity] ?? "")}`;
  return <div className="panel data-panel import-panel">
    <div className="sub-head"><FileUp size={15} /><h3>{t("Import from a spreadsheet")}</h3><p>{t("Preview first. Nothing is saved until you import, and a file with any error is rejected as a whole. Re-importing the same file creates nothing new.")}</p></div>
    <div className="import-controls">
      <label>{t("Records")}<select value={entity} onChange={(e) => { setEntity(e.target.value); setReport(null); }}>{allowed.map((e) => <option key={e} value={e}>{t(ENTITIES[e].label)}</option>)}</select></label>
      <label>{t("CSV file (max 500 KB)")}<input type="file" accept=".csv,text/csv" onChange={(e) => {
        const file = e.target.files?.[0];
        setReport(null); setFileError(null); setCsvText(""); setFileName(file?.name ?? "");
        if (!file) return;
        if (file.size > 500_000) { setFileError(t("This file is larger than 500 KB. Split it into smaller files.")); return; }
        void file.text().then(setCsvText);
      }} /></label>
      <a className="text-link" href={templateHref} download={`${entity}-template.csv`}>{t("Download a blank template")}</a>
    </div>
    {fileError && <div className="form-error" role="alert"><AlertCircle size={15} />{fileError}</div>}
    <div className="import-actions">
      <button className="quiet-button" disabled={!csvText || run.isPending} onClick={() => run.mutate(false)}>{t("Preview")} {fileName && `“${fileName}”`}</button>
      <button className="primary-button compact" disabled={!report || report.committed || report.errors.length > 0 || report.to_create === 0 || run.isPending} onClick={() => run.mutate(true)}>{run.isPending ? <LoaderCircle className="spin" size={15} /> : <Check size={15} />} {t("Import {0} new", [report?.to_create ?? ""])}</button>
    </div>
    {run.error && !report && <div className="form-error" role="alert"><AlertCircle size={15} />{run.error.message}</div>}
    {report && <div className="import-report" aria-live="polite">
      <div className="report-stats"><span><b>{report.total_rows}</b> {t("rows")}</span><span><b>{report.to_create}</b> {t("new")}</span><span><b>{report.unchanged}</b> {t("already present")}</span><span className={report.errors.length ? "bad" : "good"}><b>{report.errors.length}</b> {t("problems")}</span></div>
      {report.committed && <p className="success-line"><Check size={14} /> {t("Imported {0} {1}", [report.to_create, t(ENTITIES[entity as Entity].label).toLowerCase()])}.</p>}
      {report.errors.length > 0 && <div className="table-wrap"><table className="data-table compact-table"><thead><tr><th scope="col">{t("Row")}</th><th scope="col">{t("Column")}</th><th scope="col">{t("Problem")}</th></tr></thead><tbody>{report.errors.map((err, i) => <tr key={i}><td>{err.row}</td><td className="mono">{err.field ?? "—"}</td><td>{err.message}</td></tr>)}</tbody></table></div>}
    </div>}
  </div>;
}
