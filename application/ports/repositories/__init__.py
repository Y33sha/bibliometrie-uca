"""Ports des repositories : l'accès aux données des ressources persistées — écritures, et lectures d'appoint.

Deux natures sous le même mot « repository ». `Person`, `Structure`, `Serial`, `Publisher` et `Perimeter` chargent et persistent un agrégat du domaine (`find_by_id -> Entity`, `save`). `Contribution`, `Address`, `Config` et `Audit` écrivent des lignes de table, sans agrégat. Implémentés dans `infrastructure/repositories/`.
"""
