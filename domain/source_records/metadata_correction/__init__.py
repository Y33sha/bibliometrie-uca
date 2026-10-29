"""Règles de la phase `metadata_correction`, qui écrit les valeurs corrigées dans `source_records` : le matching et l'agrégation lisent ainsi des colonnes corrigées. `refresh_from_sources` rejoue les règles applicables sur la publication.

- `rules` : type de document et statut open access d'un enregistrement source, d'après ses propres champs.
- `shared_doi` : DOI partagé par plusieurs enregistrements sources.
- `serial_by_doi` : revue d'un enregistrement source, d'après l'espace de noms de son DOI.

Chaque correction garde la valeur d'avant correction dans la colonne `corrections`, de `source_records` comme de `publications`.
"""
