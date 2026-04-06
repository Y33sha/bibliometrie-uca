-- Migration 011 : renommer wos_institutions en wos_organizations
-- 2026-04-05

ALTER TABLE IF EXISTS wos_institutions RENAME TO wos_organizations;
ALTER INDEX IF EXISTS idx_wos_inst_ror RENAME TO idx_wos_org_ror;
ALTER SEQUENCE IF EXISTS wos_institutions_id_seq RENAME TO wos_organizations_id_seq;
