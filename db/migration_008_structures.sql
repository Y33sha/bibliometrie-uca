-- Migration 008 : Modélisation des structures et formes de noms
--
-- Remplace la dépendance aux fichiers JSON (labos.json, config_validation.json)
-- par un référentiel en base, permettant la boucle de rétroaction via l'interface.
--
-- Tables créées :
--   structures           — toutes les entités (UCA, labos, tutelles, partenaires, sites)
--   structure_relations   — liens entre structures (est_tutelle_de, est_partenaire_de)
--   name_forms            — formes de noms pour la détection automatique
--
-- La table laboratories existante est conservée pour compatibilité.
-- Un champ laboratory_id dans structures permet le lien.

BEGIN;

-- Types énumérés
CREATE TYPE structure_type AS ENUM (
    'universite',
    'onr',            -- CNRS, INRAE, Inserm, IRD…
    'chu',
    'ecole',          -- INP, VetAgro Sup, ENS Lyon, Mines St-Étienne…
    'labo',
    'equipe',
    'site',           -- site géographique (Clermont-Ferrand, Cézeaux…)
    'autre'
);

CREATE TYPE relation_type AS ENUM (
    'est_tutelle_de',
    'est_partenaire_de'
);


-- Table principale : toutes les structures
CREATE TABLE structures (
    id              SERIAL PRIMARY KEY,
    code            TEXT UNIQUE NOT NULL,        -- identifiant court : uca, cnrs, lpc, chu_cf, site_clermont
    name            TEXT NOT NULL,               -- nom complet
    acronym         TEXT,                        -- acronyme (peut être NULL)
    type            structure_type NOT NULL,
    ror_id          TEXT,                        -- identifiant ROR (pour les entités qui en ont)
    rnsr_id         TEXT,                        -- identifiant RNSR (labos)
    hal_collection  TEXT,                        -- collection HAL (labos)
    laboratory_id   INT REFERENCES laboratories(id),  -- lien vers la table existante (labos uniquement)
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_structures_type ON structures (type);
CREATE INDEX idx_structures_lab_id ON structures (laboratory_id);


-- Relations entre structures
CREATE TABLE structure_relations (
    id              SERIAL PRIMARY KEY,
    parent_id       INT NOT NULL REFERENCES structures(id) ON DELETE CASCADE,
    child_id        INT NOT NULL REFERENCES structures(id) ON DELETE CASCADE,
    relation_type   relation_type NOT NULL,
    UNIQUE (parent_id, child_id, relation_type)
);

CREATE INDEX idx_struct_rel_parent ON structure_relations (parent_id);
CREATE INDEX idx_struct_rel_child ON structure_relations (child_id);


-- Formes de noms pour la détection automatique
CREATE TABLE name_forms (
    id                  SERIAL PRIMARY KEY,
    structure_id        INT NOT NULL REFERENCES structures(id) ON DELETE CASCADE,
    form_text           TEXT NOT NULL,               -- chaîne à chercher
    form_normalized     TEXT NOT NULL,               -- version normalisée (minuscules, sans accents)
    is_regex            BOOLEAN DEFAULT FALSE,       -- TRUE si form_text est une regex (ex: \bIP\b)
    requires_context_of JSONB DEFAULT NULL,          -- NULL = suffisant ; ["tutelles"] ou [14, 27] = contexte requis
    is_active           BOOLEAN DEFAULT TRUE,        -- FALSE = forme désactivée (conservée pour historique)
    notes               TEXT,                        -- commentaire libre
    created_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_name_forms_structure ON name_forms (structure_id);
CREATE INDEX idx_name_forms_active ON name_forms (is_active) WHERE is_active = TRUE;


-- Ajout de structure_id et matched_form_id dans address_laboratories
-- pour tracer quelle structure et quelle forme a provoqué le rattachement
ALTER TABLE address_laboratories
    ADD COLUMN IF NOT EXISTS structure_id INT REFERENCES structures(id) ON DELETE SET NULL;

ALTER TABLE address_laboratories
    ADD COLUMN IF NOT EXISTS matched_form_id INT REFERENCES name_forms(id) ON DELETE SET NULL;


COMMIT;
