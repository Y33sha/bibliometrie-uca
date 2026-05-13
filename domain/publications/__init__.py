"""Concept métier Publication — value objects, règles, et invariants
de portée (scope).

Sous-modules :
- ``identifiers`` : VOs DOI/HALId/NNT + helpers de normalisation
- ``scope`` : doc_types hors périmètre métier aval (matching, table de
  vérité authorships, listings).
- ``dedup`` : invariants de déduplication (metadata minimales).

Note : ``domain/publication.py`` (singulier, à la racine de domain/)
reste en place comme façade transitoire ré-exportant les VOs
d'identifiants, et héberge encore les règles métier
(``best_oa_status``, ``resolve_doi_conflict``, ``clean_publication_title``)
ainsi que les projections de lecture (``PubByDoi``, ``PubByNnt``, …).
Cf. chantier ``CODE_rich-domain-model``.
"""
