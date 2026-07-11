"""Concept métier Publication — value objects, règles, et invariants
de portée (scope).

Sous-modules :
- `identifiers` : VOs DOI/HALId/NNT + helpers de normalisation (`clean_doi`, `normalize_nnt`, `extract_hal_id_from_url`)
- `publication` : aggregate root `Publication` + entité fille `Authorship`
- `scope` : doc_types hors périmètre métier aval (matching, table de vérité authorships, listings).
- `reconciliation` : décision pure d'assignation SP → pub-ancre (match/create/skip + merge/split unifiés, `plan_reconciliation`) — applique la primitive d'`entity resolution` (`domain.entity_resolution.connected_components`) aux publications
- `metadata` : règles sur les métadonnées canoniques (`best_oa_status`, `clean_publication_title`, `has_minimal_publication_metadata`)
- `aggregation` : agrégation cross-source de l'aggregate (`refresh_from_sources`)
"""
