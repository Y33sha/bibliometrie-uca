"""Services applicatifs autour de l'agrégat Person (référentiel Personnes).

Sous-modules :
- `core` : briques transaction-agnostiques (exclusion, renommage, identifiants, formes de noms, rattachement de contributions, fusion…), réutilisées par le pipeline, les CLI et l'API.
- `commands` : command handlers de l'API (frontière transactionnelle, commit).
"""
