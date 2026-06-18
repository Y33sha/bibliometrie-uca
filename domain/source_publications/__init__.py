"""Entité `SourcePublication` et logique métier associée.

Une `SourcePublication` est l'image d'un document dans une source externe
(HAL, OpenAlex, WoS, theses.fr, ScanR, …), agrégée plus tard dans la
`Publication` canonique. Entité de lecture : identité `(source, source_id)` /
`id`, immuable et utilisée en lecture seule ; jamais persistée via cet objet
(les écritures passent par le SQL).

Sous-modules :
- ``source_publication`` : l'entité ``SourcePublication``
- ``keys`` : projection des clés de confirmation (dédup)
- ``correction`` : règles de correction des métadonnées
- ``doc_types`` : mapping des types de document source → vocabulaire canonique
- ``raw_metadata`` : accès aux métadonnées brutes
"""
