"""Ports des repositories : l'accès aux données des ressources persistées — écritures, et lectures d'appoint.

Protocols pour `Publication`, `Person`, `Structure`, `Authorship`, `Journal`, `Publisher`, `Address`, `Perimeter`, `AuditLog`, `Config`, `DoiPrefix`. Certains chargent et persistent un agrégat du domaine (`find_by_id -> Entity`, `save`) ; d'autres ne font que du CRUD de table ou de l'append. Le nom « repository » couvre les deux. Implémentés dans `infrastructure/repositories/`.
"""
