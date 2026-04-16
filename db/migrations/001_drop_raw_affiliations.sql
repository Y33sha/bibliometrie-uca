-- Migration 001 : supprimer raw_affiliations et addresses_extracted
-- Les adresses sont désormais créées pendant la normalisation
-- et stockées dans addresses + source_authorship_addresses.

ALTER TABLE source_authorships DROP COLUMN IF EXISTS raw_affiliations;
ALTER TABLE source_authorships DROP COLUMN IF EXISTS addresses_extracted;

-- Supprimer le trigger et la fonction associés
DROP TRIGGER IF EXISTS trg_reset_addresses_extracted ON source_authorship_addresses;
DROP FUNCTION IF EXISTS reset_addresses_extracted();
