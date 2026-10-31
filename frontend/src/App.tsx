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
import { AccountPage } from "./account";
import { api, type ApiError } from "./api";
import { MasterDataPage } from "./masterdata";
import { OrdersPage } from "./orders";
import { HEADLINES, RiskBoard, useRiskBoard } from "./risk";
import { ActionStatus, ActionsPage, type ActionPage } from "./actions";
import { ReportsPage } from "./reports";
import { OutsourcingPage } from "./outsourcing";
import { SettingsPage } from "./settings";
import { StockPage } from "./stock";
import type { Page, SessionState, Site, UnitConversion, WorkspaceSummary } from "./types";
import { LANGUAGES, locale, setLanguage, t, tk, type Lang } from "./i18n";

type AuthStatus = "checking" | "anonymous" | "ready";

function App() {
  const [authStatus, setAuthStatus] = useState<AuthStatus>("checking");
  const [session, setSession] = useState<SessionState | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  // Before sign-in the choice is kept on this device; after, the user's saved language wins.
  const [lang, setLang] = useState<Lang>(() => { try { return localStorage.getItem("thodara.lang") === "ta" ? "ta" : "en"; } catch { return "en"; } });
  const queryClient = useQueryClient();
  setLanguage(lang);
  const chooseLocal = (value: Lang) => {
    if (value !== lang) {
      setLanguage(value);
      // Data fetched in the other language (risk explanations, suggestions) is fetched again.
      void queryClient.invalidateQueries();
    }
    setLang(value);
    try { localStorage.setItem("thodara.lang", value); } catch { /* storage may be blocked */ }
  };
  const adopt = (value: SessionState) => { setSession(value); if (value.user.language) chooseLocal(value.user.language); };

  useEffect(() => {
    let live = true;
    api<SessionState>("/api/v1/auth/session")
      .then((value) => {
        if (!live) return;
        adopt(value);
        setAuthStatus("ready");
      })
      .catch((error: ApiError) => {
        if (!live) return;
        if (error.status !== 401) setAuthError(error.message);
        setAuthStatus("anonymous");
      });
    return () => { live = false; };
  }, []);

  const saveLanguage = useMutation({
    mutationFn: (value: Lang) => api<SessionState>("/api/v1/auth/language", { method: "PUT", body: JSON.stringify({ language: value }) }),
    onSuccess: adopt,
  });
  const login = useMutation({
    mutationFn: (input: { email: string; password: string }) =>
      api<SessionState>("/api/v1/auth/login", { method: "POST", body: JSON.stringify(input) }),
    onSuccess: (value) => {
      // A language picked on the sign-in page is an explicit choice: save it for this user.
      if (value.user.language !== lang) { setSession(value); saveLanguage.mutate(lang); } else adopt(value);
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
    onSuccess: adopt,
  });


  const languageSwitch = <LanguageSwitch value={lang} onChange={(value) => (session ? saveLanguage.mutate(value) : chooseLocal(value))} />;

  if (authStatus === "checking") return <FullScreenState label={t("Checking your secure session")} />;
  if (authStatus === "anonymous") {
    return <SignInPage onSubmit={(values) => login.mutate(values)} loading={login.isPending} error={login.error?.message ?? authError} languageSwitch={languageSwitch} />;
  }
  if (!session) return <FullScreenState label={t("Preparing your workspace")} />;
  if (!session.memberships.length) {
    return <NoWorkspacePage user={session.user.display_name} onSignOut={() => logout.mutate()} />;
  }
  if (!session.active_tenant) {
    return <TenantPicker session={session} loading={selectTenant.isPending} error={selectTenant.error?.message} onChoose={(id) => selectTenant.mutate(id)} onSignOut={() => logout.mutate()} />;
  }
  return <WorkspaceApp session={session} onSignOut={() => logout.mutate()} languageSwitch={languageSwitch} />;
}

/** English / தமிழ் toggle. Numbers stay in 0-9 digits in both (ADR-0012). */
function LanguageSwitch({ value, onChange }: { value: Lang; onChange: (value: Lang) => void }) {
  return <div className="segmented language-switch" role="radiogroup" aria-label={t("Language")}>
    {LANGUAGES.map(([code, label]) => <button key={code} type="button" role="radio" aria-checked={value === code} lang={code} className={value === code ? "on" : undefined} onClick={() => onChange(code)}>{label}</button>)}
  </div>;
}

function FullScreenState({ label }: { label: string }) {
  return <main className="full-state"><LoaderCircle className="spin" size={22} /><span>{label}</span></main>;
}

function Brand() {
  return <span className="brand" aria-label={t("Thodara")}>
    <span className="brand-mark"><Workflow size={18} strokeWidth={2.2} /></span>
    <span>thodara<span className="brand-period">.</span></span>
  </span>;
}

function PlainHeader({ onSignOut, languageSwitch }: { onSignOut?: () => void; languageSwitch?: React.ReactNode }) {
  return <header className="wrap topnav"><Brand />{languageSwitch && <span className="push-right">{languageSwitch}</span>}{onSignOut && <button className="quiet-button push-right" onClick={onSignOut}><LogOut size={15} /> {t("Sign out")}</button>}</header>;
}

function SignInPage({ onSubmit, loading, error, languageSwitch }: {
  onSubmit: (values: { email: string; password: string }) => void;
  loading: boolean;
  error?: string | null;
  languageSwitch: React.ReactNode;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [visible, setVisible] = useState(false);
  return <div className="page-frame">
    <PlainHeader languageSwitch={languageSwitch} />
    <main className="wrap hero hero-auth">
      <div className="hero-copy">
        <span className="eyebrow">{t("MANUFACTURING OPERATIONS")}</span>
        <h1 className="display">{t("Keep every")} <em>{t("order moving.")}</em></h1>
        <p className="lede">{t("Connect customer commitments to what is happening across your factory and supplier network.")}</p>
        <ul className="ticks">
          <li>{t("See the order path, from material to dispatch")}</li>
          <li>{t("Act on verified updates: know what was confirmed and when")}</li>
        </ul>
      </div>
      <form className="card form-card" onSubmit={(event) => { event.preventDefault(); onSubmit({ email, password }); }}>
        <span className="eyebrow">{t("SECURE WORKSPACE ACCESS")}</span>
        <h2 className="heading">{t("Sign in to Thodara")}</h2>
        <p className="muted">{t("Use the account invited by your workspace administrator.")}</p>
        <label htmlFor="email">{t("Work email")}</label>
        <div className="input-wrap"><Users size={16} /><input id="email" type="email" autoComplete="username" inputMode="email" value={email} onChange={(event) => setEmail(event.target.value)} required maxLength={254} placeholder={t("you@company.com")} /></div>
        <div className="password-label"><label htmlFor="password">{t("Password")}</label><span>{t("Forgot password? Contact your administrator.")}</span></div>
        <div className="input-wrap"><LockKeyhole size={16} /><input id="password" type={visible ? "text" : "password"} autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required maxLength={128} placeholder={t("Enter your password")} /><button className="text-button" type="button" onClick={() => setVisible((value) => !value)} aria-label={visible ? t("Hide password") : t("Show password")}>{visible ? t("Hide") : t("Show")}</button></div>
        {error && <div className="form-error" role="alert"><AlertCircle size={15} />{error}</div>}
        <button className="primary-button wide-button" disabled={loading} type="submit">{loading ? <><LoaderCircle className="spin" size={16} /> {t("Signing in…")}</> : <>{t("Continue securely")} <ArrowRight size={16} /></>}</button>
        <div className="secure-note"><ShieldCheck size={14} /> {t("Your session is encrypted and access is workspace-scoped.")}</div>
      </form>
    </main>
    <SiteFooter title={t("Thodara")} note={t("India-first · Configurable · Connected")} />
  </div>;
}

function TenantPicker({ session, onChoose, onSignOut, loading, error }: {
  session: SessionState; onChoose: (tenantId: string) => void; onSignOut: () => void; loading: boolean; error?: string;
}) {
  return <div className="page-frame">
    <PlainHeader onSignOut={onSignOut} />
    <main className="wrap hero">
      <div className="hero-copy"><span className="eyebrow">{t("WORKSPACE ACCESS")}</span><h1 className="display">{t("Choose a")} <em>{t("workspace.")}</em></h1><p className="lede">{t("You have access to more than one company. Select where you want to work; you can switch later by signing in again.")}</p></div>
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
      <div className="hero-copy"><span className="eyebrow">{t("NO WORKSPACE YET")}</span><h1 className="display">{t("Hello,")} <em>{user.split(" ")[0]}.</em></h1><p className="lede">{t("Your account does not have a company workspace assigned. Ask your Thodara administrator to send you an invitation.")}</p></div>
      <div className="card notice-card"><CircleHelp size={22} /><p>{t("Workspace creation is managed through the onboarding process. Public self-service signup has not been enabled.")}</p></div>
    </main>
  </div>;
}

type SetupPayload = { company_name: string; country_code: string; base_currency: string; site_name: string; city: string; time_zone: string };

function WorkspaceApp({ session, onSignOut, languageSwitch }: { session: SessionState; onSignOut: () => void; languageSwitch: React.ReactNode }) {
  const queryClient = useQueryClient();
  const workspace = useQuery({
    queryKey: ["workspace", session.active_tenant?.tenant_id],
    queryFn: () => api<WorkspaceSummary>("/api/v1/workspace/dashboard"),
  });
  const setup = useMutation({
    mutationFn: (payload: SetupPayload) => api<WorkspaceSummary>("/api/v1/onboarding/workspace", { method: "PUT", body: JSON.stringify(payload) }),
    onSuccess: (value) => queryClient.setQueryData(["workspace", session.active_tenant?.tenant_id], value),
  });

  if (workspace.isPending) return <FullScreenState label={t("Loading your workspace")} />;
  if (workspace.isError) return <main className="full-state error-state"><AlertCircle size={20} /><p>{workspace.error.message}</p><button className="primary-button" onClick={() => void workspace.refetch()}>{t("Try again")}</button><button className="quiet-button" onClick={onSignOut}>{t("Sign out")}</button></main>;
  if (!workspace.data.setup_complete) return <WorkspaceSetup companyName={workspace.data.company_name} site={workspace.data.sites[0]} loading={setup.isPending} error={setup.error?.message} onSubmit={(data) => setup.mutate(data)} onSignOut={onSignOut} />;
  return <Shell session={session} workspace={workspace.data} onSignOut={onSignOut} languageSwitch={languageSwitch} />;
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
      <div className="hero-copy"><span className="eyebrow">{t("WORKSPACE SETUP · STEP 1 OF 1")}</span><h1 className="display">{t("Let’s set up")} <em>{t("your company.")}</em></h1><p className="lede">{t("These settings keep dates, currency and plant activity clear for your team. You can update them later.")}</p>
        <div className="note-line"><ShieldCheck size={16} /><span>{t("We won’t infer tax registrations or enable finance settings here. Those need your company’s confirmed requirements.")}</span></div></div>
      <form className="card form-card" onSubmit={(event) => { event.preventDefault(); onSubmit({ company_name: company, country_code: country.toUpperCase(), base_currency: currency.toUpperCase(), site_name: siteName, city, time_zone: timeZone }); }}>
        <div className="form-grid">
          <label className="span-2">{t("Company display name")}<input value={company} onChange={(e) => setCompany(e.target.value)} required minLength={2} maxLength={160} /></label>
          <label className="span-2">{t("Plant / site name")}<input value={siteName} onChange={(e) => setSiteName(e.target.value)} required minLength={2} maxLength={120} /></label>
          <label>{t("Country code")}<input value={country} onChange={(e) => setCountry(e.target.value)} required maxLength={2} /></label>
          <label>{t("Base currency")}<input value={currency} onChange={(e) => setCurrency(e.target.value)} required maxLength={3} /></label>
          <label>{t("City")} <span className="optional">{t("OPTIONAL")}</span><input value={city} onChange={(e) => setCity(e.target.value)} maxLength={120} /></label>
          <label>{t("Time zone")}<input value={timeZone} onChange={(e) => setTimeZone(e.target.value)} required /></label>
        </div>
        {error && <div className="form-error" role="alert"><AlertCircle size={15} />{error}</div>}
        <button className="primary-button wide-button" disabled={loading} type="submit">{loading ? <><LoaderCircle className="spin" size={16} /> {t("Saving…")}</> : <>{t("Save and open workspace")} <ArrowRight size={16} /></>}</button>
      </form>
    </main>
  </div>;
}

const navItems: { key: string; label: string; href?: string }[] = [
  { key: "my-work", label: tk("My work"), href: "#my-work" },
  { key: "risk", label: tk("Delivery risk"), href: "#risk" },
  { key: "actions", label: tk("Actions"), href: "#actions" },
  { key: "orders", label: tk("Orders"), href: "#orders" },
  { key: "outsourcing", label: tk("Outsourcing"), href: "#outsourcing" },
  { key: "stock", label: tk("Stock"), href: "#stock" },
  { key: "reports", label: tk("Reports"), href: "#reports" },
  { key: "master-data", label: tk("Master data"), href: "#master-data/items" },
  { key: "settings", label: tk("Company & sites"), href: "#settings" },
];
const sections = new Set(["my-work", "risk", "actions", "reports", "orders", "outsourcing", "stock", "master-data", "settings", "account"]);

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

function Shell({ session, workspace, onSignOut, languageSwitch }: { session: SessionState; workspace: WorkspaceSummary; onSignOut: () => void; languageSwitch: React.ReactNode }) {
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
        <nav className={`links ${menuOpen ? "open" : ""}`} aria-label={t("Main navigation")}>
          {navItems.map((item) => item.href
            ? <a key={item.key} href={item.href} className={route.section === item.key ? "current" : undefined} aria-current={route.section === item.key ? "page" : undefined}>{t(item.label)}</a>
            : <span key={item.key} className="soon" title={t("This module will be enabled as it is implemented")} aria-disabled="true">{t(item.label)}</span>)}
          <button className="quiet-button menu-signout" onClick={onSignOut}><LogOut size={15} /> {t("Sign out")}</button>
        </nav>
        <div className="who">
          {canImport && <a className="pill-dark" href="#master-data/import">{t("Import data")}</a>}
          <div className="account">
            <button className="initials" onClick={() => setAccountOpen((v) => !v)} aria-label={t("Account menu")} aria-expanded={accountOpen}>{initials(session.user.display_name)}</button>
            {accountOpen && <div className="account-menu"><b>{session.user.display_name}</b><small>{session.user.email}</small><small className="role-label">{role} · {workspace.company_name}</small><div className="menu-language"><span>{t("Language")}</span>{languageSwitch}</div><a className="menu-link" href="#account">{t("Sessions & security")}</a><button onClick={onSignOut}><LogOut size={15} /> {t("Sign out")}</button></div>}
          </div>
          <button className="icon-button menu-button" onClick={() => setMenuOpen((v) => !v)} aria-label={menuOpen ? t("Close menu") : t("Open menu")} aria-expanded={menuOpen}>{menuOpen ? <X size={18} /> : <Menu size={18} />}</button>
        </div>
      </div>
    </header>
    <main id="main">
      {route.section === "risk" ? <RiskBoard />
        : route.section === "reports" ? <ReportsPage />
        : route.section === "actions" ? <ActionsPage sub={route.sub} permissions={workspace.permissions} />
        : route.section === "orders" ? <OrdersPage sub={route.sub} permissions={workspace.permissions} />
        : route.section === "outsourcing" ? <OutsourcingPage sub={route.sub} permissions={workspace.permissions} />
        : route.section === "stock" ? <StockPage permissions={workspace.permissions} />
        : route.section === "master-data" ? <MasterDataPage tab={route.sub} permissions={workspace.permissions} />
        : route.section === "settings" ? <SettingsPage permissions={workspace.permissions} />
        : route.section === "account" ? <AccountPage onSignOut={onSignOut} />
          : <MyWork session={session} workspace={workspace} />}
    </main>
    <SiteFooter title={workspace.company_name} link={route.section === "settings" ? { href: "#my-work", label: t("My work") } : { href: "#settings", label: t("Company & sites") }} note={<>{t("Signed in as {0}", [session.user.display_name])} · <span className="role-label">{role}</span></>} />
  </div>;
}

function SiteFooter({ title, note, link }: { title: string; note: React.ReactNode; link?: { href: string; label: string } }) {
  return <footer className="wrap site-footer">
    <div className="foot-big"><span className="heading">{title}</span>{link && <a href={link.href}>{link.label} →</a>}</div>
    <div className="foot-small"><span>{t("Thodara ERP · Workspace data is private to your organization.")}</span><span>{note}</span></div>
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
  const risk = useRiskBoard();
  const myActions = useQuery({ queryKey: ["actions", "dashboard"], queryFn: () => api<ActionPage>("/api/v1/actions?mine=true&status=active&limit=5"), staleTime: 0 });
  const ac = myActions.data?.counts;
  const rc = risk.data?.counts;
  const openLines = risk.data?.lines.length;
  const needing = (risk.data?.lines ?? []).filter((l) => l.headline !== "on_track" && l.headline !== "ready");
  const trouble = risk.data ? needing.length : undefined;
  const attention = needing.slice(0, 5);

  const counts = [items.data, customers.data, suppliers.data];
  const known = counts.every((value) => value !== undefined);
  const masterReady = known && counts.every((value) => (value ?? 0) > 0);
  const masterStarted = counts.some((value) => (value ?? 0) > 0);
  const masterTag = !known ? t("Checking") : masterReady ? t("Ready") : masterStarted ? t("In progress") : t("Not started");
  const firstName = session.user.display_name.split(" ")[0] ?? "";
  const hour = Number(new Intl.DateTimeFormat(locale(), { hour: "numeric", hourCycle: "h23", timeZone: workspace.sites[0]?.time_zone ?? "UTC" }).format(new Date()));
  const greeting = hour < 12 ? t("Good morning") : hour < 17 ? t("Good afternoon") : t("Good evening");
  const dateLabel = new Intl.DateTimeFormat(locale(), { weekday: "short", day: "numeric", month: "short", timeZone: workspace.sites[0]?.time_zone ?? "UTC" }).format(new Date());
  const siteCount = sites.data?.length;
  const show = (value: number | undefined) => (value === undefined ? "…" : String(value));

  return <>
    <section className="wrap hero">
      <div className="hero-copy">
        <span className="eyebrow">{t("MY WORK · {0}", [workspace.company_name.toUpperCase()])}</span>
        <h1 className="display">{greeting},<br /><em>{firstName}.</em></h1>
        <p className="lede">{openLines === undefined ? t("Working out your delivery picture…") : openLines === 0 ? t("No open customer order lines yet. Enter or import an order to see whether it will ship on time.") : trouble ? t("{0} of {1} open order lines need attention today.", [trouble, openLines]) : t("All {0} open order lines are on track or ready.", [openLines])}</p>
        <a className="primary-button hero-button" href={openLines ? "#risk" : "#orders/new"}>{openLines ? t("Open delivery risk") : t("Enter the first order")} <ArrowRight size={16} /></a>
        <div className="meta-line"><span>{dateLabel}</span>{workspace.sites[0] && <span>{workspace.sites[0].name}</span>}{siteCount !== undefined && <span>{siteCount} {siteCount === 1 ? t("site") : t("sites")}</span>}</div>
      </div>
      <aside className="path-panel" aria-label={t("Order to dispatch")}>
        <div className="orbit" />
        <span className="eyebrow">{t("ORDER TO DISPATCH")}</span>
        <h2 className="heading">{t("Fulfillment path")}</h2>
        <ol className="path">
          <PathStep n={1} title={t("Master data")} note={t("Items, customers, suppliers, warehouses")} tag={masterTag} done={masterReady} />
          <PathStep n={2} title={t("Customer orders")} note={t("Lines, promised dates, dependencies")} tag={openLines ? t("{0} open lines", [openLines]) : t("None yet")} done={Boolean(openLines)} />
          <PathStep n={3} title={t("Job work & quality")} note={t("Batches, supplier updates, receipts, inspection")} tag={rc ? t("{0} unknown · {1} on hold", [rc.unknown, rc.quality_hold]) : "…"} />
          <PathStep n={4} title={t("Dispatch")} note={t("Shipments against orders")} tag={rc ? t("{0} ready to move", [rc.ready]) : "…"} />
        </ol>
        <span className="panel-note">{t("Every figure shows its source; unknown is never shown as late.")}</span>
      </aside>
    </section>

    <section className="wrap figures" aria-label={t("Operations overview")}>
      <Figure label={t("Open order lines")} note={t("On confirmed orders")} value={openLines} href="#risk" />
      <Figure label={t("Late, short or at risk")} note={t("Need a recovery decision")} value={rc ? rc.confirmed_late + rc.quantity_shortage + rc.at_risk : undefined} href="#risk" />
      <Figure label={t("Unknown or stale")} note={t("Chase the supplier for an update")} value={rc?.unknown} href="#risk" />
      <Figure label={t("Quality holds")} note={t("Material waiting on a decision")} value={rc?.quality_hold} href="#risk" />
    </section>

    <section className="wrap split">
      {attention.length === 0 ? <div className="card inbox">
        <span className="ring"><Check size={30} /></span>
        <h3 className="heading">{t("Nothing needs attention")}</h3>
        <p>{t("Order lines that are late, short, at risk, on hold or unknown appear here, most severe first.")}</p>
      </div> : <div className="card inbox attention">
        <h3 className="heading">{t("Needs attention")}</h3>
        <ul>{attention.map((l) => <li key={l.line_id}><a href={`#orders/${l.order_id}`}><span className={`badge risk-${l.headline}`}>{t(HEADLINES.find(([k]) => k === l.headline)?.[1])}</span> <b className="mono">{l.order_number}/{l.line_no}</b> {l.customer_name}<small>{l.issues[0]?.message}</small></a></li>)}</ul>
        <a className="text-link" href="#risk">{t("All delivery risk →")}</a>
      </div>}
      <div>
        <span className="eyebrow">{t("DAILY CONTROL")}</span>
        <h2 className="section-title">{t("Today’s action list")}</h2>
        <p className="lede small">{ac ? t("{0} yours · {1} overdue across the team · {2} waiting for your approval.", [ac.mine, ac.overdue, ac.to_approve]) : t("Loading…")}</p>
        {(myActions.data?.items ?? []).length === 0 ? <p className="muted-line">{t("Nothing assigned to you. Create actions from an order’s delivery risk.")}</p>
          : <ul className="my-actions">{myActions.data!.items.map((a) => <li key={a.id}><a href={`#actions/${a.id}`}><ActionStatus a={a} /> <b>{a.title}</b><small>{t("due {0}{1}", [new Date(a.due_at).toLocaleString(locale(), { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }), a.line ? ` · ${a.line.order_number}/${a.line.line_no}` : ""])}</small></a></li>)}</ul>}
        <a className="quiet-button" href="#actions">{t("Open actions")} <ArrowRight size={15} /></a>
      </div>
    </section>

    <section className="wrap status">
      <div className="status-head">
        <div><span className="eyebrow">{t("STATUS YOU CAN TRUST")}</span><h2 className="section-title">{t("Reported is not received.")}</h2></div>
        <p className="lede small">{t("Every quantity keeps where it came from. A supplier’s word, the stores count and the inspector’s decision are shown separately, and a missing update reads as “unknown”, never as “late”.")}</p>
      </div>
      <div className="states">
        <div className="state"><b>{t("Reported")}</b><p>{t("What the supplier says is done, entered by your team with who said it and when.")}</p></div>
        <div className="state"><b>{t("Received")}</b><p>{t("What stores physically counted in at the gate, against the batch.")}</p></div>
        <div className="state"><b>{t("Accepted")}</b><p>{t("What quality passed. Only this counts as usable for an order.")}</p></div>
      </div>
    </section>

    <section className="band">
      <div className="wrap">
        <h2 className="section-title centered">{t("Your factory, set up")}</h2>
        <p className="lede small centered">{t("The shared records every order, work order and dispatch will refer to.")}</p>
        <div className="tiles">
          <a className="tile" href="#master-data/items"><strong>{show(items.data)}</strong><span>{t("Items")}</span><small>{t("Active products and materials")}</small></a>
          <a className="tile" href="#master-data/customers"><strong>{show(customers.data)}</strong><span>{t("Customers")}</span><small>{t("Active accounts")}</small></a>
          <a className="tile" href="#master-data/suppliers"><strong>{show(suppliers.data)}</strong><span>{t("Suppliers")}</span><small>{t("Including job work")}</small></a>
          <a className="tile" href="#master-data/warehouses"><strong>{show(warehouses.data)}</strong><span>{t("Warehouses")}</span><small>{siteCount === undefined ? t("Across your sites") : t(siteCount === 1 ? "Across {0} site" : "Across {0} sites", [siteCount])}</small></a>
          <a className="tile" href="#master-data/units"><strong>{show(units.data)}</strong><span>{t("Units")}</span><small>{conversions.data ? `${conversions.data.length} ${conversions.data.length === 1 ? t("conversion") : t("conversions")}` : t("Of measure")}</small></a>
        </div>
      </div>
    </section>
  </>;
}

function PathStep({ n, title, note, tag, done = false }: { n: number; title: string; note: string; tag: string; done?: boolean }) {
  return <li className={`step ${done ? "done" : ""}`}><span className="dot">{done ? <Check size={16} /> : n}</span><span><b>{title}</b><small>{note}</small></span><span className="tag">{tag}</span></li>;
}

function Figure({ label, note, value, href }: { label: string; note: string; value?: number; href?: string }) {
  const body = <><strong>{value ?? "…"}</strong><span>{label}</span><small>{note}</small></>;
  return href ? <a className="figure" href={href}>{body}</a> : <div className="figure">{body}</div>;
}

function initials(name: string) {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]?.toUpperCase() ?? "").join("");
}

export default App;
