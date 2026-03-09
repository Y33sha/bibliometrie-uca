-- Migration 019 : Scinder persons en persons (hub d'identité) + persons_rh (données RH)
--
-- Objectif :
--   - persons = entité pérenne d'identité (nom, prénom, identifiants)
--   - persons_rh = données issues de l'extraction RH (département, rôle, dates, email)
--     → peut être supprimée sans impacter le reste
--
-- La FK est dans persons_rh.person_id → persons.id

BEGIN;

-- 1. Créer persons_rh
CREATE TABLE persons_rh (
    id            SERIAL PRIMARY KEY,
    person_id     INTEGER NOT NULL UNIQUE REFERENCES persons(id) ON DELETE CASCADE,
    email         TEXT,
    role_title    TEXT,
    department_name TEXT,
    structure_id  INTEGER REFERENCES structures(id),
    start_date    DATE,
    end_date      DATE,
    hr_export_date DATE,
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_persons_rh_person_id ON persons_rh(person_id);
CREATE INDEX idx_persons_rh_department ON persons_rh(department_name);

-- 2. Migrer les données RH existantes
INSERT INTO persons_rh (person_id, email, role_title, department_name, structure_id, start_date, end_date, hr_export_date)
SELECT id, email, role_title, department_name, structure_id, start_date, end_date, hr_export_date
FROM persons;

-- 3. Supprimer les colonnes RH de persons
ALTER TABLE persons DROP COLUMN IF EXISTS email;
ALTER TABLE persons DROP COLUMN IF EXISTS role_title;
ALTER TABLE persons DROP COLUMN IF EXISTS department_name;
ALTER TABLE persons DROP COLUMN IF EXISTS structure_id;
ALTER TABLE persons DROP COLUMN IF EXISTS start_date;
ALTER TABLE persons DROP COLUMN IF EXISTS end_date;
ALTER TABLE persons DROP COLUMN IF EXISTS hr_export_date;

COMMIT;
