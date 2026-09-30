import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CalendarDays, Check, Hash, LoaderCircle, Plus, Trash2 } from "lucide-react";
import { api } from "./api";
import type { CalendarInfo, NumberSequence, Site } from "./types";

const WEEKDAYS: [number, string][] = [[1, "Mon"], [2, "Tue"], [3, "Wed"], [4, "Thu"], [5, "Fri"], [6, "Sat"], [7, "Sun"]];
const SUGGESTED = { working_days: [1, 2, 3, 4, 5, 6], shift_start: "09:00", shift_end: "18:00" };
const hhmm = (value: string | null) => (value ?? "").slice(0, 5);
const hours = (minutes: number) => `${Math.floor(minutes / 60)} h${minutes % 60 ? ` ${minutes % 60} min` : ""}`;

export function CalendarPanel({ canManage }: { canManage: boolean }) {
  const sites = useQuery({ queryKey: ["sites"], queryFn: () => api<Site[]>("/api/v1/organization/sites") });
  const [siteId, setSiteId] = useState("");
  useEffect(() => { if (!siteId && sites.data?.[0]) setSiteId(sites.data[0].id); }, [sites.data, siteId]);
  if (!sites.data?.length) return null;
  return <div className="panel">
    <div className="sub-head"><CalendarDays size={15} /><h3>Working calendar</h3><p>Working days, shift hours and holidays for each site. Delivery-risk dates are worked out on this calendar; a site without one shows its dates as unknown.</p></div>
    {sites.data.length > 1 && <div className="toolbar"><select aria-label="Site" value={siteId} onChange={(e) => setSiteId(e.target.value)}>{sites.data.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></div>}
    {siteId && <SiteCalendarEditor key={siteId} siteId={siteId} canManage={canManage} />}
  </div>;
}

function SiteCalendarEditor({ siteId, canManage }: { siteId: string; canManage: boolean }) {
  const queryClient = useQueryClient();
  const url = `/api/v1/organization/sites/${siteId}/calendar`;
  const calendar = useQuery({ queryKey: ["calendar", siteId], queryFn: () => api<CalendarInfo>(url) });
  const [days, setDays] = useState<number[]>(SUGGESTED.working_days);
  const [start, setStart] = useState(SUGGESTED.shift_start);
  const [end, setEnd] = useState(SUGGESTED.shift_end);
  const [holidayDate, setHolidayDate] = useState("");
  const [holidayName, setHolidayName] = useState("");
  useEffect(() => {
    if (calendar.data?.configured) {
      setDays(calendar.data.working_days ?? []);
      setStart(hhmm(calendar.data.shift_start));
      setEnd(hhmm(calendar.data.shift_end));
    }
  }, [calendar.data]);
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["calendar", siteId] });
  const save = useMutation({
    mutationFn: () => api<CalendarInfo>(url, { method: "PUT", body: JSON.stringify({ working_days: days, shift_start: start, shift_end: end, version: calendar.data?.version ?? undefined }) }),
    onSuccess: (value) => queryClient.setQueryData(["calendar", siteId], value),
  });
  const addHoliday = useMutation({
    mutationFn: () => api(`/api/v1/organization/sites/${siteId}/holidays`, { method: "POST", body: JSON.stringify({ holiday_date: holidayDate, name: holidayName }) }),
    onSuccess: () => { setHolidayDate(""); setHolidayName(""); refresh(); },
  });
  const removeHoliday = useMutation({ mutationFn: (id: string) => api(`/api/v1/organization/sites/${siteId}/holidays/${id}`, { method: "DELETE" }), onSuccess: refresh });
  if (calendar.isPending) return <div className="table-state"><LoaderCircle className="spin" size={16} /> Loading…</div>;
  if (calendar.isError) return <div className="form-error" role="alert"><AlertCircle size={15} />{calendar.error.message}</div>;
  const data = calendar.data;
  const error = save.error ?? addHoliday.error ?? removeHoliday.error;
  return <div className="calendar-editor">
    {!data.configured && <div className="notice-line"><AlertCircle size={16} /><span>This site has no working calendar yet. {canManage ? "Review the suggested pattern below and save it." : "Ask an administrator to set it up."}</span></div>}
    <div className="calendar-grid">
      <div>
        <span className="field-label">Working days</span>
        <div className="day-chips" role="group" aria-label="Working days">{WEEKDAYS.map(([n, label]) => <button key={n} type="button" disabled={!canManage} aria-pressed={days.includes(n)} className={days.includes(n) ? "chip on" : "chip"} onClick={() => setDays((d) => d.includes(n) ? d.filter((x) => x !== n) : [...d, n].sort())}>{label}</button>)}</div>
        <div className="shift-row">
          <label>Shift starts<input type="time" value={start} disabled={!canManage} onChange={(e) => setStart(e.target.value)} /></label>
          <label>Shift ends<input type="time" value={end} disabled={!canManage} onChange={(e) => setEnd(e.target.value)} /></label>
        </div>
        {data.configured && data.minutes_per_day !== null && <p className="hint">{hours(data.minutes_per_day)} of working time per working day. Breaks and overnight shifts are not modelled yet.</p>}
        {canManage && <button className="primary-button compact" disabled={save.isPending || days.length === 0} onClick={() => save.mutate()}>{save.isPending ? <LoaderCircle className="spin" size={15} /> : <Check size={15} />} {data.configured ? "Save calendar" : "Save this calendar"}</button>}
      </div>
      <div>
        <span className="field-label">Holidays</span>
        {data.holidays.length ? <ul className="holiday-list">{data.holidays.map((h) => <li key={h.id}><span className="mono">{h.holiday_date}</span><span>{h.name}</span>{canManage && <button className="icon-button small" aria-label={`Remove holiday ${h.name}`} onClick={() => removeHoliday.mutate(h.id)}><Trash2 size={13} /></button>}</li>)}</ul> : <p className="muted-line">No holidays added.</p>}
        {canManage && <form className="conversion-form" onSubmit={(e) => { e.preventDefault(); addHoliday.mutate(); }}>
          <input type="date" aria-label="Holiday date" value={holidayDate} onChange={(e) => setHolidayDate(e.target.value)} required />
          <input aria-label="Holiday name" placeholder="e.g. Diwali" value={holidayName} onChange={(e) => setHolidayName(e.target.value)} required maxLength={120} />
          <button className="quiet-button" type="submit" disabled={addHoliday.isPending}><Plus size={14} /> Add</button>
        </form>}
      </div>
    </div>
    {data.upcoming.length > 0 && <div><span className="field-label">Next 14 days</span><ol className="day-strip">{data.upcoming.map((d) => <li key={d.day} className={d.working ? "work" : "off"} title={d.reason ?? "Working day"}><b>{new Date(`${d.day}T00:00:00`).toLocaleDateString("en-IN", { weekday: "short" })}</b><span>{Number(d.day.slice(8))}</span><small>{d.working ? "Work" : d.reason}</small></li>)}</ol></div>}
    {error && <div className="form-error" role="alert"><AlertCircle size={15} />{error.message}</div>}
  </div>;
}

