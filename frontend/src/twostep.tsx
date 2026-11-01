import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { AlertCircle, ArrowRight, Check, Copy, Download, KeyRound, LoaderCircle, LogOut, ShieldCheck, Smartphone } from "lucide-react";
import { api } from "./api";
import type { SessionState } from "./types";
import { locale, t } from "./i18n";

/** Two-step sign-in with a free authenticator app (ADR-0015). The server enforces every rule. */

type Setup = { secret: string; otpauth_uri: string; qr_svg: string };
type Enabled = { backup_codes: string[]; session: SessionState };

function CodeInput({ value, onChange, allowBackup, autoFocus }: { value: string; onChange: (v: string) => void; allowBackup?: boolean; autoFocus?: boolean }) {
  return <div className="input-wrap"><KeyRound size={16} /><input
    aria-label={allowBackup ? t("Authenticator or backup code") : t("Authenticator code")}
    value={value} onChange={(e) => onChange(e.target.value)} autoFocus={autoFocus}
    autoComplete="one-time-code" inputMode={allowBackup ? "text" : "numeric"} maxLength={allowBackup ? 16 : 6}
    placeholder={allowBackup ? t("6-digit code or backup code") : t("6-digit code")} required minLength={6} /></div>;
}

function Problem({ error }: { error: Error | null }) {
  return error ? <div className="form-error" role="alert"><AlertCircle size={15} />{error.message}</div> : null;
}

/** Second step of signing in. */
export function TwoStepCodePage({ session, onDone, onSignOut, header }: { session: SessionState; onDone: (s: SessionState) => void; onSignOut: () => void; header: React.ReactNode }) {
  const [code, setCode] = useState("");
  const verify = useMutation({
    mutationFn: () => api<SessionState>("/api/v1/auth/two-step/verify", { method: "POST", body: JSON.stringify({ code }) }),
    onSuccess: onDone,
    onError: () => setCode(""),
  });
  return <div className="page-frame">{header}
    <main className="wrap hero hero-auth">
      <div className="hero-copy"><span className="eyebrow">{t("TWO-STEP SIGN-IN")}</span><h1 className="display">{t("One more")} <em>{t("step.")}</em></h1><p className="lede">{t("Open your authenticator app and enter the 6-digit code for Thodara ({0}).", [session.user.email])}</p></div>
      <form className="card form-card" onSubmit={(e) => { e.preventDefault(); verify.mutate(); }}>
        <span className="eyebrow">{t("AUTHENTICATOR CODE")}</span>
        <h2 className="heading">{t("Enter your code")}</h2>
        <CodeInput value={code} onChange={setCode} allowBackup autoFocus />
        <p className="hint">{t("No phone? Enter one of your backup codes instead. Each backup code works once.")}</p>
        <Problem error={verify.error} />
        <button className="primary-button wide-button" disabled={verify.isPending || code.trim().length < 6} type="submit">{verify.isPending ? <LoaderCircle className="spin" size={16} /> : <>{t("Verify and continue")} <ArrowRight size={16} /></>}</button>
        <p className="hint">{t("Lost your phone and your backup codes? Ask an administrator of your company to reset your two-step sign-in.")}</p>
        <button className="quiet-button" type="button" onClick={onSignOut}><LogOut size={15} /> {t("Sign out")}</button>
      </form>
    </main>
  </div>;
}

/** Owners and administrators past the 7-day grace period set it up before continuing. */
export function TwoStepEnrolPage({ onDone, onSignOut, header }: { onDone: (s: SessionState) => void; onSignOut: () => void; header: React.ReactNode }) {
  return <div className="page-frame">{header}
    <main className="wrap page narrow-page">
      <header className="page-head"><div><span className="eyebrow">{t("TWO-STEP SIGN-IN")}</span><h1 className="page-title">{t("Set up two-step sign-in")}</h1></div><p className="lede small">{t("Owners and administrators must use an authenticator app. It takes about a minute, and you need it at every sign-in from now on.")}</p></header>
      <div className="panel"><SetupFlow onFinished={onDone} /></div>
      <button className="quiet-button" onClick={onSignOut}><LogOut size={15} /> {t("Sign out")}</button>
    </main>
  </div>;
}

