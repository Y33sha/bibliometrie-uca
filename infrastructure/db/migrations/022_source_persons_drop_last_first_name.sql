-- Migration 022 : retire les colonnes `last_name` et `first_name` de `source_persons`.
--
-- Cf. chantier docs/chantiers/regles-metier-domain.md. Les noms des
-- auteurs côté source sont désormais lus uniquement depuis
-- `source_authorships.raw_author_name` et parsés à la lecture via
-- `domain.names.parse_raw_author_name` (qui gère « Nom, Prénom »
-- comme « Prénom Nom »). Cela supprime l'asymétrie historique entre
-- sources structurées (HAL/ScanR/theses qui peuplaient ces colonnes)
-- et sources non structurées (OpenAlex/WoS/Crossref qui parsaient déjà
-- à la lecture).

ALTER TABLE source_persons
    DROP COLUMN last_name,
    DROP COLUMN first_name;
