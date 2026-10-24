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
  components: LineComponent[];
  operations: LineOperation[];
}

export interface BatchAllocation {
  id: string;
  batch_id: string;
  batch_number: string;
  batch_status: string;
  supplier_name: string;
  quantity: string;
  batch_quantity: string | null;
  expected_return_date: string | null;
  revised_return_date: string | null;
  last_reported_at: string | null;
  reported_completed: string | null;
  reported_rejected: string | null;
  reported_pending: string | null;
  blocker: string | null;
  received_qty: string | null;
  accepted_qty: string | null;
  held_qty: string | null;
}

export interface LineComponent {
  id: string;
  item_id: string;
  item_code: string;
  item_name: string;
  unit_code: string;
  qty_per_unit: string;
  required_qty: string;
  allocated_qty: string;
  outsourced_operation: string | null;
  allocations: BatchAllocation[];
}

export interface LineOperation {
  id: string;
  sequence: number;
  name: string;
  kind: "in_house" | "transport";
  duration_minutes: number;
}

export interface DependencyTemplate {
  source_order_number: string | null;
  components: LineComponent[];
  operations: LineOperation[];
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

export type BatchStatus = "planned" | "at_supplier" | "closed" | "cancelled";

export interface BatchAllocationDetail {
  id: string;
  component_id: string;
  quantity: string;
  order_id: string;
  order_number: string;
  order_status: string;
  customer_name: string;
  line_no: number;
  line_item_code: string;
  line_status: string;
  promised_date: string | null;
  component_required_qty: string;
  priority_rank: number | null;
  priority_reason: string | null;
  priority_set_by_label: string | null;
  priority_set_at: string | null;
}

export interface BatchMovement {
  kind: string;
  quantity: string;
  movement_date: string;
  document_reference: string | null;
  note: string | null;
  recorded_by_label: string | null;
  recorded_at: string;
}

export interface BatchDetail {
  id: string;
  number: string;
  site_id: string;
  site_name: string;
  supplier_id: string;
  supplier_code: string;
  supplier_name: string;
  item_id: string;
  item_code: string;
  item_name: string;
  unit_code: string;
  operation: string;
  quantity: string;
  allocated_qty: string;
  expected_return_date: string;
  status: BatchStatus;
  status_reason: string | null;
  sent_date: string | null;
  challan_reference: string | null;
  notes: string | null;
  version: number;
  created_at: string;
  updated_at: string;
  allocations: BatchAllocationDetail[];
  movements: BatchMovement[];
  quantities: QuantityPicture;
  latest_update: SupplierUpdate | null;
  updates: SupplierUpdate[];
  receipts: BatchReceipt[];
}

export interface QuantityPicture {
  sent: string;
  reported_completed: string | null;
  reported_rejected: string | null;
  reported_pending: string | null;
  reported_unaccounted: string | null;
  received: string;
  awaiting_inspection: string;
  accepted: string;
  held: string;
  rejected_at_inspection: string;
  rework: string;
  still_at_supplier: string;
}

export interface QualityDecision {
  kind: "inspection" | "hold_release";
  accepted_qty: string;
  rejected_qty: string;
  held_qty: string;
  rework_qty: string;
  note: string | null;
  decided_by_label: string | null;
  decided_at: string;
  same_person: boolean;
}

export interface BatchReceipt {
  id: string;
  received_qty: string;
  receipt_date: string;
  document_reference: string | null;
  note: string | null;
  status: "awaiting_inspection" | "inspected";
  accepted_qty: string;
  rejected_qty: string;
  held_qty: string;
  rework_qty: string;
  received_by_label: string | null;
  recorded_at: string;
  version: number;
  decisions: QualityDecision[];
}

export interface SupplierUpdate {
  id: string;
  completed_qty: string;
  rejected_qty: string;
  pending_qty: string;
  unaccounted_qty: string;
  revised_return_date: string | null;
  blocker: string | null;
  source: "manufacturer_entered";
  contact_method: "phone" | "whatsapp" | "email" | "visit" | "other";
  contact_name: string | null;
  reported_at: string;
  confirmation_state: "supplier_confirmation_pending";
  corrects_id: string | null;
  correction_reason: string | null;
  superseded: boolean;
  recorded_by_label: string | null;
  recorded_at: string;
}

export interface ReportFields {
  last_reported_at?: string | null;
  reported_completed?: string | null;
  reported_rejected?: string | null;
  reported_pending?: string | null;
  revised_return_date?: string | null;
  blocker?: string | null;
  received_qty?: string | null;
  accepted_qty?: string | null;
  held_qty?: string | null;
}

export interface BatchSummary {
  id: string;
  number: string;
  site_name: string;
  supplier_name: string;
  item_code: string;
  item_name: string;
  unit_code: string;
  operation: string;
  quantity: string;
  allocated_qty: string;
  order_count: number;
  expected_return_date: string;
  sent_date: string | null;
  status: BatchStatus;
}

export interface BatchSummary extends ReportFields {}

export interface AllocationCandidate {
  component_id: string;
  order_id: string;
  order_number: string;
  customer_name: string;
  line_no: number;
  line_item_code: string;
  promised_date: string | null;
  outsourced_operation: string | null;
  required_qty: string;
  allocated_qty: string;
  open_qty: string;
}
