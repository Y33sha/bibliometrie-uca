"""Entité `SourceRecord` et logique métier associée.

Un `SourceRecord` est l'image d'un document dans une source externe (HAL, OpenAlex, WoS, theses.fr, ScanR, …), agrégé plus tard dans la `Publication` du référentiel. Entité de lecture : clés `(source, source_id)` et `id`, immuable et utilisée en lecture seule ; jamais persistée via cet objet (les écritures passent par le SQL).

Sous-modules :
- `source_record` : l'entité `SourceRecord`
- `keys` : projection des clés de confirmation (dédup)
- `correction` : règles de correction des métadonnées
- `doc_types` : mapping des types de document source → vocabulaire canonique
- `languages` : langue donnée par la source → code du référentiel des langues
- `raw_metadata` : accès aux métadonnées brutes
"""
