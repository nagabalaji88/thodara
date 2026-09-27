import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  ArrowRight,
  Bell,
  Boxes,
  Building2,
  CalendarClock,
  Check,
  ChevronDown,
  CircleHelp,
  ClipboardCheck,
  Database,
  Factory,
  Gauge,
  LayoutDashboard,
  LoaderCircle,
  LockKeyhole,
  LogOut,
  Menu,
  PackageCheck,
  Search,
  Settings2,
  ShieldCheck,
  Truck,
  Users,
  Workflow,
} from "lucide-react";
import { api, type ApiError } from "./api";
import { MasterDataPage } from "./masterdata";
import { SettingsPage } from "./settings";
import type { SessionState, WorkspaceSummary } from "./types";

type AuthStatus = "checking" | "anonymous" | "ready";

function App() {
  const [authStatus, setAuthStatus] = useState<AuthStatus>("checking");
  const [session, setSession] = useState<SessionState | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  useEffect(() => {
    let live = true;
    api<SessionState>("/api/v1/auth/session")
      .then((value) => {
        if (!live) return;
        setSession(value);
        setAuthStatus("ready");
      })
      .catch((error: ApiError) => {
        if (!live) return;
        if (error.status !== 401) setAuthError(error.message);
        setAuthStatus("anonymous");
      });
    return () => { live = false; };
  }, []);

  const login = useMutation({
    mutationFn: (input: { email: string; password: string }) =>
      api<SessionState>("/api/v1/auth/login", { method: "POST", body: JSON.stringify(input) }),
    onSuccess: (value) => {
      setSession(value);
      setAuthStatus("ready");
      setAuthError(null);
      queryClient.clear();
    },
  });

  const logout = useMutation({
    mutationFn: () => api<void>("/api/v1/auth/logout", { method: "POST" }),
    onSettled: () => {
      setSession(null);
      setAuthStatus("anonymous");
      queryClient.clear();
    },
  });

  const selectTenant = useMutation({
    mutationFn: (tenantId: string) => api<SessionState>("/api/v1/auth/select-tenant", {
      method: "POST", body: JSON.stringify({ tenant_id: tenantId }),
    }),
    onSuccess: setSession,
  });

  if (authStatus === "checking") return <FullScreenState label="Checking your secure session" />;
  if (authStatus === "anonymous") {
    return <SignInPage onSubmit={(values) => login.mutate(values)} loading={login.isPending} error={login.error?.message ?? authError} />;
  }
  if (!session) return <FullScreenState label="Preparing your workspace" />;
  if (!session.memberships.length) {
    return <NoWorkspacePage user={session.user.display_name} onSignOut={() => logout.mutate()} />;
  }
  if (!session.active_tenant) {
    return <TenantPicker session={session} loading={selectTenant.isPending} error={selectTenant.error?.message} onChoose={(id) => selectTenant.mutate(id)} onSignOut={() => logout.mutate()} />;
  }
  return <WorkspaceApp session={session} onSignOut={() => logout.mutate()} />;
}

function FullScreenState({ label }: { label: string }) {
  return <main className="full-state"><LoaderCircle className="spin" size={22} /><span>{label}</span></main>;
}

function Brand({ inverse = false }: { inverse?: boolean }) {
  return <div className={`brand ${inverse ? "brand-inverse" : ""}`} aria-label="Thodara">
    <span className="brand-mark"><Workflow size={18} strokeWidth={2.2} /></span>
    <span>thodara<span className="brand-period">.</span></span>
  </div>;
}

