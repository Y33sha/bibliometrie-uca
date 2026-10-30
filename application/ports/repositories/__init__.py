"""Ports des repositories : écritures sur les données, et lectures qui les accompagnent.

Le mot « repository » couvre deux natures. `Person`, `Structure`, `Serial`, `Publisher` et `Perimeter` chargent et persistent une entité du domaine (`find_by_id -> Entity`, `save`). Les autres écrivent des lignes de table, sans entité du domaine. Implémentés dans `infrastructure/repositories/`.
"""
