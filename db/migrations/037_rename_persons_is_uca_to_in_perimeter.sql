-- Migration 037 : renommer persons.is_uca en persons.in_perimeter
-- 2026-04-09

ALTER TABLE IF EXISTS authorships RENAME COLUMN is_uca TO in_perimeter;