const DOC_LABELS: Record<string, string> = { sales_order: "Sales orders", outsourced_batch: "Outsourced batches", dispatch: "Dispatch notes" };

export function NumberingPanel({ canManage }: { canManage: boolean }) {
  const sequences = useQuery({ queryKey: ["numbering"], queryFn: () => api<NumberSequence[]>("/api/v1/organization/numbering") });
  return <div className="panel">
    <div className="sub-head"><Hash size={15} /><h3>Document numbers</h3><p>How new documents are numbered. Numbers never repeat, and the next number cannot be moved backwards.</p></div>
    {sequences.isPending ? <div className="table-state"><LoaderCircle className="spin" size={16} /> Loading…</div>
      : sequences.isError ? <div className="form-error" role="alert"><AlertCircle size={15} />{sequences.error.message}</div>
        : <div className="member-list">{sequences.data.map((s) => <SequenceRow key={`${s.document_type}-${s.version}`} sequence={s} canManage={canManage} />)}</div>}
  </div>;
}

function SequenceRow({ sequence, canManage }: { sequence: NumberSequence; canManage: boolean }) {
  const queryClient = useQueryClient();
  const [prefix, setPrefix] = useState(sequence.prefix);
  const [padding, setPadding] = useState(sequence.padding);
  const [next, setNext] = useState(sequence.next_number);
  const save = useMutation({
    mutationFn: () => api<NumberSequence>(`/api/v1/organization/numbering/${sequence.document_type}`, { method: "PUT", body: JSON.stringify({ prefix, padding, next_number: next, version: sequence.version }) }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["numbering"] }),
  });
  const preview = `${prefix.toUpperCase()}${String(next).padStart(padding, "0")}`;
  const dirty = prefix !== sequence.prefix || padding !== sequence.padding || next !== sequence.next_number;
  return <div className="member-row">
    <div className="member-who"><span><b>{DOC_LABELS[sequence.document_type] ?? sequence.document_type}</b><small>Next: <span className="mono">{dirty ? preview : sequence.preview}</span></small></span></div>
    {canManage && <div className="member-access">
      <label className="mini-field">Prefix<input value={prefix} maxLength={12} onChange={(e) => setPrefix(e.target.value.toUpperCase())} /></label>
      <label className="mini-field">Digits<input type="number" min={1} max={10} value={padding} onChange={(e) => setPadding(Number(e.target.value))} /></label>
      <label className="mini-field">Next number<input type="number" min={sequence.next_number} value={next} onChange={(e) => setNext(Number(e.target.value))} /></label>
      <button className="quiet-button" disabled={!dirty || save.isPending} onClick={() => save.mutate()}><Check size={14} /> Save</button>
      {save.error && <span className="inline-error" role="alert">{save.error.message}</span>}
    </div>}
  </div>;
}
