import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  ArrowRight,
  Check,
  CircleHelp,
  LoaderCircle,
  LockKeyhole,
  LogOut,
  Menu,
  ShieldCheck,
  Users,
  Workflow,
  X,
} from "lucide-react";
import { api, type ApiError } from "./api";
import { MasterDataPage } from "./masterdata";
import { SettingsPage } from "./settings";
import type { Page, SessionState, Site, UnitConversion, WorkspaceSummary } from "./types";

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

function Brand() {
  return <span className="brand" aria-label="Thodara">
    <span className="brand-mark"><Workflow size={18} strokeWidth={2.2} /></span>
    <span>thodara<span className="brand-period">.</span></span>
  </span>;
}

function PlainHeader({ onSignOut }: { onSignOut?: () => void }) {
  return <header className="wrap topnav"><Brand />{onSignOut && <button className="quiet-button push-right" onClick={onSignOut}><LogOut size={15} /> Sign out</button>}</header>;
}

function SignInPage({ onSubmit, loading, error }: {
  onSubmit: (values: { email: string; password: string }) => void;
  loading: boolean;
  error?: string | null;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [visible, setVisible] = useState(false);
  return <div className="page-frame">
    <PlainHeader />
    <main className="wrap hero hero-auth">
      <div className="hero-copy">
        <span className="eyebrow">MANUFACTURING OPERATIONS</span>
        <h1 className="display">Keep every <em>order moving.</em></h1>
        <p className="lede">Connect customer commitments to what is happening across your factory and supplier network.</p>
        <ul className="ticks">
          <li>See the order path, from material to dispatch</li>
          <li>Act on verified updates: know what was confirmed and when</li>
        </ul>
      </div>
      <form className="card form-card" onSubmit={(event) => { event.preventDefault(); onSubmit({ email, password }); }}>
        <span className="eyebrow">SECURE WORKSPACE ACCESS</span>
        <h2 className="heading">Sign in to Thodara</h2>
        <p className="muted">Use the account invited by your workspace administrator.</p>
        <label htmlFor="email">Work email</label>
        <div className="input-wrap"><Users size={16} /><input id="email" type="email" autoComplete="username" inputMode="email" value={email} onChange={(event) => setEmail(event.target.value)} required maxLength={254} placeholder="you@company.com" /></div>
        <div className="password-label"><label htmlFor="password">Password</label><span>Forgot password? Contact your administrator.</span></div>
        <div className="input-wrap"><LockKeyhole size={16} /><input id="password" type={visible ? "text" : "password"} autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required maxLength={128} placeholder="Enter your password" /><button className="text-button" type="button" onClick={() => setVisible((value) => !value)} aria-label={visible ? "Hide password" : "Show password"}>{visible ? "Hide" : "Show"}</button></div>
        {error && <div className="form-error" role="alert"><AlertCircle size={15} />{error}</div>}
        <button className="primary-button wide-button" disabled={loading} type="submit">{loading ? <><LoaderCircle className="spin" size={16} /> Signing in…</> : <>Continue securely <ArrowRight size={16} /></>}</button>
        <div className="secure-note"><ShieldCheck size={14} /> Your session is encrypted and access is workspace-scoped.</div>
      </form>
    </main>
    <SiteFooter title="Thodara" note="India-first · Configurable · Connected" />
  </div>;
}

function TenantPicker({ session, onChoose, onSignOut, loading, error }: {
  session: SessionState; onChoose: (tenantId: string) => void; onSignOut: () => void; loading: boolean; error?: string;
}) {
  return <div className="page-frame">
    <PlainHeader onSignOut={onSignOut} />
    <main className="wrap hero">
      <div className="hero-copy"><span className="eyebrow">WORKSPACE ACCESS</span><h1 className="display">Choose a <em>workspace.</em></h1><p className="lede">You have access to more than one company. Select where you want to work; you can switch later by signing in again.</p></div>
      <div className="card">
        <div className="tenant-list">{session.memberships.map((tenant) => <button key={tenant.tenant_id} disabled={loading} className="tenant-option" onClick={() => onChoose(tenant.tenant_id)}><span><b>{tenant.tenant_name}</b><small>{tenant.role.replaceAll("_", " ")}</small></span><ArrowRight size={18} /></button>)}</div>
        {error && <div className="form-error" role="alert"><AlertCircle size={15} />{error}</div>}
      </div>
    </main>
  </div>;
}

function NoWorkspacePage({ user, onSignOut }: { user: string; onSignOut: () => void }) {
  return <div className="page-frame">
    <PlainHeader onSignOut={onSignOut} />
    <main className="wrap hero">
      <div className="hero-copy"><span className="eyebrow">NO WORKSPACE YET</span><h1 className="display">Hello, <em>{user.split(" ")[0]}.</em></h1><p className="lede">Your account does not have a company workspace assigned. Ask your Thodara administrator to send you an invitation.</p></div>
      <div className="card notice-card"><CircleHelp size={22} /><p>Workspace creation is managed through the onboarding process. Public self-service signup has not been enabled.</p></div>
    </main>
  </div>;
}

type SetupPayload = { company_name: string; country_code: string; base_currency: string; site_name: string; city: string; time_zone: string };

function WorkspaceApp({ session, onSignOut }: { session: SessionState; onSignOut: () => void }) {
  const queryClient = useQueryClient();
  const workspace = useQuery({
    queryKey: ["workspace", session.active_tenant?.tenant_id],
    queryFn: () => api<WorkspaceSummary>("/api/v1/workspace/dashboard"),
  });
  const setup = useMutation({
    mutationFn: (payload: SetupPayload) => api<WorkspaceSummary>("/api/v1/onboarding/workspace", { method: "PUT", body: JSON.stringify(payload) }),
    onSuccess: (value) => queryClient.setQueryData(["workspace", session.active_tenant?.tenant_id], value),
  });

  if (workspace.isPending) return <FullScreenState label="Loading your workspace" />;
  if (workspace.isError) return <main className="full-state error-state"><AlertCircle size={20} /><p>{workspace.error.message}</p><button className="primary-button" onClick={() => void workspace.refetch()}>Try again</button><button className="quiet-button" onClick={onSignOut}>Sign out</button></main>;
  if (!workspace.data.setup_complete) return <WorkspaceSetup companyName={workspace.data.company_name} site={workspace.data.sites[0]} loading={setup.isPending} error={setup.error?.message} onSubmit={(data) => setup.mutate(data)} onSignOut={onSignOut} />;
  return <Shell session={session} workspace={workspace.data} onSignOut={onSignOut} />;
}

function WorkspaceSetup({ companyName, site, loading, error, onSubmit, onSignOut }: {
  companyName: string; site?: WorkspaceSummary["sites"][number]; loading: boolean; error?: string;
  onSubmit: (value: SetupPayload) => void; onSignOut: () => void;
}) {
  const [company, setCompany] = useState(companyName);
  const [siteName, setSiteName] = useState(site?.name ?? "Main plant");
  const [city, setCity] = useState(site?.city ?? "");
  const [country, setCountry] = useState("IN");
  const [currency, setCurrency] = useState("INR");
  const [timeZone, setTimeZone] = useState(site?.time_zone ?? "Asia/Kolkata");
  return <div className="page-frame">
    <PlainHeader onSignOut={onSignOut} />
    <main className="wrap hero hero-top">
      <div className="hero-copy"><span className="eyebrow">WORKSPACE SETUP · STEP 1 OF 1</span><h1 className="display">Let’s set up <em>your company.</em></h1><p className="lede">These settings keep dates, currency and plant activity clear for your team. You can update them later.</p>
        <div className="note-line"><ShieldCheck size={16} /><span>We won’t infer tax registrations or enable finance settings here. Those need your company’s confirmed requirements.</span></div></div>
      <form className="card form-card" onSubmit={(event) => { event.preventDefault(); onSubmit({ company_name: company, country_code: country.toUpperCase(), base_currency: currency.toUpperCase(), site_name: siteName, city, time_zone: timeZone }); }}>
        <div className="form-grid">
          <label className="span-2">Company display name<input value={company} onChange={(e) => setCompany(e.target.value)} required minLength={2} maxLength={160} /></label>
          <label className="span-2">Plant / site name<input value={siteName} onChange={(e) => setSiteName(e.target.value)} required minLength={2} maxLength={120} /></label>
          <label>Country code<input value={country} onChange={(e) => setCountry(e.target.value)} required maxLength={2} /></label>
          <label>Base currency<input value={currency} onChange={(e) => setCurrency(e.target.value)} required maxLength={3} /></label>
          <label>City <span className="optional">OPTIONAL</span><input value={city} onChange={(e) => setCity(e.target.value)} maxLength={120} /></label>
          <label>Time zone<input value={timeZone} onChange={(e) => setTimeZone(e.target.value)} required /></label>
        </div>
        {error && <div className="form-error" role="alert"><AlertCircle size={15} />{error}</div>}
        <button className="primary-button wide-button" disabled={loading} type="submit">{loading ? <><LoaderCircle className="spin" size={16} /> Saving…</> : <>Save and open workspace <ArrowRight size={16} /></>}</button>
      </form>
    </main>
  </div>;
}

const navItems: { key: string; label: string; href?: string }[] = [
  { key: "my-work", label: "My work", href: "#my-work" },
  { key: "master-data", label: "Master data", href: "#master-data/items" },
  { key: "settings", label: "Company & sites", href: "#settings" },
  { key: "orders", label: "Orders" },
  { key: "production", label: "Production" },
];
const sections = new Set(["my-work", "master-data", "settings"]);

function useHashRoute() {
  const [hash, setHash] = useState(() => window.location.hash.slice(1));
  useEffect(() => {
    const onChange = () => { setHash(window.location.hash.slice(1)); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  const [section = "my-work", sub = ""] = hash.split("/");
  return { section: sections.has(section) ? section : "my-work", sub };
}

const IMPORT_PERMISSIONS = ["customers:manage", "suppliers:manage", "items:manage"];

function Shell({ session, workspace, onSignOut }: { session: SessionState; workspace: WorkspaceSummary; onSignOut: () => void }) {
  const route = useHashRoute();
  const [menuOpen, setMenuOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  useEffect(() => { setMenuOpen(false); setAccountOpen(false); }, [route.section, route.sub]);
  const canImport = IMPORT_PERMISSIONS.some((p) => workspace.permissions.includes(p));
  const role = session.active_tenant?.role.replaceAll("_", " ") ?? "";
  return <div className="page-frame">
    <header className="topbar">
      <div className="wrap topnav">
        <a href="#my-work" className="brand-link"><Brand /></a>
        <nav className={`links ${menuOpen ? "open" : ""}`} aria-label="Main navigation">
          {navItems.map((item) => item.href
            ? <a key={item.key} href={item.href} className={route.section === item.key ? "current" : undefined} aria-current={route.section === item.key ? "page" : undefined}>{item.label}</a>
            : <span key={item.key} className="soon" title="This module will be enabled as it is implemented" aria-disabled="true">{item.label}</span>)}
          <button className="quiet-button menu-signout" onClick={onSignOut}><LogOut size={15} /> Sign out</button>
        </nav>
        <div className="who">
          {canImport && <a className="pill-dark" href="#master-data/import">Import data</a>}
          <div className="account">
            <button className="initials" onClick={() => setAccountOpen((v) => !v)} aria-label="Account menu" aria-expanded={accountOpen}>{initials(session.user.display_name)}</button>
            {accountOpen && <div className="account-menu"><b>{session.user.display_name}</b><small>{session.user.email}</small><small className="role-label">{role} · {workspace.company_name}</small><button onClick={onSignOut}><LogOut size={15} /> Sign out</button></div>}
          </div>
          <button className="icon-button menu-button" onClick={() => setMenuOpen((v) => !v)} aria-label={menuOpen ? "Close menu" : "Open menu"} aria-expanded={menuOpen}>{menuOpen ? <X size={18} /> : <Menu size={18} />}</button>
        </div>
      </div>
    </header>
    <main id="main">
      {route.section === "master-data" ? <MasterDataPage tab={route.sub} permissions={workspace.permissions} />
        : route.section === "settings" ? <SettingsPage permissions={workspace.permissions} />
          : <MyWork session={session} workspace={workspace} />}
    </main>
    <SiteFooter title={workspace.company_name} link={route.section === "settings" ? { href: "#my-work", label: "My work" } : { href: "#settings", label: "Company & sites" }} note={<>Signed in as {session.user.display_name} · <span className="role-label">{role}</span></>} />
  </div>;
}

function SiteFooter({ title, note, link }: { title: string; note: React.ReactNode; link?: { href: string; label: string } }) {
  return <footer className="wrap site-footer">
    <div className="foot-big"><span className="heading">{title}</span>{link && <a href={link.href}>{link.label} →</a>}</div>
    <div className="foot-small"><span>Thodara ERP · Workspace data is private to your organization.</span><span>{note}</span></div>
  </footer>;
}

function useTotal(path: string) {
  return useQuery({ queryKey: ["md", "total", path], queryFn: () => api<Page<unknown>>(`${path}${path.includes("?") ? "&" : "?"}limit=1`), select: (page) => page.total });
}

function MyWork({ session, workspace }: { session: SessionState; workspace: WorkspaceSummary }) {
  const items = useTotal("/api/v1/master-data/items?status=active");
  const customers = useTotal("/api/v1/master-data/customers?status=active");
  const suppliers = useTotal("/api/v1/master-data/suppliers?status=active");
  const warehouses = useTotal("/api/v1/master-data/warehouses?status=active");
  const units = useTotal("/api/v1/master-data/units?status=active");
  const conversions = useQuery({ queryKey: ["md", "conversions"], queryFn: () => api<UnitConversion[]>("/api/v1/master-data/unit-conversions") });
  const sites = useQuery({ queryKey: ["sites"], queryFn: () => api<Site[]>("/api/v1/organization/sites") });

  const counts = [items.data, customers.data, suppliers.data];
  const known = counts.every((value) => value !== undefined);
  const masterReady = known && counts.every((value) => (value ?? 0) > 0);
  const masterStarted = counts.some((value) => (value ?? 0) > 0);
  const masterTag = !known ? "Checking" : masterReady ? "Ready" : masterStarted ? "In progress" : "Not started";
  const firstName = session.user.display_name.split(" ")[0] ?? "";
  const hour = Number(new Intl.DateTimeFormat("en-IN", { hour: "numeric", hourCycle: "h23", timeZone: workspace.sites[0]?.time_zone ?? "UTC" }).format(new Date()));
  const greeting = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  const dateLabel = new Intl.DateTimeFormat("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: workspace.sites[0]?.time_zone ?? "UTC" }).format(new Date());
  const siteCount = sites.data?.length;
  const show = (value: number | undefined) => (value === undefined ? "…" : String(value));

  return <>
    <section className="wrap hero">
      <div className="hero-copy">
        <span className="eyebrow">MY WORK · {workspace.company_name.toUpperCase()}</span>
        <h1 className="display">{greeting},<br /><em>{firstName}.</em></h1>
        <p className="lede">Here’s your factory’s order and delivery picture. Nothing is waiting on you yet: customer orders arrive with the next module.</p>
        <a className="primary-button hero-button" href="#master-data/items">Open master data <ArrowRight size={16} /></a>
        <div className="meta-line"><span>{dateLabel}</span>{workspace.sites[0] && <span>{workspace.sites[0].name}</span>}{siteCount !== undefined && <span>{siteCount} {siteCount === 1 ? "site" : "sites"}</span>}</div>
      </div>
      <aside className="path-panel" aria-label="Order to dispatch">
        <div className="orbit" />
        <span className="eyebrow">ORDER TO DISPATCH</span>
        <h2 className="heading">Fulfillment path</h2>
        <ol className="path">
          <PathStep n={1} title="Master data" note="Items, customers, suppliers, warehouses" tag={masterTag} done={masterReady} />
          <PathStep n={2} title="Customer orders" note="Lines and promised dates" tag="Not set up" />
          <PathStep n={3} title="In-house & job work" note="Operations and outsourced batches" tag="Not set up" />
          <PathStep n={4} title="Dispatch" note="Inspection, packing, delivery" tag="Not set up" />
        </ol>
        <span className="panel-note">Each step shows its source and time once updates arrive.</span>
      </aside>
    </section>

    <section className="wrap figures" aria-label="Operations overview">
      <Figure label="Open customer orders" note="Sales order workflow not set up" />
      <Figure label="Production in progress" note="Work orders not set up" />
      <Figure label="Supplier updates due" note="Supplier workflow not set up" />
      <Figure label="Quality holds" note="Inspection workflow not set up" />
    </section>

    <section className="wrap split">
      <div className="card inbox">
        <span className="ring"><Check size={30} /></span>
        <h3 className="heading">Your action list is clear</h3>
        <p>When orders and supplier batches exist, the next action that could affect a customer commitment appears here, with its owner and due time.</p>
      </div>
      <div>
        <span className="eyebrow">DAILY CONTROL</span>
        <h2 className="section-title">Today’s action list</h2>
        <p className="lede small">Prioritise what could affect a customer commitment, not everything that moved.</p>
        <ul className="ticks ruled">
          <li>Company and first site set up</li>
          <li className={masterReady ? undefined : "todo"}>At least one item, customer and supplier</li>
          <li className="todo">First customer order</li>
          <li className="todo">First supplier update</li>
        </ul>
        <a className="quiet-button" href="#master-data/items">Open master data <ArrowRight size={15} /></a>
      </div>
    </section>

    <section className="wrap status">
      <div className="status-head">
        <div><span className="eyebrow">STATUS YOU CAN TRUST</span><h2 className="section-title">Reported is not received.</h2></div>
        <p className="lede small">Every quantity keeps where it came from. A supplier’s word, the stores count and the inspector’s decision are shown separately, and a missing update reads as “unknown”, never as “late”.</p>
      </div>
      <div className="states">
        <div className="state"><b>Reported</b><p>What the supplier or shop floor says is done. No supplier updates yet.</p></div>
        <div className="state"><b>Received</b><p>What stores physically counted in. Receipts arrive with the inventory module.</p></div>
        <div className="state"><b>Accepted</b><p>What quality passed. Inspections arrive with the quality module.</p></div>
      </div>
    </section>

    <section className="band">
      <div className="wrap">
        <h2 className="section-title centered">Your factory, set up</h2>
        <p className="lede small centered">The shared records every order, work order and dispatch will refer to.</p>
        <div className="tiles">
          <a className="tile" href="#master-data/items"><strong>{show(items.data)}</strong><span>Items</span><small>Active products and materials</small></a>
          <a className="tile" href="#master-data/customers"><strong>{show(customers.data)}</strong><span>Customers</span><small>Active accounts</small></a>
          <a className="tile" href="#master-data/suppliers"><strong>{show(suppliers.data)}</strong><span>Suppliers</span><small>Including job work</small></a>
          <a className="tile" href="#master-data/warehouses"><strong>{show(warehouses.data)}</strong><span>Warehouses</span><small>{siteCount === undefined ? "Across your sites" : `Across ${siteCount} ${siteCount === 1 ? "site" : "sites"}`}</small></a>
          <a className="tile" href="#master-data/units"><strong>{show(units.data)}</strong><span>Units</span><small>{conversions.data ? `${conversions.data.length} ${conversions.data.length === 1 ? "conversion" : "conversions"}` : "Of measure"}</small></a>
        </div>
      </div>
    </section>
  </>;
}

function PathStep({ n, title, note, tag, done = false }: { n: number; title: string; note: string; tag: string; done?: boolean }) {
  return <li className={`step ${done ? "done" : ""}`}><span className="dot">{done ? <Check size={16} /> : n}</span><span><b>{title}</b><small>{note}</small></span><span className="tag">{tag}</span></li>;
}

function Figure({ label, note }: { label: string; note: string }) {
  return <div className="figure"><strong aria-label="Not available yet">—</strong><span>{label}</span><small>{note}</small></div>;
}

function initials(name: string) {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]?.toUpperCase() ?? "").join("");
}

export default App;
