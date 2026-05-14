"""Concept métier Publication — value objects, règles, et invariants
de portée (scope).

Sous-modules :
- ``identifiers`` : VOs DOI/HALId/NNT + helpers de normalisation
- ``publication`` : aggregate root ``Publication`` + entité fille
  ``Authorship``
- ``scope`` : doc_types hors périmètre métier aval (matching, table de
  vérité authorships, listings).
- ``deduplication`` : règles pures de matching et de résolution de conflit DOI (cascade `decide_publication_match`, attribution tardive `decide_doi_attribution`, conflit chapter/book `resolve_doi_conflict`).

Note : ``domain/publication.py`` (singulier, à la racine de domain/)
reste en place comme façade ré-exportant les VOs d'identifiants, et
héberge encore les règles métier (``best_oa_status``,
``resolve_doi_conflict``, ``clean_publication_title``) ainsi que les
projections de lecture (``PubByDoi``, ``PubByNnt``, …).
"""
