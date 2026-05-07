"""Concept métier Publication — value objects, règles, et invariants
de portée (scope).

Sous-modules :
- ``scope`` : doc_types hors périmètre métier aval (matching, table de
  vérité authorships, listings).

Note : ``domain/publication.py`` (singulier, à la racine de domain/)
contient encore les VOs DOI/HALId/NNT, ``clean_doi``, ``best_oa_status``,
``resolve_doi_conflict``, etc. Migration vers le présent dossier prévue
dans un chantier dédié (cf. décision n°1 de
``docs/chantiers/regles-metier-domain.md``).
"""
