export interface TenantChoice {
  tenant_id: string;
  tenant_name: string;
  role: string;
}

export interface SessionState {
  user: { id: string; email: string; display_name: string };
  active_tenant: TenantChoice | null;
  memberships: TenantChoice[];
  expires_at: string;
}

export interface WorkspaceSite {
  id: string;
  name: string;
  city: string | null;
  time_zone: string;
}

export interface WorkspaceSummary {
  tenant_id: string;
  company_name: string;
  country_code: string | null;
  base_currency: string | null;
  setup_complete: boolean;
  sites: WorkspaceSite[];
  module_state: "not_configured" | "ready";
  permissions: string[];
}

export interface Page<T> {
  items: T[];
  total: number;
}

export interface MasterRecord {
  id: string;
  code: string;
  name: string;
  status: "active" | "inactive";
  version: number;
  created_at: string;
  updated_at: string;
  item_type?: string;
  base_unit_id?: string;
  tracking?: string;
  description?: string | null;
  contact_email?: string | null;
  contact_phone?: string | null;
  city?: string | null;
  provides_job_work?: boolean;
  dimension?: string;
  decimal_places?: number;
  site_id?: string;
}

export interface UnitConversion {
  id: string;
  from_unit_id: string;
  from_unit_code: string;
  to_unit_id: string;
  to_unit_code: string;
  factor: string;
}

export interface Site {
  id: string;
  name: string;
  city: string | null;
  time_zone: string;
  status: string;
}

export interface Member {
  membership_id: string;
  user_id: string;
  email: string;
  display_name: string;
  role: string;
  status: string;
  site_scope: "all" | "selected";
  site_ids: string[];
}

export interface ImportReport {
  entity: string;
  total_rows: number;
  to_create: number;
  unchanged: number;
  errors: { row: number; field: string | null; message: string }[];
  committed: boolean;
}


export interface AuthSessionInfo {
  id: string;
  created_at: string;
  last_seen_at: string | null;
  expires_at: string;
  user_agent: string | null;
  current: boolean;
}

export interface CalendarInfo {
  site_id: string;
  configured: boolean;
  working_days: number[] | null;
  shift_start: string | null;
  shift_end: string | null;
  minutes_per_day: number | null;
  version: number | null;
  holidays: { id: string; holiday_date: string; name: string }[];
  upcoming: { day: string; working: boolean; reason: string | null }[];
}

export interface NumberSequence {
  document_type: string;
  prefix: string;
  next_number: number;
  padding: number;
  version: number;
  preview: string;
}

export type OrderStatus = "draft" | "confirmed" | "cancelled" | "closed";
export type OrderLineStatus = "open" | "fulfilled" | "short_closed" | "cancelled";

export interface PromiseOut {
  previous_date: string | null;
  new_date: string;
  reason_code: string;
  note: string | null;
  changed_by_label: string | null;
  changed_at: string;
}

export interface OrderLine {
  id: string;
  line_no: number;
  item_id: string;
  item_code: string;
  item_name: string;
  unit_code: string;
  ordered_qty: string;
  shipped_qty: string;
  cancelled_qty: string;
  short_closed_qty: string;
  remaining_qty: string;
  requested_date: string;
  promised_date: string | null;
  status: OrderLineStatus;
  status_reason: string | null;
  version: number;
  promise_history: PromiseOut[];
}

export interface OrderDetail {
  id: string;
  number: string;
  site_id: string;
  site_name: string;
  customer_id: string;
  customer_code: string;
  customer_name: string;
  customer_reference: string | null;
  order_date: string;
  status: OrderStatus;
  status_reason: string | null;
  notes: string | null;
  confirmed_at: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  lines: OrderLine[];
}

export interface OrderSummary {
  id: string;
  number: string;
  customer_code: string;
  customer_name: string;
  customer_reference: string | null;
  site_name: string;
  order_date: string;
  status: OrderStatus;
  line_count: number;
  open_lines: number;
  next_promised_date: string | null;
}

export interface OrderImportIssue {
  row: number;
  field: string | null;
  message: string;
}

export interface OrderImportReport {
  total_rows: number;
  orders_to_create: number;
  lines_to_create: number;
  unchanged_orders: number;
  errors: OrderImportIssue[];
  committed: boolean;
  created_numbers: string[];
}
