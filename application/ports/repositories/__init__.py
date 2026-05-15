"""Ports des repositories (agrégats du domaine).

Protocols qui décrivent la persistance des agrégats `Publication`,
`Person`, `Structure`, `Authorship`, `Journal`, `Publisher`, `Address`,
`Perimeter`, `AuditLog`. Implémentés dans `infrastructure/repositories/`.

Le placement dans `application/ports/` (et non `domain/ports/`) reflète
le fait que les ports décrivent une **frontière d'I/O** — typique de la
couche application en hexagonal/DDD pragmatique (cf. Cosmic Python). Le
domaine reste strictement pur (entités, value objects, règles métier).

L'arborescence interne (`repositories/` vs ports de query services côté
`api/`, `pipeline/`) sert juste à grouper visuellement par nature ; ce
n'est pas porteur de règle d'import.
"""
