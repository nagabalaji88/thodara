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

