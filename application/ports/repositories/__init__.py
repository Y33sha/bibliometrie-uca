"""Ports des repositories : écritures sur les données, et lectures qui les accompagnent.

Le mot « repository » couvre deux natures. `Person`, `Structure`, `Serial`, `Publisher` et `Perimeter` chargent et persistent un agrégat du domaine (`find_by_id -> Entity`, `save`). `Contribution`, `Address`, `Config` et `Audit` écrivent des lignes de table, sans agrégat. Implémentés dans `infrastructure/repositories/`.
"""
