"""Règles métier des trois sous-étapes de la phase `metadata_correction`.

La phase persiste sur les `source_records` les valeurs corrigées, pour que le matching et l'agrégation aval lisent des colonnes déjà corrigées ; `refresh_from_sources` rejoue les règles applicables sur la publication canonique. Distincte de l'agrégation (`aggregation.py` arbitre entre sources) et du normalizer (qui préserve les `source_records` comme trace inviolable des sources).

Trois sous-étapes, un module chacune :

- `rules` — correction unaire : reclasse le type de document et corrige le statut d'accès ouvert d'un enregistrement d'après ses propres champs, par une table de règles.
- `shared_doi` — correction du DOI d'un groupe d'enregistrements portant un même DOI (convergence vers l'œuvre canonique, ou nullage d'un DOI recopié à tort).
- `serial_by_doi` — rattachement d'une revue à un enregistrement via l'espace de noms de son DOI.

La provenance de chaque correction est tracée par le caller dans la colonne `corrections` de `source_records` ou de `publications`, avec la valeur d'avant correction. Celle d'une publication est recalculée à chaque refresh.
"""
