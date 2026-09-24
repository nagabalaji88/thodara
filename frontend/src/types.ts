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
}

