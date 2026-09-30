import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, LoaderCircle, LogOut, MonitorSmartphone } from "lucide-react";
import { api } from "./api";
import type { AuthSessionInfo } from "./types";

export function deviceLabel(userAgent: string | null): string {
  if (!userAgent) return "Unknown device";
  const browser = /Edg\//.test(userAgent) ? "Edge"
    : /Firefox\//.test(userAgent) ? "Firefox"
      : /Chrome\//.test(userAgent) ? "Chrome"
        : /Safari\//.test(userAgent) ? "Safari"
          : "Browser";
  const os = /iPhone|iPad/.test(userAgent) ? "iPhone or iPad"
    : /Android/.test(userAgent) ? "Android"
      : /Windows/.test(userAgent) ? "Windows"
        : /Mac OS X|Macintosh/.test(userAgent) ? "Mac"
          : /Linux/.test(userAgent) ? "Linux"
            : "unknown system";
  return browser === "Browser" && os === "unknown system" ? "Other client" : `${browser} on ${os}`;
}

function when(value: string | null): string {
  if (!value) return "—";
  const minutes = Math.round((Date.now() - new Date(value).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  return new Date(value).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function AccountPage({ onSignOut }: { onSignOut: () => void }) {
  const queryClient = useQueryClient();
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: () => api<AuthSessionInfo[]>("/api/v1/auth/sessions") });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["sessions"] });
  const revoke = useMutation({ mutationFn: (id: string) => api<void>(`/api/v1/auth/sessions/${id}/revoke`, { method: "POST" }), onSuccess: refresh });
  const revokeOthers = useMutation({ mutationFn: () => api<{ revoked: number }>("/api/v1/auth/sessions/revoke-others", { method: "POST" }), onSuccess: refresh });
  const others = sessions.data?.filter((s) => !s.current).length ?? 0;
  const error = sessions.error ?? revoke.error ?? revokeOthers.error;

  return <section className="wrap page">
    <header className="page-head"><div><span className="eyebrow">YOUR ACCOUNT</span><h1 className="page-title">Sessions &amp; security</h1></div><p className="lede small">Every browser or device signed in to your account. Sign out any you don’t recognise; the change takes effect on its next request.</p></header>
    <div className="panel">
      <div className="sub-head"><MonitorSmartphone size={15} /><h3>Signed-in devices</h3><p>Sessions end on their own after 8 hours.</p></div>
      {sessions.isPending ? <div className="table-state"><LoaderCircle className="spin" size={16} /> Loading…</div>
        : <div className="member-list">{sessions.data?.map((s) => <div key={s.id} className="member-row">
          <div className="member-who"><span><b>{deviceLabel(s.user_agent)}{s.current && <span className="badge badge-active current-badge">This device</span>}</b><small>Signed in {when(s.created_at)} · Last active {when(s.last_seen_at)}</small></span></div>
          {s.current
            ? <button className="quiet-button" onClick={onSignOut}><LogOut size={15} /> Sign out</button>
            : <button className="quiet-button" disabled={revoke.isPending} onClick={() => revoke.mutate(s.id)}>Sign out this device</button>}
        </div>)}</div>}
      {others > 0 && <div className="inline-form"><button className="primary-button compact" disabled={revokeOthers.isPending} onClick={() => revokeOthers.mutate()}>Sign out all other devices ({others})</button></div>}
      {error && <div className="form-error" role="alert"><AlertCircle size={15} />{error.message}</div>}
      <p className="hint">Password reset and two-step verification arrive once the sign-in method is decided.</p>
    </div>
  </section>;
}
