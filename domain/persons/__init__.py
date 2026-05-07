"""Concept métier Personne — value objects, modèles JSONB, et règles
d'entité.

Sous-modules :
- ``identifiers`` : VOs ORCID/IdHAL/IdRef + helpers de normalisation
- ``source_ids`` : modèle Pydantic de la colonne JSONB
  ``source_persons.source_ids``
- ``merge`` : invariants de fusion entre personnes (extensible aux
  règles de déduplication / création quand on les rapatriera)
"""
