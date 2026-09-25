import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Building2, Check, LoaderCircle, Plus, Users } from "lucide-react";
import { api } from "./api";
import type { Member, Site } from "./types";

export function SettingsPage({ permissions }: { permissions: string[] }) {
  return <section className="page">
    <header className="page-head"><div><span className="eyebrow">ORGANIZATION</span><h1>Company &amp; sites</h1><p>Plants and who may work on each of them.</p></div></header>
    <SitesPanel canManage={permissions.includes("sites:manage")} />
    {permissions.includes("users:manage") && <MembersPanel />}
  </section>;
}

function SitesPanel({ canManage }: { canManage: boolean }) {
  const queryClient = useQueryClient();
  const sites = useQuery({ queryKey: ["sites"], queryFn: () => api<Site[]>("/api/v1/organization/sites") });
  const [name, setName] = useState("");
  const [city, setCity] = useState("");
  const [timeZone, setTimeZone] = useState("Asia/Kolkata");
  const create = useMutation({
    mutationFn: () => api<Site>("/api/v1/organization/sites", { method: "POST", body: JSON.stringify({ name, city, time_zone: timeZone }) }),
    onSuccess: () => { setName(""); setCity(""); void queryClient.invalidateQueries({ queryKey: ["sites"] }); void queryClient.invalidateQueries({ queryKey: ["workspace"] }); },
  });
  return <div className="panel data-panel">
    <div className="sub-head"><Building2 size={15} /><h3>Sites</h3><p>{canManage ? "Every plant or location your company operates." : "The sites you have access to."}</p></div>
    {sites.isPending ? <div className="table-state"><LoaderCircle className="spin" size={16} /> Loading…</div>
      : sites.isError ? <div className="form-error" role="alert"><AlertCircle size={15} />{sites.error.message}</div>
        : sites.data.length === 0 ? <div className="table-state">You have not been given access to any site yet. Ask your administrator.</div>
          : <div className="table-wrap"><table className="data-table"><thead><tr><th scope="col">Site</th><th scope="col">City</th><th scope="col">Time zone</th><th scope="col">Status</th></tr></thead><tbody>{sites.data.map((s) => <tr key={s.id} className="static-row"><td>{s.name}</td><td>{s.city ?? "—"}</td><td>{s.time_zone}</td><td><span className={`badge badge-${s.status === "active" ? "active" : "inactive"}`}>{s.status}</span></td></tr>)}</tbody></table></div>}
    {canManage && <form className="inline-form" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
      <label>New site name<input value={name} onChange={(e) => setName(e.target.value)} required minLength={2} maxLength={120} placeholder="e.g. Pune Plant" /></label>
      <label>City<input value={city} onChange={(e) => setCity(e.target.value)} maxLength={120} /></label>
      <label>Time zone<input value={timeZone} onChange={(e) => setTimeZone(e.target.value)} required maxLength={64} /></label>
      <button className="quiet-button" type="submit" disabled={create.isPending}><Plus size={14} /> Add site</button>
    </form>}
    {create.error && <div className="form-error" role="alert"><AlertCircle size={15} />{create.error.message}</div>}
  </div>;
}

function MembersPanel() {
  const members = useQuery({ queryKey: ["members"], queryFn: () => api<Member[]>("/api/v1/organization/members") });
  const sites = useQuery({ queryKey: ["sites"], queryFn: () => api<Site[]>("/api/v1/organization/sites") });
  return <div className="panel data-panel">
    <div className="sub-head"><Users size={15} /><h3>Site access</h3><p>Owners and administrators always see every site. Everyone else sees only the sites granted here; with none granted, they see no site data.</p></div>
    {members.isPending || sites.isPending ? <div className="table-state"><LoaderCircle className="spin" size={16} /> Loading…</div>
      : members.isError ? <div className="form-error" role="alert"><AlertCircle size={15} />{members.error.message}</div>
        : <div className="member-list">{members.data.map((m) => <MemberRow key={m.membership_id + m.site_scope + m.site_ids.join()} member={m} sites={sites.data ?? []} />)}</div>}
    <p className="hint">Inviting new people is not available yet; it waits on the identity-provider decision.</p>
  </div>;
}

function MemberRow({ member, sites }: { member: Member; sites: Site[] }) {
  const queryClient = useQueryClient();
  const fixed = member.role === "owner" || member.role === "administrator";
  const [scope, setScope] = useState(member.site_scope);
  const [chosen, setChosen] = useState<Set<string>>(new Set(member.site_ids));
  const save = useMutation({
    mutationFn: () => api<Member>(`/api/v1/organization/members/${member.membership_id}/site-access`, {
      method: "PUT", body: JSON.stringify({ site_scope: scope, site_ids: scope === "selected" ? [...chosen] : [] }),
    }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["members"] }),
  });
  const dirty = scope !== member.site_scope || (scope === "selected" && [...chosen].sort().join() !== [...member.site_ids].sort().join());
  return <div className="member-row">
    <div className="member-who"><span className="user-initials">{member.display_name.slice(0, 2).toUpperCase()}</span><span><b>{member.display_name}</b><small>{member.email} · <span className="role-label">{member.role.replaceAll("_", " ")}</span></small></span></div>
    {fixed ? <span className="badge badge-active">All sites</span> : <div className="member-access">
      <select aria-label={`Site access for ${member.display_name}`} value={scope} onChange={(e) => setScope(e.target.value as Member["site_scope"])}><option value="all">All sites</option><option value="selected">Selected sites</option></select>
      {scope === "selected" && <div className="site-checks">{sites.map((s) => <label key={s.id} className="check-field"><input type="checkbox" checked={chosen.has(s.id)} onChange={(e) => { const next = new Set(chosen); if (e.target.checked) next.add(s.id); else next.delete(s.id); setChosen(next); }} />{s.name}</label>)}</div>}
      <button className="quiet-button" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>{save.isPending ? <LoaderCircle className="spin" size={14} /> : <Check size={14} />} Save</button>
      {save.error && <span className="inline-error" role="alert">{save.error.message}</span>}
    </div>}
  </div>;
}
