-- Migration 020 : index trigram sur addresses.normalized_text.
--
-- `interfaces/cli/suggest_address_countries.py` cherche, pour chaque
-- adresse sans pays, les adresses avec pays dont le `normalized_text`
-- la contient comme sous-chaîne (`LIKE '%X%'`). Sans index, c'est un
-- seq scan séparé pour chaque cible — soit ~8k cibles × ~400k pool =
-- plusieurs milliards de comparaisons substring.
--
-- L'index gin_trgm_ops permet à PostgreSQL d'utiliser le trigramme
-- pour pré-filtrer le pool avant le LIKE final, et autorise une
-- réécriture en UPDATE bulk SQL (un seul JOIN au lieu d'une boucle
-- Python avec round-trip par adresse).

CREATE INDEX idx_addresses_normalized_text_trgm
    ON addresses USING gin (normalized_text public.gin_trgm_ops);