/** Scan, confirm with a code, then save the backup codes. */
export function SetupFlow({ onFinished, onCancel }: { onFinished: (s: SessionState) => void; onCancel?: () => void }) {
  const [code, setCode] = useState("");
  const start = useMutation({ mutationFn: () => api<Setup>("/api/v1/auth/two-step/setup", { method: "POST" }) });
  const enable = useMutation({
    mutationFn: () => api<Enabled>("/api/v1/auth/two-step/enable", { method: "POST", body: JSON.stringify({ code }) }),
    onError: () => setCode(""),
  });
  if (enable.data) return <BackupCodesView codes={enable.data.backup_codes} intro={t("Two-step sign-in is on. Save these backup codes now; they are shown only once.")} onDone={() => onFinished(enable.data.session)} />;
  if (!start.data) return <div className="two-step-start">
    <ol className="steps-list">
      <li>{t("Install a free authenticator app on your phone, for example Google Authenticator, Microsoft Authenticator or 2FAS.")}</li>
      <li>{t("Scan the code Thodara shows you, then type the 6-digit code from the app.")}</li>
      <li>{t("Save your ten backup codes somewhere safe, away from your phone.")}</li>
    </ol>
    <Problem error={start.error} />
    <div className="inline-form">
      <button className="primary-button compact" disabled={start.isPending} onClick={() => start.mutate()}>{start.isPending ? <LoaderCircle className="spin" size={14} /> : <Smartphone size={14} />} {t("Start set-up")}</button>
      {onCancel && <button className="quiet-button" onClick={onCancel}>{t("Cancel")}</button>}
    </div>
  </div>;
  const groups = start.data.secret.match(/.{1,4}/g)?.join(" ") ?? start.data.secret;
  return <form className="two-step-scan" onSubmit={(e) => { e.preventDefault(); enable.mutate(); }}>
    <img className="qr" alt={t("QR code to scan with your authenticator app")} src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(start.data.qr_svg)}`} width={210} height={210} />
    <div className="two-step-fields">
      <p className="muted">{t("Scan this with your authenticator app. If you cannot scan, add an account by hand with this key (time-based):")}</p>
      <code className="secret-key" aria-label={t("Set-up key")}>{groups}</code>
      <label>{t("Code from the app")}</label>
      <CodeInput value={code} onChange={setCode} autoFocus />
      <Problem error={enable.error} />
      <div className="inline-form">
        <button className="primary-button compact" type="submit" disabled={enable.isPending || code.trim().length !== 6}>{enable.isPending ? <LoaderCircle className="spin" size={14} /> : <Check size={14} />} {t("Turn on two-step sign-in")}</button>
        {onCancel && <button className="quiet-button" type="button" onClick={onCancel}>{t("Cancel")}</button>}
      </div>
    </div>
  </form>;
}

export function BackupCodesView({ codes, intro, onDone }: { codes: string[]; intro: string; onDone: () => void }) {
  const [copied, setCopied] = useState(false);
  const [saved, setSaved] = useState(false);
  const text = `${t("Thodara backup codes")}\n${new Date().toLocaleDateString(locale())}\n\n${codes.join("\n")}\n\n${t("Each code works once.")}\n`;
  const copy = () => { void navigator.clipboard?.writeText(text).then(() => setCopied(true)).catch(() => setCopied(false)); };
  const download = () => {
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    const link = Object.assign(document.createElement("a"), { href: url, download: "thodara-backup-codes.txt" });
    link.click();
    URL.revokeObjectURL(url);
  };
  return <div className="backup-codes">
    <p className="success-line"><ShieldCheck size={14} /> {intro}</p>
    <ol className="code-grid">{codes.map((c) => <li key={c}><code>{c}</code></li>)}</ol>
    <div className="inline-form">
      <button className="quiet-button" onClick={copy}>{copied ? <Check size={14} /> : <Copy size={14} />} {copied ? t("Copied") : t("Copy")}</button>
      <button className="quiet-button" onClick={download}><Download size={14} /> {t("Download")}</button>
    </div>
    <label className="check-field"><input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} />{t("I have saved these codes")}</label>
    <button className="primary-button compact" disabled={!saved} onClick={onDone}>{t("Continue")} <ArrowRight size={14} /></button>
  </div>;
}

/** Account page panel: status, set-up, new backup codes, turning off. */
export function TwoStepPanel({ session, onSession }: { session: SessionState; onSession: (s: SessionState) => void }) {
  const state = session.two_step;
  const [mode, setMode] = useState<"idle" | "setup" | "codes" | "off">("idle");
  const [code, setCode] = useState("");
  const [fresh, setFresh] = useState<string[] | null>(null);
  const done = () => { setMode("idle"); setCode(""); };
  const replace = useMutation({
    mutationFn: () => api<{ backup_codes: string[] }>("/api/v1/auth/two-step/backup-codes", { method: "POST", body: JSON.stringify({ code }) }),
    onSuccess: (value) => { setFresh(value.backup_codes); done(); },
  });
  const disable = useMutation({
    mutationFn: () => api<SessionState>("/api/v1/auth/two-step/disable", { method: "POST", body: JSON.stringify({ code }) }),
    onSuccess: (value) => { onSession(value); done(); },
  });
  const action = mode === "codes" ? replace : disable;
  return <div className="panel">
    <div className="sub-head"><ShieldCheck size={15} /><h3>{t("Two-step sign-in")}</h3><p>{state.required ? t("Required for owners and administrators.") : t("Optional for your role, and recommended.")}</p></div>
    {fresh ? <BackupCodesView codes={fresh} intro={t("New backup codes. The old ones no longer work.")} onDone={() => setFresh(null)} />
      : mode === "setup" ? <SetupFlow onFinished={(s) => { onSession(s); done(); }} onCancel={done} />
      : <>
        <p className="two-step-status">{state.enabled
          ? <><span className="badge badge-active">{t("On")}</span> {t("A code from your authenticator app is needed at every sign-in. Backup codes left: {0}.", [state.backup_codes_left])}</>
          : <><span className="badge">{t("Off")}</span> {state.due_at ? t("Set it up by {0}. After that, you will have to set it up before you can continue.", [new Date(state.due_at).toLocaleDateString(locale(), { day: "numeric", month: "short", year: "numeric" })]) : t("Only your password protects this account.")}</>}</p>
        {state.enabled && state.backup_codes_left <= 3 && <p className="notice-line"><AlertCircle size={15} />{t("You are running out of backup codes. Get new ones.")}</p>}
        {mode === "idle" ? <div className="inline-form">
          {!state.enabled && <button className="primary-button compact" onClick={() => setMode("setup")}><Smartphone size={14} /> {t("Set up two-step sign-in")}</button>}
          {state.enabled && <button className="quiet-button" onClick={() => setMode("codes")}>{t("Get new backup codes")}</button>}
          {state.enabled && !state.required && <button className="quiet-button" onClick={() => setMode("off")}>{t("Turn off")}</button>}
        </div>
          : <form className="inline-form" onSubmit={(e) => { e.preventDefault(); action.mutate(); }}>
            <CodeInput value={code} onChange={setCode} allowBackup={mode === "off"} autoFocus />
            <button className="primary-button compact" type="submit" disabled={action.isPending || code.trim().length < 6}>{mode === "codes" ? t("Get new backup codes") : t("Turn off")}</button>
            <button className="quiet-button" type="button" onClick={done}>{t("Cancel")}</button>
          </form>}
        <Problem error={action.error} />
      </>}
  </div>;
}

/** Shown in the workspace while an owner or administrator is in the grace period. */
export function TwoStepBanner({ session }: { session: SessionState }) {
  const { required, enabled, due_at } = session.two_step;
  if (!required || enabled || !due_at) return null;
  const days = Math.max(0, Math.ceil((new Date(due_at).getTime() - Date.now()) / 86_400_000));
  return <div className="wrap"><p className="notice-line two-step-banner"><ShieldCheck size={15} /><span>{t("Owners and administrators must use two-step sign-in. Set it up within {0} days; after that you will have to set it up before you can continue.", [days])} <a href="#account">{t("Set it up now")}</a></span></p></div>;
}
