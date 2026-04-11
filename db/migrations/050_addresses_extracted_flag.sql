-- Flag pour eviter de retraiter les source_authorships dont les adresses
-- ont deja ete extraites et liees via source_authorship_addresses.

ALTER TABLE source_authorships ADD COLUMN IF NOT EXISTS addresses_extracted BOOLEAN NOT NULL DEFAULT FALSE;

-- Trigger : quand un lien source_authorship_addresses est supprime,
-- remettre le flag a FALSE sur l'authorship correspondante.
CREATE OR REPLACE FUNCTION reset_addresses_extracted()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE source_authorships SET addresses_extracted = FALSE
    WHERE id = OLD.source_authorship_id;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_reset_addresses_extracted ON source_authorship_addresses;
CREATE TRIGGER trg_reset_addresses_extracted
    AFTER DELETE ON source_authorship_addresses
    FOR EACH ROW
    EXECUTE FUNCTION reset_addresses_extracted();

-- Marquer comme extraites les authorships qui ont deja des liens
UPDATE source_authorships SET addresses_extracted = TRUE
WHERE EXISTS (
    SELECT 1 FROM source_authorship_addresses saa
    WHERE saa.source_authorship_id = source_authorships.id
);
