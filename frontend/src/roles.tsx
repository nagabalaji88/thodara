import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Check, KeyRound, LoaderCircle, Lock, Plus, X } from "lucide-react";
import { api, type ApiError } from "./api";
import { t, tk } from "./i18n";

export interface RoleInfo { key: string; name: string; description: string | null; permissions: string[]; standard: boolean; changed: boolean; locked: boolean; members: number; version: number | null }
interface Catalogue { key: string; group: string; label: string }
export interface RolesData { catalogue: Catalogue[]; roles: RoleInfo[] }

export function useRoles(enabled = true) {
  return useQuery({ queryKey: ["roles"], queryFn: () => api<RolesData>("/api/v1/organization/roles"), enabled, staleTime: 0 });
}

/** Roles and what each may do. Administrators are locked with every permission (ADR-0011). */
export function RolesPanel({ canManage }: { canManage: boolean }) {
  const roles = useRoles();
  const [editing, setEditing] = useState<RoleInfo | "new" | null>(null);
  const data = roles.data;
  return <div className="panel data-panel">
    <div className="sub-head"><KeyRound size={15} /><h3>{t("Roles")}</h3><p>{t("What each role may do. Changes apply at once to everyone who holds the role. The administrator role always has every permission, so the company can never lock itself out.")}</p></div>
    {roles.isPending ? <div className="table-state"><LoaderCircle className="spin" size={16} /> {t("Loading…")}</div>
      : roles.isError ? <div className="form-error" role="alert"><AlertCircle size={15} />{roles.error.message}</div>
        : <div className="table-wrap"><table className="data-table">
          <thead><tr><th scope="col">{t("Role")}</th><th scope="col">{t("Can")}</th><th scope="col" className="num">{t("Members")}</th>{canManage && <th scope="col"><span className="sr-only">{t("Edit")}</span></th>}</tr></thead>
          <tbody>{data!.roles.map((r) => <tr key={r.key} className="static-row">
            <td><b>{r.standard ? t(r.name) : r.name}</b>{r.locked && <Lock size={12} aria-label={t("Locked")} className="inline-icon" />}<small className="cell-sub">{r.locked ? t("Locked · every permission") : r.standard ? (r.changed ? t("Standard role, changed by your company") : t("Standard role")) : t("Your company's role")}{r.description ? ` · ${r.description}` : ""}</small></td>
            <td><small className="cell-sub">{summary(r, data!.catalogue)}</small></td>
            <td className="num">{r.members}</td>
            {canManage && <td className="row-actions">{!r.locked && <button className="text-button" onClick={() => setEditing(r)}>{t("Edit")}</button>}</td>}
          </tr>)}</tbody>
        </table></div>}
    {canManage && <div className="inline-form"><button className="quiet-button" onClick={() => setEditing("new")}><Plus size={14} /> {t("New role")}</button></div>}
    {editing && data && <RoleDialog role={editing === "new" ? null : editing} catalogue={data.catalogue} onClose={() => setEditing(null)} />}
  </div>;
}

function summary(r: RoleInfo, catalogue: Catalogue[]): string {
  const doing = catalogue.filter((c) => c.group !== "See" && r.permissions.includes(c.key)).map((c) => t(c.label).toLowerCase());
  return doing.length ? doing.join("; ") : t("See only");
}

