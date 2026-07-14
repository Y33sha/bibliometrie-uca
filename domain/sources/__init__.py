"""Concept métier Source bibliographique — registre et règles par source.

Sous-modules :
- `registry` : registre des sources (liste, sets, ordres de priorité) — source unique de vérité côté Python.
- règles métier source-spécifiques (interprétation des schémas par source) :
  `crossref`, `datacite`, `scanr`, `wos`, `theses`, `hal`,
  `openalex`, `hal_domains`. Ex : `domain.sources.scanr.derive_scanr_oa_status`.
"""
