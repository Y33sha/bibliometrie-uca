-- Migration 055: architecture source-agnostique pour les paramètres d'extraction.
--
-- 1. structures.api_ids (jsonb) : identifiants API par source.
--    Ex: {"openalex": ["i198244214"], "wos": ["Univ Clermont Auvergne"]}
--    Les clés correspondent à l'enum source_type.
--
-- 2. config.api_base_urls : URLs de base des API par source.
--
-- 3. config.hal_portals (renomme hal_portal) : liste de portails HAL.
--
-- 4. config.hal_extra_collections : collections HAL hors structures du périmètre.
--
-- 5. config.perimeter_extraction : périmètre utilisé pour l'extraction.

-- Colonne api_ids sur structures
ALTER TABLE structures ADD COLUMN IF NOT EXISTS api_ids jsonb;

-- Base URLs des API
INSERT INTO config (key, value, description) VALUES
    ('api_base_urls', '{
        "hal": "https://api.archives-ouvertes.fr/search/",
        "openalex": "https://api.openalex.org/works",
        "wos": "https://api.clarivate.com/api/wos",
        "scanr": "https://cluster-production.elasticsearch.dataesr.ovh/scanr-publications/_search",
        "theses": "https://theses.fr/api/v1/theses/recherche/"
    }', 'URLs de base des API par source (clés = enum source_type)')
ON CONFLICT (key) DO NOTHING;

-- Périmètre d'extraction = uca_wide
INSERT INTO config (key, value, description) VALUES
    ('perimeter_extraction', '"uca_wide"', 'Périmètre pour déterminer les structures à interroger lors de l''extraction')
ON CONFLICT (key) DO NOTHING;

-- Renommer hal_portal → hal_portals (scalar → tableau)
UPDATE config SET
    key = 'hal_portals',
    value = '["clermont-univ"]',
    description = 'Portails HAL à interroger (en plus des collections labo)'
WHERE key = 'hal_portal';

-- Collections HAL supplémentaires (hors structures du périmètre)
INSERT INTO config (key, value, description) VALUES
    ('hal_extra_collections', '[]', 'Collections HAL à interroger en plus de celles dérivées des structures du périmètre')
ON CONFLICT (key) DO NOTHING;
