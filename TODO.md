# Pipeline
## Extraction
### Couverture
* [ ] extraction par ORCID: vérifier pertinence (tester différentes sources, auditer le gain)
* [ ] bioRxiv, medRxiv: identifiants différents de arxiv? cf publi 2757 (voir si on moissonne ces identifiants; possibilité de récupérer les DOI à partir des identifiants comme dans ArXiv)
* [ ] chercher dans ScanR par hal-id? (généraliser cross-import à tous les identifiants et toutes les sources)
### Performance
* [ ] à étudier: cross-import: seulement `in_perimeter`? (ie seulement au run n+1) => éviter de cross-importer des trucs rejetés pendant la phase affiliations
* [ ] analyser les diff de payload pour voir si on peut diminuer le nombre d'UPSERT en filtrant les champs importés
## Suite du traitement
* [ ] `publishers_journals`: paralléliser crossref/datacite
* [ ] vérifier qu'il ne manque pas des `ANALYZE` en cours de pipeline pour éviter un *seq scan* sur des millions de lignes lors d'un premier run depuis une base vide.
### Correction
* [ ] vérifier comment DOC_TYPE_MAP interagit avec les autres règles de correction du `doc_type`
* [ ] créer circuit pour correction automatisée du `journal_type` (titre terminé par ` eBooks` => plateforme d'ebooks)
* [ ] `metadata_correction`: en cas de corrections de champs multiples sur un même doc, les règles s'appliquent indépendamment à partir du brut; étudier les scénarios de corrections multiples où l'output d'une règle pourrait intersecter l'input des suivantes, voir s'il est pertinent de les chaîner ensemble
* [ ] `persons`: voir si on peut généraliser le matching par identifiants forts aux authorships hors périmètre (à réserver aux identifiants `confirmed`)

# Données
* [ ] détection d'incohérences `doi_prefix`/`publisher_id`/`journal_id`: auditer d'abord, classifier les cas de divergence selon leur cause
## Problèmes dans les sources
* [ ] DUMAS: comment distinguer mémoires et thèses d'exercice?
* [ ] noms de containers OpenAlex aberrants ("SPIRE - Sciences Po Institutional REpository") => faire quelque chose
## Explorer autres sources possibles
* [ ] Dimensions; ArXiv, PMC, Pubmed; Sudoc? (liens personnes-thèses plus complets que theses.fr, j'ai l'impression); Cairn, Persée pour augmenter couverture SHS?
* [ ] OpenAPC: j'ai utilisé les données sur les APC UCA, mais il faudrait partir du dump complet et matcher tous les DOI des publis UCA pour voir quels établissements ont payé les APC quand ce n'est pas l'UCA

# UI
## Admin
* [ ] Clarifier la section "périmètres" (grouper affiliation/publications; séparer persons + UI)
* [ ] fusion / dé-fusion manuelle de publications: circuit à créer (interface de gestion du référentiel de publications, sur le modèle de admin/persons; avec requêtes pour repérer doublons probables et fusions suspectes; supprimer `admin/duplicates` et `admin/person-duplicates`)
* [ ] signaler visuellement les structures qui ne font partie d'aucun périmètre (pages liste et détail), ajouter filtre périmètre dans la page liste
* [ ] page persons: le nombre de publications liées à une forme de nom ne se met pas à jour dans le drawer quand on les détache de l'auteur
* [ ] créer des catégories de personnes (personnel UCA, chercheurs associés, anciens doctorants, méga-collab de physique des particules) => et pouvoir configurer la visibilité des groupes dans l'UI publique (beaucoup d'adresses UCA dans les collaborations ALICE/ATLAS sont décalées dans les sources, ce qui pourrit la base avec des milliers de fausses "personnes UCA")
## Publique
* [ ] page "affiliations suspectes hal": requête incorrecte, capture trop de publis + problème de perf
* [ ] Filtres supplémentaires possibles: langue; `has_doi` (crossref, datacite, other, none); `corresponding_is_in_perimeter`; `peer_reviewed`? (suppose de posséder la donnée ou de pouvoir la déduire des sources); licence
* [ ] premier/dernier auteur (sur l'onglet publications de la page personne)
* [ ] colonne éditeur; filtres éditeur + revue?
* [ ] thèses d'autres établissements liés à nos labos: enlever de la page thèses (ajouter filtre implicite sur "établissement de soutenance" / ou le faire en amont dès le pipeline?)
* [ ] onglet thèses: les noms d'auteur apparaissent bruts (certains en capitales)
* [ ] page structures: filtrer par tutelle, par Institut (intégrer les instituts)

# Cas particuliers, bizarreries à élucider
* [ ] 164107: pourquoi type autre?
* [ ] 165068 type "commmentary"; 86931 type "meeting report" => comment prendre en compte ces types (et empêcher openalex d'imposer le type article); réfléchir au type "report"
* [ ] 30172 un recueil de proceedings fusionné avec tous ses chapitres
* [ ] 182637 et 182636: vérifier si DataCite indique relation
* [ ] règle à créer: si DOI de forme ISBN + _n => conference_paper ou chapitre / si forme ISBN: proceedings ou book
* [ ] 107270 et 869915 Computing Pivot-Minors: un article faussement typé preprint par openalex; + question des arxiv_id (déduire le DOI et vice-versa)
* [ ] faux preprints: retyper en fonction du DOI (theConversation => media)
* [ ] problème sur l'ouverture des thèses: 132576
* [ ] recensions: "Comptes rendus :", "Compte rendu :"; type = article + titre contient "(dir.)"

# Idées pour plus tard, éventuellement
* stats en compte fractionnaire vs compte entier
* collaborations nationales et internationales: identification des structures partenaires; évolution des collaborations dans le temps (graphes de collaboration par labo, avec visualisation animée par année)
* mesures d'impact
* définir des groupes de pays (UE, continents) pour la facette "pays des co-auteurs"
* règles de correction de métadonnées et règles de déduplication de publications: actuellement logées dans le code; possibilité de les stocker en base et de les rendre configurables via l'UI?
* audit trail: uniformiser les types d'action qui génèrent un log ou pas + interface pour les consulter
* rendre les extracteurs interruptibles avec ctrl+C sous Windows
* mettre en place des slugs pour les URL?

# Pas nécessaire de le régler, du moment qu'on le documente quelque part
* [ ] re-tester le circuit des imports RH => pas urgent, pas d'imports csv à terme en prod

# Qualité / Doc
* [ ] Audit complet "nommage des variables/fonctions/classes/méthodes/tables/colonnes". S'assurer que le code est structure-agnostique. Supprimer abréviations cryptiques. Revoir certains noms trop restrictifs (publication->document? journal->container?)
* [ ] Audit complet "documentation/docstrings/commentaires". S'assurer que tout est à jour et non-jargonneux.
* [ ] Documenter la duplication de données (vues matérialisées, tables et colonnes dérivées) et leur cycle de vie + quantifier poids vs gain de performance en lecture
* [ ] Documenter les process incrémentaux (flag `dirty`) vs recalcul complet, et les arbitrages entre gain de temps et risque de drift; chaque process incrémental doit avoir un mode `--full-rebuild`
