"""Ports des repositories : l'accès aux données des ressources persistées — écritures, et lectures d'appoint.

Protocols pour `Publication`, `Person`, `Structure`, `Authorship`, `Journal`, `Publisher`, `Address`, `Perimeter`, `AuditLog`, `Config`, `DoiPrefix`. Certains chargent et persistent un agrégat du domaine (`find_by_id -> Entity`, `save`) ; d'autres ne font que du CRUD de table ou de l'append. Le nom « repository » couvre les deux. Implémentés dans `infrastructure/repositories/`.

Le placement dans `application/ports/` (et non `domain/ports/`) reflète le fait que les ports décrivent une frontière d'I/O — typique de la couche application en hexagonal / DDD pragmatique (cf. Cosmic Python). Le domaine reste strictement pur (entités, value objects, règles métier).

L'arborescence interne (`repositories/` vs ports de query services côté `api/`, `pipeline/`) sert à grouper par nature ; ce n'est pas porteur de règle d'import.
"""
