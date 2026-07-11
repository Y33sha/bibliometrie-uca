"""Services applicatifs autour de l'agrégat Publication.

Sous-modules :
- `core` : briques transaction-agnostiques (refresh canonique depuis les
  sources, fusion, marquage distinct…), réutilisées par le pipeline, les CLI et
  l'API.
- `commands` : command handlers de l'API (frontière transactionnelle, commit).
"""
