"""Services applicatifs autour de l'agrégat Person (référentiel Personnes).

Sous-modules :
- `core` : briques transaction-agnostiques (création, identifiants, formes de
  noms, rattachement d'authorships, fusion…), réutilisées par le pipeline, les
  CLI et l'API.
- `commands` : command handlers de l'API (frontière transactionnelle, commit).
"""
