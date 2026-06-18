"""Logique métier et projections de lecture côté `source_publications`.

Une `source_publications` est l'image d'un document dans une source externe
(HAL, OpenAlex, WoS, theses.fr, ScanR, …), agrégée plus tard dans la
`Publication` canonique. Ce package n'expose pas d'agrégat mutable : les
source_publications sont des entrées en lecture seule du pipeline.

Sous-modules :
- ``views`` : projections de lecture (``SourcePublicationWithJournalView``)
- ``keys`` : projection des clés de confirmation (dédup)
- ``correction`` : règles de correction des métadonnées
- ``doc_types`` : mapping des types de document source → vocabulaire canonique
- ``raw_metadata`` : accès aux métadonnées brutes
"""