function RoleDialog({ role, catalogue, onClose }: { role: RoleInfo | null; catalogue: Catalogue[]; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(role?.name ?? "");
  const [description, setDescription] = useState(role?.description ?? "");
  const [chosen, setChosen] = useState<Set<string>>(new Set(role?.permissions ?? ["workspace:read"]));
  useEffect(() => { const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); }; window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k); }, [onClose]);
  const groups = useMemo(() => {
    const out = new Map<string, Catalogue[]>();
    for (const c of catalogue) out.set(c.group, [...(out.get(c.group) ?? []), c]);
    return [...out.entries()];
  }, [catalogue]);
  const done = () => { for (const k of ["roles", "members", "workspace"]) void queryClient.invalidateQueries({ queryKey: [k] }); onClose(); };
  const body = () => JSON.stringify({ name, description: description || null, permissions: [...chosen], ...(role ? { version: role.version } : {}) });
  const save = useMutation({
    mutationFn: () => role ? api(`/api/v1/organization/roles/${role.key}`, { method: "PUT", body: body() }) : api("/api/v1/organization/roles", { method: "POST", body: body() }),
    onSuccess: done,
  });
  const remove = useMutation({ mutationFn: () => api(`/api/v1/organization/roles/${role!.key}?version=${role!.version}`, { method: "DELETE" }), onSuccess: done });
  const error = save.error ?? remove.error;
  return <div className="dialog-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
    <form className="dialog wide-dialog" role="dialog" aria-modal="true" aria-labelledby="role-title" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
      <header><div><span className="eyebrow">{role ? (role.standard ? "STANDARD ROLE" : "YOUR ROLE") + ` · ${role.members} member${role.members === 1 ? "" : "s"}` : t("NEW ROLE")}</span><h2 id="role-title">{role ? t("Edit {0}", [role.name]) : t("New role")}</h2></div><button type="button" className="icon-button" onClick={onClose} aria-label={t("Close")}><X size={16} /></button></header>
      <div className="dialog-grid">
        <label>{t("Name")}<input value={name} onChange={(e) => setName(e.target.value)} required minLength={2} maxLength={60} placeholder={t("e.g. Shift supervisor")} autoFocus /></label>
        <label>{t("Description")} <span className="optional">{t("OPTIONAL")}</span><input value={description} onChange={(e) => setDescription(e.target.value)} maxLength={300} /></label>
      </div>
      <div className="permission-groups">{groups.map(([group, items]) => <fieldset key={group} className="permission-group"><legend>{t(group)}</legend>
        {items.map((c) => <label key={c.key} className="check-field"><input type="checkbox" checked={chosen.has(c.key)} disabled={c.key === "workspace:read"} onChange={(e) => { const next = new Set(chosen); if (e.target.checked) next.add(c.key); else next.delete(c.key); setChosen(next); }} />{t(c.label)}</label>)}
      </fieldset>)}</div>
      <p className="hint">{t("Approvers can never approve what they entered themselves unless your company allows it under Delivery risk settings. Every change is recorded with your name.")}</p>
      {error && <div className="form-error" role="alert"><AlertCircle size={15} /><span>{error.message}{(error as ApiError).status === 409 && error.message.includes("changed") ? t(" Reload the page.") : ""}</span></div>}
      <footer>
        {role && role.changed && <button type="button" className="quiet-button" disabled={remove.isPending} onClick={() => remove.mutate()}>{t("Reset to standard")}</button>}
        {role && !role.standard && <button type="button" className="quiet-button danger" disabled={remove.isPending} onClick={() => remove.mutate()}>{t("Delete role")}</button>}
        <span className="toolbar-spacer" /><button type="button" className="quiet-button" onClick={onClose}>{t("Back")}</button>
        <button type="submit" className="primary-button compact" disabled={save.isPending}>{save.isPending ? <LoaderCircle className="spin" size={15} /> : <Check size={15} />} {role ? t("Save role") : t("Create role")}</button>
      </footer>
    </form>
  </div>;
}

// Server-provided catalogue and standard role names (app/services/roles.py), translated here.
export const ROLE_PHRASES = [
  tk("See"),
  tk("Open the workspace (always on)"),
  tk("See master data"),
  tk("See orders, delivery risk, dispatch and reports"),
  tk("See outsourced batches"),
  tk("See recovery actions"),
  tk("See stock"),
  tk("Orders"),
  tk("Create, confirm, amend and cancel orders"),
  tk("Plan dependencies and batch priority"),
  tk("Outsourcing"),
  tk("Create, send, close and cancel batches"),
  tk("Record supplier updates"),
  tk("Stores and quality"),
  tk("Record receipts from suppliers"),
  tk("Inspect and release quality holds"),
  tk("Record stock entries"),
  tk("Approvals"),
  tk("Approve opening balances and stock adjustments"),
  tk("Actions"),
  tk("Raise, assign and close recovery actions"),
  tk("Approve consequential recovery actions"),
  tk("Dispatch"),
  tk("Record and cancel dispatches"),
  tk("Approve shipping beyond accepted material"),
  tk("Master data"),
  tk("Manage items"),
  tk("Manage units"),
  tk("Manage customers"),
  tk("Manage suppliers"),
  tk("Manage warehouses"),
  tk("Company"),
  tk("Manage sites and calendars"),
  tk("Change company settings"),
  tk("Manage members and their site access"),
  tk("Change roles and permissions"),
  tk("Owner"),
  tk("Administrator"),
  tk("Production manager"),
  tk("Production coordinator"),
  tk("Procurement"),
  tk("Stores"),
  tk("Quality"),
  tk("Finance"),
  tk("Approver"),
  tk("Read only"),
];
