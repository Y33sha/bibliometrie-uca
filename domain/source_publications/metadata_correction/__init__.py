"""Règles métier des trois sous-étapes de la phase `metadata_correction`.

La phase persiste sur les `source_publications` les valeurs corrigées, pour que le matching et l'agrégation aval lisent des colonnes déjà corrigées ; `refresh_from_sources` rejoue les règles applicables sur la publication canonique. Distincte de l'agrégation (`aggregation.py` arbitre entre sources) et du normalizer (qui préserve les `source_publications` comme trace inviolable des sources).

Trois sous-étapes, un module chacune :

- `rules` — correction unaire : reclasse le type de document et corrige le statut d'accès ouvert d'un enregistrement d'après ses propres champs, par une table de règles.
- `shared_doi` — correction du DOI d'un groupe d'enregistrements portant un même DOI (convergence vers l'œuvre canonique, ou nullage d'un DOI recopié à tort).
- `journal_by_doi` — rattachement d'une revue à un enregistrement via le préfixe de son DOI.

La provenance de chaque correction est tracée par le caller : une `source_publication` la stashe dans `raw_metadata.<champ>.corrected_by` avec la valeur brute écrasée (réversibilité) ; une publication canonique l'inscrit dans `meta.corrections.<champ>` (provenance seule, recalculée à chaque refresh).
"""
