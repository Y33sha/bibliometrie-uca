-- Migration 007 : retire la clé `hal_ref_author` de `config.api_base_urls`.
--
-- L'API auteur HAL (`ref/author`) était interrogée par la phase
-- `harvest_hal_identifiers` pour récupérer ORCID/IdRef. Ces identifiants
-- sont désormais extraits du TEI (`label_xml`) pendant la normalisation,
-- et la phase a été supprimée. L'endpoint n'a plus aucun appelant.

UPDATE config
SET value = value - 'hal_ref_author',
    description = 'URLs de base des API externes : extracteurs (hal/openalex/wos/scanr/theses) + endpoints secondaires (openalex_sources, unpaywall, zenodo)'
WHERE key = 'api_base_urls';
