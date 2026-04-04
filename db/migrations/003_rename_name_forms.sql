-- Migration 003 : renommer name_forms en structure_name_forms
-- 2026-04-04

ALTER TABLE name_forms RENAME TO structure_name_forms;
ALTER INDEX idx_name_forms_active RENAME TO idx_structure_name_forms_active;
ALTER INDEX idx_name_forms_structure RENAME TO idx_structure_name_forms_structure;
ALTER SEQUENCE name_forms_id_seq RENAME TO structure_name_forms_id_seq;
