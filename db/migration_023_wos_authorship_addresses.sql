-- Migration 023 : Table de liaison wos_authorships ↔ addresses
-- Même architecture que openalex_authorship_addresses.

BEGIN;

CREATE TABLE IF NOT EXISTS wos_authorship_addresses (
    id                  SERIAL PRIMARY KEY,
    wos_authorship_id   INT NOT NULL REFERENCES wos_authorships(id) ON DELETE CASCADE,
    address_id          INT NOT NULL REFERENCES addresses(id) ON DELETE CASCADE,
    UNIQUE (wos_authorship_id, address_id)
);

CREATE INDEX IF NOT EXISTS idx_wos_aa_authorship ON wos_authorship_addresses(wos_authorship_id);
CREATE INDEX IF NOT EXISTS idx_wos_aa_address ON wos_authorship_addresses(address_id);

COMMIT;
