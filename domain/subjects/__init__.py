"""Concept métier Sujet : libellés agrégés depuis les sources.

Un sujet est un libellé observé sur des publications, dédupliqué sur `lower(label)`. La provenance (quelle source l'a annoté) vit sur `publication_subjects.source`.

Sous-modules :
- `subject` : helper de normalisation des libellés.
"""
