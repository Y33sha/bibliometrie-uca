python interfaces/cli/oneshot/fill_source_record_identifiers.py

# Pipeline
* [ ] bloquer les opérations destructrices côté admin lorsque le pipeline est actif (recenser les actions qui peuvent poser problème)
## Extraction
* [ ] Dimensions?; ArXiv, PMC, Pubmed; Sudoc? (liens personnes-thèses plus complets que theses.fr, j'ai l'impression); Cairn, Persée pour augmenter couverture SHS?
* [ ] payloads bruts: ne plus faire transiter par la base?
## Suite du traitement
* [ ] normalisation en parallèle de l'extraction?
* [ ] déduplication par métadonnées: ajouter condition journal_id pour les articles? container title pour les chapitres?
* [ ] rendre la résolution des personnes totalement indépendante de l’ordre d'arrivée + remettre en jeu les résolutions non épinglées
* [ ] règles de priorité entre sources pour les métadonnées: assouplir selon les cas de figure (notice OpenAlex ou ScanR dérivées de HAL => HAL doit primer) / annoter un corpus et trouver une bonne fonction de décision

# Données
* [ ] gérer les adresses résultant d'une erreur de parsing (ex. publi 106296); quand un work openalex a les mêmes affiliations pour toutes les contributions => suspect (contrôler par les autres sources)
* [ ] conserver l'historique des structures
* [ ] financements (projets ANR, projets européens)
# UI
## Admin
* [ ] créer des catégories de personnes (personnel UCA, chercheurs associés, anciens doctorants, méga-collab de physique des particules) => et pouvoir configurer la visibilité des groupes dans l'UI publique (beaucoup d'adresses UCA dans les collaborations ALICE/ATLAS sont décalées dans les sources, ce qui pourrit la base avec des milliers de fausses "personnes UCA")
* [ ] fusionner structures
## Publique
* [ ] page "affiliations suspectes hal": requête incorrecte, capture trop de publis
* [ ] Filtres supplémentaires possibles: `has_doi` (crossref, datacite, other, none); repositories?
* [ ] auteur premier, dernier, correspondant: sur les facettes et les stats
* [ ] mesures d'impact à intégrer dans les stats, les dashboards, et les facettes
* [ ] évolution des collaborations dans le temps (graphes de collaboration par labo, avec visualisation animée par année)
* [ ] visualisation des collab avec carte (monde, Europe, France) qui les localise au niveau de leur ville
* [ ] stats en compte fractionnaire vs compte entier
* [ ] mettre en place des slugs pour les URL?
* [ ] définir des groupes de pays (UE, continents) pour la facette "pays des co-auteurs"
* [ ] icônes des licences

# Cas particuliers, bizarreries à élucider
