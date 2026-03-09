-- Migration 004: review_status sur addresses
-- Usage: psql -d publisher-stats -f migration_004_address_review.sql

BEGIN;

ALTER TABLE addresses
    ADD COLUMN IF NOT EXISTS review_status TEXT DEFAULT NULL;
    -- NULL = pas examiné, 'false_positive', 'valid'

CREATE INDEX IF NOT EXISTS idx_addresses_review
    ON addresses (review_status) WHERE is_uca = TRUE;

COMMIT;
