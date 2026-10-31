uv run python -m interfaces.cli.oneshot.purge_descriptive_page_locations
uv run python -m interfaces.cli.oneshot.canonicalize_hal_location_urls
uv run python -m interfaces.cli.oneshot.clean_source_record_texts
uv run python -m interfaces.cli.oneshot.backfill_best_copy_urls
uv run python -m interfaces.cli.oneshot.recompute_oa_statuses

# Pipeline
## Extraction
* [ ] Dimensions?; ArXiv, PMC, Pubmed; Sudoc? (liens personnes-thèses plus complets que theses.fr, j'ai l'impression); Cairn, Persée pour augmenter couverture SHS? creuser ISTEX
* [ ] INPI pour les brevets
* [ ] payloads bruts: ne plus faire transiter par la base?
## Suite du traitement
* [ ] normalisation en parallèle de l'extraction?
* [ ] déduplication par métadonnées: ajouter condition journal_id pour les articles? container title pour les chapitres?
* [ ] règles de priorité entre sources pour les métadonnées: assouplir selon les cas de figure (notice OpenAlex ou ScanR dérivées de HAL => HAL doit primer) / annoter un corpus et trouver une bonne fonction de décision
# Données
* [ ] conserver l'historique des structures
* [ ] financements (projets ANR, projets européens)
* [ ] publications fermées, sans localisation éditeur, avec revue OA: chercher des moyens de retrouver les localisations éditeur (URL des revues)
* [ ] OpenAlex: raw affiliation strings qui dérivent de noms de structures HAL: pas de vraies adresses
# UI
## Admin
* [ ] créer des catégories de personnes (personnel UCA, chercheurs associés, anciens doctorants, méga-collab de physique des particules) => et pouvoir configurer la visibilité des groupes dans l'UI publique (beaucoup d'adresses UCA dans les collaborations ALICE/ATLAS sont décalées dans les sources, ce qui pourrit la base avec des milliers de fausses "personnes UCA")
* [ ] fusionner structures
* [ ] bloquer les opérations destructrices côté admin lorsque le pipeline est actif (recenser les actions qui peuvent poser problème)
## Publique
* [ ] page "affiliations divergentes hal": requête incorrecte, capture trop de publis
* [ ] auteur premier, dernier, correspondant: sur les facettes et les stats
* [ ] mesures d'impact à intégrer dans les stats, les dashboards, et les facettes
* [ ] stats en compte fractionnaire vs compte entier?
* [ ] définir des groupes de pays (UE, continents) pour la facette "pays des co-auteurs"
### Visualisation
* [ ] taux de collaboration
* [ ] évolution des collaborations dans le temps (graphes de collaboration par labo, avec visualisation animée par année)
* [ ] visualisation des collab avec carte (monde, Europe, France) qui les localise au niveau de leur ville
* [ ] année en cours: diminuer l'opacité

# Cas particuliers, bizarreries à élucider
* 9705 accès ouvert "via l'éditeur" alors que c'est un DOI Zenodo (+ autre accès Zenodo en dessous)
* 132757 collab Argentine? (il y en a bcp comme ça)
