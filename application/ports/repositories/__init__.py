"""Ports des repositories : l'accès aux données des ressources persistées — écritures, et lectures d'appoint.

Deux natures sous le même mot « repository ». `Publication`, `Person`, `Structure`, `Journal`, `Publisher` et `Perimeter` chargent et persistent un agrégat du domaine (`find_by_id -> Entity`, `save`). `Authorship`, `Address`, `Config`, `AuditLog` et `DoiPrefix` font du CRUD de table ou de l'append, sans racine hydratée. Implémentés dans `infrastructure/repositories/`.
"""
