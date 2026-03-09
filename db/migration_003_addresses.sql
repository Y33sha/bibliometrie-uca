-- Migration 003: table des adresses et résolution des affiliations
-- Usage: psql -d publisher-stats -f migration_003_addresses.sql

BEGIN;

-- ═══════════════════════════════════════════════════════════
-- Table des adresses distinctes (chaînes brutes individuelles)
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS addresses (
    id                  SERIAL PRIMARY KEY,
    raw_text            TEXT NOT NULL UNIQUE,
    raw_text_normalized TEXT NOT NULL,
    is_uca              BOOLEAN DEFAULT NULL,   -- NULL = non résolu
    resolved_at         TIMESTAMPTZ DEFAULT NULL,
    created_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_addresses_normalized
    ON addresses (raw_text_normalized);
CREATE INDEX IF NOT EXISTS idx_addresses_unresolved
    ON addresses (id) WHERE is_uca IS NULL;

-- ═══════════════════════════════════════════════════════════
-- Pivot adresse → structure (labo UCA, ou UCA sans labo)
-- Une adresse peut être affiliée à plusieurs labos (rare mais possible)
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS address_laboratories (
    id              SERIAL PRIMARY KEY,
    address_id      INT NOT NULL REFERENCES addresses(id) ON DELETE CASCADE,
    laboratory_id   INT REFERENCES laboratories(id),  -- NULL = UCA détectée mais pas de labo identifié
    source          TEXT NOT NULL DEFAULT 'auto',      -- 'auto', 'manual', 'openalex', 'wos'
    is_valid        BOOLEAN DEFAULT TRUE,              -- FALSE = faux positif confirmé
    confidence      FLOAT DEFAULT 1.0,
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (address_id, laboratory_id)
);

CREATE INDEX IF NOT EXISTS idx_addr_lab_address
    ON address_laboratories (address_id);
CREATE INDEX IF NOT EXISTS idx_addr_lab_lab
    ON address_laboratories (laboratory_id);

-- ═══════════════════════════════════════════════════════════
-- Lien publication_authors → addresses (many-to-many)
-- Un auteur sur une publi peut avoir plusieurs adresses
-- ═══════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS publication_author_addresses (
    id                      SERIAL PRIMARY KEY,
    publication_author_id   INT NOT NULL REFERENCES publication_authors(id) ON DELETE CASCADE,
    address_id              INT NOT NULL REFERENCES addresses(id) ON DELETE CASCADE,
    UNIQUE (publication_author_id, address_id)
);

CREATE INDEX IF NOT EXISTS idx_paa_pubauthor
    ON publication_author_addresses (publication_author_id);
CREATE INDEX IF NOT EXISTS idx_paa_address
    ON publication_author_addresses (address_id);

COMMIT;
