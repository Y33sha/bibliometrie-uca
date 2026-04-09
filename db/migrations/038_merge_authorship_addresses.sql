-- Migration : fusion des 3 tables *_authorship_addresses en source_authorship_addresses
-- Les données seront reconstruites par le pipeline (populate_addresses.py)

BEGIN;

DROP TABLE IF EXISTS openalex_authorship_addresses CASCADE;
DROP TABLE IF EXISTS wos_authorship_addresses CASCADE;
DROP TABLE IF EXISTS scanr_authorship_addresses CASCADE;

CREATE TABLE source_authorship_addresses (
    id                      SERIAL PRIMARY KEY,
    source_authorship_id    INTEGER NOT NULL REFERENCES source_authorships(id) ON DELETE CASCADE,
    address_id              INTEGER NOT NULL REFERENCES addresses(id) ON DELETE CASCADE,
    UNIQUE (source_authorship_id, address_id)
);

CREATE INDEX idx_saa_authorship ON source_authorship_addresses (source_authorship_id);
CREATE INDEX idx_saa_address ON source_authorship_addresses (address_id);

COMMIT;
