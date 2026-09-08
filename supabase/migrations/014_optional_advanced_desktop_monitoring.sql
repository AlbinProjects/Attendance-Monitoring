-- Optional advanced desktop monitoring. Disabled by default.
-- Only Super Admin can change this setting through the backend.
alter table company_settings
  add column if not exists advanced_desktop_monitoring_enabled boolean not null default false;
