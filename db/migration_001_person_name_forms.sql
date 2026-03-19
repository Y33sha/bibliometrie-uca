-- Migration 001 : table des formes de noms de personnes
-- Chaque forme brute (normalisée lower/unaccent/trim) est mappée à un ou plusieurs person_id

CREATE TABLE IF NOT EXISTS person_name_forms (
    id          SERIAL PRIMARY KEY,
    name_form   TEXT NOT NULL,       -- unaccent(lower(trim(...)))
    person_ids  INT[] NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT person_name_forms_name_form_uq UNIQUE (name_form)
);

CREATE INDEX IF NOT EXISTS idx_pnf_person_ids ON person_name_forms USING GIN (person_ids);
