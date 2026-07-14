"""Services applicatifs autour de l'agrégat Journal.

Sous-modules :
- `core` : briques transaction-agnostiques (find_or_create, update, merge…), réutilisées par le pipeline, les CLI et l'API.
- `commands` : command handlers de l'API (frontière transactionnelle, commit).
"""
