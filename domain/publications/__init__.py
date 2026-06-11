"""Concept métier Publication — value objects, règles, et invariants
de portée (scope).

Sous-modules :
- ``identifiers`` : VOs DOI/HALId/NNT + helpers de normalisation (``clean_doi``, ``normalize_nnt``, ``extract_hal_id_from_url``)
- ``publication`` : aggregate root ``Publication`` + entité fille ``Authorship``
- ``scope`` : doc_types hors périmètre métier aval (matching, table de vérité authorships, listings).
- ``deduplication`` : règles pures de déduplication — identifiants (``DeduplicationKey``) et fusion par métadonnées (``MetadataDeduplicationCase`` + ``detect_metadata_merge_case``)
- ``distinct_publications`` : cas où l'on **ne** fusionne **pas** (ouvrage/chapitre, etc.)
- ``metadata`` : règles sur les métadonnées canoniques (``best_oa_status``, ``clean_publication_title``, ``has_minimal_publication_metadata``)
- ``aggregation`` : agrégation cross-source de l'aggregate (``refresh_from_sources``)
"""