function SignInPage({ onSubmit, loading, error }: {
  onSubmit: (values: { email: string; password: string }) => void;
  loading: boolean;
  error?: string | null;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [visible, setVisible] = useState(false);
  return <main className="auth-page">
    <section className="auth-story">
      <Brand inverse />
      <div className="auth-story-copy">
        <span className="eyebrow"><span className="eyebrow-dot" /> MANUFACTURING OPERATIONS</span>
        <h1>Keep every<br /><em>order moving.</em></h1>
        <p>Connect customer commitments to what is happening across your factory and supplier network.</p>
        <div className="story-points">
          <div><span><PackageCheck size={17} /></span><p><b>See the order path</b><small>From material to dispatch</small></p></div>
          <div><span><ShieldCheck size={17} /></span><p><b>Act on verified updates</b><small>Know what was confirmed and when</small></p></div>
        </div>
      </div>
      <div className="auth-story-foot"><span>Built for real factory workflows</span><span>India-first · Configurable · Connected</span></div>
      <div className="story-orbit orbit-one" /><div className="story-orbit orbit-two" />
    </section>
    <section className="auth-form-side">
      <div className="auth-mobile-brand"><Brand /></div>
      <form className="auth-card" onSubmit={(event) => { event.preventDefault(); onSubmit({ email, password }); }}>
        <div className="auth-card-icon"><LockKeyhole size={20} /></div>
        <span className="eyebrow">SECURE WORKSPACE ACCESS</span>
        <h2>Sign in to Thodara</h2>
        <p className="auth-subtitle">Use the account invited by your workspace administrator.</p>
        <label htmlFor="email">Work email</label>
        <div className="input-wrap"><Users size={16} /><input id="email" type="email" autoComplete="username" inputMode="email" value={email} onChange={(event) => setEmail(event.target.value)} required maxLength={254} placeholder="you@company.com" /></div>
        <div className="password-label"><label htmlFor="password">Password</label><span>Forgot password? Contact your administrator.</span></div>
        <div className="input-wrap"><LockKeyhole size={16} /><input id="password" type={visible ? "text" : "password"} autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required maxLength={128} placeholder="Enter your password" /><button className="text-button" type="button" onClick={() => setVisible((value) => !value)} aria-label={visible ? "Hide password" : "Show password"}>{visible ? "Hide" : "Show"}</button></div>
        {error && <div className="form-error" role="alert"><AlertCircle size={15} />{error}</div>}
        <button className="primary-button auth-submit" disabled={loading} type="submit">{loading ? <><LoaderCircle className="spin" size={16} /> Signing in…</> : <>Continue securely <ArrowRight size={16} /></>}</button>
        <div className="secure-note"><ShieldCheck size={14} /> Your session is encrypted and access is workspace-scoped.</div>
      </form>
      <footer className="auth-footer">© {new Date().getFullYear()} Thodara · <button type="button">Privacy</button> · <button type="button">Support</button></footer>
    </section>
  </main>;
}

function TenantPicker({ session, onChoose, onSignOut, loading, error }: {
  session: SessionState; onChoose: (tenantId: string) => void; onSignOut: () => void; loading: boolean; error?: string;
}) {
  return <main className="choice-page"><div className="choice-head"><Brand /><button className="quiet-button" onClick={onSignOut}><LogOut size={16} /> Sign out</button></div>
    <section className="choice-card"><div className="auth-card-icon"><Building2 size={20} /></div><span className="eyebrow">WORKSPACE ACCESS</span><h1>Choose a workspace</h1><p>You have access to more than one company. Select where you want to work.</p>
      <div className="tenant-list">{session.memberships.map((tenant) => <button key={tenant.tenant_id} disabled={loading} className="tenant-option" onClick={() => onChoose(tenant.tenant_id)}><span className="tenant-avatar"><Factory size={18} /></span><span><b>{tenant.tenant_name}</b><small>{tenant.role.replaceAll("_", " ")}</small></span><ArrowRight size={17} /></button>)}</div>
      {error && <div className="form-error" role="alert"><AlertCircle size={15} />{error}</div>}
    </section>
  </main>;
}

function NoWorkspacePage({ user, onSignOut }: { user: string; onSignOut: () => void }) {
  return <main className="choice-page"><div className="choice-head"><Brand /><button className="quiet-button" onClick={onSignOut}><LogOut size={16} /> Sign out</button></div><section className="choice-card"><div className="auth-card-icon"><Building2 size={20} /></div><span className="eyebrow">NO WORKSPACE YET</span><h1>Hello, {user.split(" ")[0]}</h1><p>Your account does not have a company workspace assigned. Ask your Thodara administrator to send you an invitation.</p><div className="notice-box"><CircleHelp size={17} /><span>Workspace creation is managed through the onboarding process. Public self-service signup has not been enabled.</span></div></section></main>;
}

const navItems = [
  { key: "my-work", label: "My work", icon: LayoutDashboard, href: "#my-work" },
  { key: "master-data", label: "Master data", icon: Database, href: "#master-data/items" },
  { key: "settings", label: "Company & sites", icon: Building2, href: "#settings" },
  { key: "orders", label: "Sales orders", icon: PackageCheck },
  { key: "production", label: "Production", icon: Workflow },
  { key: "suppliers", label: "Supplier updates", icon: Users },
  { key: "inventory", label: "Inventory", icon: Boxes },
  { key: "quality", label: "Quality", icon: ClipboardCheck },
  { key: "dispatch", label: "Dispatch", icon: Truck },
];
const pageTitles: Record<string, string> = { "my-work": "My work", "master-data": "Master data", settings: "Company & sites" };

function useHashRoute() {
  const [hash, setHash] = useState(() => window.location.hash.slice(1));
  useEffect(() => {
    const onChange = () => setHash(window.location.hash.slice(1));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  const [section = "my-work", sub = ""] = hash.split("/");
  return { section: section in pageTitles ? section : "my-work", sub };
}

function WorkspaceApp({ session, onSignOut }: { session: SessionState; onSignOut: () => void }) {
  const workspace = useQuery({
    queryKey: ["workspace", session.active_tenant?.tenant_id],
    queryFn: () => api<WorkspaceSummary>("/api/v1/workspace/dashboard"),
  });
  const setup = useMutation({
    mutationFn: (payload: { company_name: string; country_code: string; base_currency: string; site_name: string; city: string; time_zone: string }) =>
      api<WorkspaceSummary>("/api/v1/onboarding/workspace", { method: "PUT", body: JSON.stringify(payload) }),
    onSuccess: (value) => queryClientCacheSet(value),
  });
  const queryClient = useQueryClient();
  function queryClientCacheSet(value: WorkspaceSummary) {
    queryClient.setQueryData(["workspace", session.active_tenant?.tenant_id], value);
  }

  if (workspace.isPending) return <FullScreenState label="Loading your workspace" />;
  if (workspace.isError) return <main className="full-state error-state"><AlertCircle size={20} /><p>{workspace.error.message}</p><button className="primary-button" onClick={() => void workspace.refetch()}>Try again</button><button className="quiet-button" onClick={onSignOut}>Sign out</button></main>;
  if (!workspace.data.setup_complete) return <WorkspaceSetup companyName={workspace.data.company_name} site={workspace.data.sites[0]} loading={setup.isPending} error={setup.error?.message} onSubmit={(data) => setup.mutate(data)} onSignOut={onSignOut} />;
  return <Dashboard session={session} workspace={workspace.data} onSignOut={onSignOut} />;
}

function WorkspaceSetup({ companyName, site, loading, error, onSubmit, onSignOut }: {
  companyName: string; site?: WorkspaceSummary["sites"][number]; loading: boolean; error?: string;
  onSubmit: (value: { company_name: string; country_code: string; base_currency: string; site_name: string; city: string; time_zone: string }) => void;
  onSignOut: () => void;
}) {
  const [company, setCompany] = useState(companyName);
  const [siteName, setSiteName] = useState(site?.name ?? "Main plant");
  const [city, setCity] = useState(site?.city ?? "");
  const [country, setCountry] = useState("IN");
  const [currency, setCurrency] = useState("INR");
  const [timeZone, setTimeZone] = useState(site?.time_zone ?? "Asia/Kolkata");
  return <main className="setup-page"><header className="setup-header"><Brand /><button className="quiet-button" onClick={onSignOut}><LogOut size={16} /> Sign out</button></header>
    <div className="setup-progress"><span>WORKSPACE SETUP</span><div><i /></div><small>Step 1 of 1 · Essentials</small></div>
    <form className="setup-card" onSubmit={(event) => { event.preventDefault(); onSubmit({ company_name: company, country_code: country.toUpperCase(), base_currency: currency.toUpperCase(), site_name: siteName, city, time_zone: timeZone }); }}>
      <div className="setup-icon"><Building2 size={21} /></div><span className="eyebrow">YOUR FACTORY WORKSPACE</span><h1>Let’s set up your company</h1><p className="setup-intro">These settings keep dates, currency, and plant activity clear for your team. You can update them later.</p>
      <div className="setup-grid"><label>Company display name<input value={company} onChange={(e) => setCompany(e.target.value)} required minLength={2} maxLength={160} /></label><label>Plant / site name<input value={siteName} onChange={(e) => setSiteName(e.target.value)} required minLength={2} maxLength={120} /></label><label>Country code<input value={country} onChange={(e) => setCountry(e.target.value)} required maxLength={2} /></label><label>Base currency<input value={currency} onChange={(e) => setCurrency(e.target.value)} required maxLength={3} /></label><label>City <span className="optional">OPTIONAL</span><input value={city} onChange={(e) => setCity(e.target.value)} maxLength={120} /></label><label>Time zone<input value={timeZone} onChange={(e) => setTimeZone(e.target.value)} required /></label></div>
      <div className="setup-note"><ShieldCheck size={16} /><span>We won’t infer tax registrations or enable finance settings here. Those need your company’s confirmed requirements.</span></div>
      {error && <div className="form-error" role="alert"><AlertCircle size={15} />{error}</div>}
      <button className="primary-button setup-submit" disabled={loading} type="submit">{loading ? <><LoaderCircle className="spin" size={16} /> Saving…</> : <>Save and open workspace <ArrowRight size={16} /></>}</button>
    </form>
  </main>;
}

function Dashboard({ session, workspace, onSignOut }: { session: SessionState; workspace: WorkspaceSummary; onSignOut: () => void }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const route = useHashRoute();
  const firstName = session.user.display_name.split(" ")[0] ?? "";
  const dateLabel = new Intl.DateTimeFormat("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: workspace.sites[0]?.time_zone ?? "UTC" }).format(new Date());
  return <div className="app-shell">
    <aside className="sidebar">
      <div className="sidebar-brand"><Brand inverse /></div>
      <div className="site-switch"><span className="site-switch-icon"><Factory size={17} /></span><span className="site-switch-copy"><b>{workspace.company_name}</b><small>{workspace.sites[0]?.name ?? "Workspace"}{workspace.sites[0]?.city ? ` · ${workspace.sites[0].city}` : ""}</small></span><ChevronDown size={15} /></div>
      <span className="nav-caption">WORKSPACE</span>
      <nav className="primary-nav" aria-label="Main navigation">{navItems.map((item) => { const active = item.key === route.section; return <a key={item.key} className={`nav-item ${active ? "active" : item.href ? "" : "disabled"}`} href={item.href} aria-current={active ? "page" : undefined} aria-disabled={!item.href} title={!item.href ? "This module will be enabled as it is implemented" : undefined}><item.icon size={17} strokeWidth={1.8} /><span>{item.label}</span>{active && <span className="nav-active-dot" />}</a>; })}</nav>
      <div className="sidebar-bottom"><div className="environment-label"><span /> SECURE WORKSPACE</div><div className="sidebar-user"><span className="user-initials">{initials(session.user.display_name)}</span><span className="sidebar-user-copy"><b>{session.user.display_name}</b><small>{session.active_tenant?.role.replaceAll("_", " ")}</small></span><button className="icon-button sidebar-menu-button" onClick={() => setMenuOpen((value) => !value)} aria-label="Open account menu"><Menu size={17} /></button>{menuOpen && <div className="account-menu"><button onClick={onSignOut}><LogOut size={15} /> Sign out</button></div>}</div></div>
    </aside>
    <div className="workspace-main">
      <header className="topbar"><div className="breadcrumbs"><span>{workspace.company_name}</span><b>/</b><strong>{pageTitles[route.section] ?? "My work"}</strong></div><div className="topbar-spacer" /><label className="global-search"><Search size={15} /><input aria-label="Search workspace" placeholder="Search orders, items…" disabled /></label><button className="icon-button notification-button" aria-label="Notifications"><Bell size={17} /><i /></button><button className="icon-button help-button" aria-label="Help"><CircleHelp size={17} /></button><div className="profile-control"><span className="user-initials">{initials(session.user.display_name)}</span><span className="profile-copy"><b>{session.user.display_name}</b><small>{workspace.sites[0]?.name ?? "Workspace"}</small></span><button className="icon-button profile-menu" onClick={() => setMenuOpen((value) => !value)} aria-label="Account options"><ChevronDown size={15} /></button>{menuOpen && <div className="account-menu top-account-menu"><button onClick={onSignOut}><LogOut size={15} /> Sign out</button></div>}</div></header>
      <main className="dashboard-content" id="main">
        {route.section === "master-data" ? <MasterDataPage tab={route.sub} permissions={workspace.permissions} />
          : route.section === "settings" ? <SettingsPage permissions={workspace.permissions} />
            : <MyWork firstName={firstName} dateLabel={dateLabel} />}
        <footer className="dashboard-footer"><span>Thodara ERP · {workspace.company_name}</span><span>Workspace data is private to your organization.</span></footer>
      </main>
    </div>
    <nav className="mobile-nav" aria-label="Mobile navigation">{[["my-work", "Work", LayoutDashboard, "#my-work"], ["master-data", "Data", Database, "#master-data/items"], ["settings", "Sites", Building2, "#settings"]].map(([key, text, Icon, href]) => { const C = Icon as typeof LayoutDashboard; return <a key={key as string} className={route.section === key ? "mobile-nav-active" : undefined} href={href as string}><C size={18} /><span>{text as string}</span></a>; })}<button disabled aria-label="More"><Settings2 size={18} /><span>More</span></button></nav>
  </div>;
}

function MyWork({ firstName, dateLabel }: { firstName: string; dateLabel: string }) {
  return <>
        <section className="welcome-row"><div><span className="eyebrow">MY WORK</span><h1>Good morning, {firstName}</h1><p>Here’s your factory’s order and delivery picture.</p></div><div className="welcome-actions"><div className="date-chip"><CalendarClock size={15} />{dateLabel}</div><button className="primary-button request-button" disabled title="Supplier update requests will be enabled with the supplier workflow"><ArrowRight size={15} /> Request update</button></div></section>
        <section className="metric-grid" aria-label="Operations overview">
          <MetricCard label="Open customer orders" value="—" note="Sales order workflow not set up" icon={<PackageCheck size={17} />} tone="amber" />
          <MetricCard label="Production in progress" value="—" note="Work orders not set up" icon={<Workflow size={17} />} />
          <MetricCard label="Supplier updates due" value="—" note="Supplier workflow not set up" icon={<Users size={17} />} tone="slate" />
          <MetricCard label="Quality holds" value="—" note="Inspection workflow not set up" icon={<ShieldCheck size={17} />} tone="muted" />
        </section>
        <section className="dashboard-grid">
          <div className="panel action-panel"><div className="panel-header"><div><span className="eyebrow">DAILY CONTROL</span><h2>Today’s action list</h2><p>Prioritize what could affect a customer commitment.</p></div><span className="panel-icon"><Gauge size={18} /></span></div><div className="empty-work"><div className="empty-illustration"><ClipboardCheck size={24} /></div><h3>Your workspace is ready</h3><p>No orders or production activity have been recorded yet. Start by setting up items, customers and suppliers; order workflows come next.</p><a className="quiet-action" href="#master-data/items">Open master data <ArrowRight size={15} /></a></div><div className="panel-foot"><span><span className="status-pip" />No operational data loaded</span><span>Updates will show their source and time</span></div></div>
          <aside className="side-panels"><div className="panel commitment-panel"><div className="panel-header"><div><span className="eyebrow">ORDER TO DISPATCH</span><h2>Fulfillment path</h2><p>Track each dependency and handoff.</p></div><span className="panel-icon amber-icon"><Workflow size={18} /></span></div><div className="path-placeholder"><div className="path-row"><PathStep icon={<Factory size={14} />} label="In-house" /><span className="path-line" /><PathStep icon={<Boxes size={14} />} label="Materials" /><span className="path-line" /><PathStep icon={<Truck size={14} />} label="Dispatch" /></div><div className="path-empty"><span>—</span><p>Operation routing appears with your first work order.</p></div></div></div>
            <div className="panel freshness-panel"><div className="panel-header"><div><span className="eyebrow">STATUS QUALITY</span><h2>Update freshness</h2></div><span className="panel-icon green-icon"><Check size={18} /></span></div><div className="freshness-empty"><span className="freshness-symbol">—</span><span>No supplier updates yet</span></div><div className="freshness-rule"><span>Reported</span><span>Received</span><span>Accepted</span></div></div>
          </aside>
        </section>
  </>;
}

function PathStep({ icon, label }: { icon: React.ReactNode; label: string }) {
  return <div className="path-step"><span>{icon}</span><small>{label}</small></div>;
}

function MetricCard({ label, value, note, icon, tone = "slate" }: { label: string; value: string; note: string; icon: React.ReactNode; tone?: string }) {
  return <article className={`metric-card metric-${tone}`}><div className="metric-head"><span className="metric-icon">{icon}</span><span className="metric-label">{label}</span></div><strong>{value}</strong><small>{note}</small></article>;
}

function initials(name: string) {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]?.toUpperCase() ?? "").join("");
}

export default App;
