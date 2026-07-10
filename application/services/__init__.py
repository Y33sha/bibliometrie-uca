"""Services applicatifs, un package par agrégat du domaine.

Chaque agrégat expose `core.py` (briques d'écriture transaction-agnostiques,
réutilisées par le pipeline, les CLI et l'API) et, quand l'API écrit sur
l'agrégat, `commands.py` (command handlers portant la frontière transactionnelle).
"""
