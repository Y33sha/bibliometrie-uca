-- Remplacer la contrainte UNIQUE sur addresses.raw_text (btree, limité à 2704 octets)
-- par un index UNIQUE sur le hash MD5 (supporte les textes de toute taille)

BEGIN;

ALTER TABLE addresses DROP CONSTRAINT IF EXISTS addresses_raw_text_key;
DROP INDEX IF EXISTS addresses_raw_text_key;

CREATE UNIQUE INDEX addresses_raw_text_key ON addresses (md5(raw_text));

COMMIT;
