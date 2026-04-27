-- Migration 009 : ajouter 'crossref' à l'enum source_type.
--
-- CrossRef devient une nouvelle source bibliographique, alimentant
-- source_publications / source_authorships / source_persons via son API
-- REST. Trois rôles complémentaires (cf docs/chantiers/crossref.md) :
--   - arbitrage des métadonnées canoniques (doc_type, journal, dates,
--     license, funders) avec priorité sur HAL/OA/WoS
--   - confirmation d'identité auteur via ORCID article-level (déposé
--     par l'éditeur, plus fiable qu'OpenAlex algorithmique)
--   - relations entre publications (preprint, version, has-dataset...)
--
-- L'ordre de la valeur dans l'enum suit la convention chronologique
-- d'intégration des sources (hal → openalex → wos → scanr → theses
-- → crossref). L'ordre métier de priorité vit dans
-- domain/sources.py::SOURCE_PRIORITY (2e position derrière theses).

ALTER TYPE public.source_type ADD VALUE IF NOT EXISTS 'crossref';
