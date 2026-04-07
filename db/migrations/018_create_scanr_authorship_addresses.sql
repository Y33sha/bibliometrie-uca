-- Table de liens scanr_authorships ↔ addresses
CREATE TABLE IF NOT EXISTS scanr_authorship_addresses (
    id                    SERIAL PRIMARY KEY,
    scanr_authorship_id   INTEGER NOT NULL REFERENCES scanr_authorships(id) ON DELETE CASCADE,
    address_id            INTEGER NOT NULL REFERENCES addresses(id) ON DELETE CASCADE,
    UNIQUE (scanr_authorship_id, address_id)
);

CREATE INDEX IF NOT EXISTS idx_saa_address ON scanr_authorship_addresses (address_id);
