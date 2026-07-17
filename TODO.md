# Pipeline
## Extraction
* [ ] ajouter extraction par ORCID: vérifier pertinence (tester différentes sources, auditer le gain)
* [ ] bioRxiv, medRxiv: identifiants différents de arxiv? cf publi 2757 (voir si on moissonne ces identifiants; possibilité de récupérer les DOI à partir des identifiants comme dans ArXiv)
* [ ] chercher dans ScanR par hal-id? (généraliser cross-import à tous les identifiants et toutes les sources; ajouter système de backoff)
* [ ] cross_import: max 10k par source par run? (pour lisser dans le temps)
## Suite du traitement
* [ ] CLI `seed_journals_doi_prefix`: intégrer au pipeline? + recalculer les anciens pour tenir compte des nouveaux (chaque doi_prefix de journal doit être unique et aussi précis que possible; à cette occasion, réécrire la fonction resolve_journal_by_doi de manière moins alambiquée)
* [ ] tester la nouvelle logique de matching personnes: faire une copie de la base, vider les `persons`, `person_name_forms` et `person_identifiers`, relancer le pipeline, comparer le résultat à la base canonique; étudier le diff, retravailler la logique, itérer jusqu'à convergence.
* [ ] réévaluer l'utilité du flag in_perimeter sur la table publications
* [ ] suggested countries: jamais remis à null
* [ ] arrêter d'utiliser hal_person_id pour matching: remplacer par idhal / ou rendre hal_person_id visible et confirmable/rejetable via UI admin?

# Données
* [ ] distinguer conference_paper et conférence (présence d'un journal_id?)
* [ ] DUMAS: comment distinguer mémoires et thèses d'exercice?
* publi 106296: gérer les adresses résultant d'une erreur de parsing (à quel niveau: exclure adresses? exclure source_authorships? - gestion manuelle, détection automatisée)
## Corrections
* [ ] détection d'incohérences `doi_prefix`/`publisher_id`/`journal_id`: auditer d'abord, classifier les cas de divergence selon leur cause
* [ ] créer circuit pour correction automatisée du `journal_type` (titre terminé par ` eBooks` => plateforme d'ebooks; titre contenant `International Conference` ou `International Symposium` => proceedings)
* [ ] typage data_paper automatisé par journal (ex. *Scientific Data*; créer un journal_type dédié?); chercher aussi "dataset" dans les titres
* [ ] règle à créer: si DOI de forme ISBN + _n => conference_paper ou chapitre / si forme ISBN: proceedings ou book (trancher selon type du "journal")
* [ ] noms de containers OpenAlex aberrants ("SPIRE - Sciences Po Institutional REpository") => faire quelque chose; quelle valeur ajoutée du champ `container` par rapport au `journal_id`? trouver comment exploiter la colonne, sinon supprimer.
* [ ] doc_types souvent suspects, à investiguer: "preprint", "autre" (voir aussi si le type "article" peut être affiné selon des critères objectifs)
## Explorer autres sources possibles
* [ ] Dimensions?; ArXiv, PMC, Pubmed; Sudoc? (liens personnes-thèses plus complets que theses.fr, j'ai l'impression); Cairn, Persée pour augmenter couverture SHS?

# UI
## Admin
* [ ] fusion / dé-fusion manuelle de publications: circuit à créer (interface de gestion du référentiel de publications, sur le modèle de admin/persons; avec requêtes pour repérer doublons probables et fusions suspectes; supprimer `admin/duplicates`)
* [ ] créer des catégories de personnes (personnel UCA, chercheurs associés, anciens doctorants, méga-collab de physique des particules) => et pouvoir configurer la visibilité des groupes dans l'UI publique (beaucoup d'adresses UCA dans les collaborations ALICE/ATLAS sont décalées dans les sources, ce qui pourrit la base avec des milliers de fausses "personnes UCA") | ou alors un simple BOOL "visible dans l'UI"?
* [ ] admin/persons, facette "à confirmer": décomptes aberrants
* [ ] recherche personnes par nom+prénom: interroger les 2 colonnes
* [ ] journals/expected.py: faire quelque chose de ça, ou supprimer
## Publique
* [ ] page "affiliations suspectes hal": requête incorrecte, capture trop de publis + problème de perf
* [ ] Filtres supplémentaires possibles: langue; `has_doi` (crossref, datacite, other, none); `corresponding_is_in_perimeter`; `peer_reviewed`? (suppose de posséder la donnée ou de pouvoir la déduire des sources); licence
* [ ] premier/dernier auteur (sur l'onglet publications de la page personne)
* [ ] thèses d'autres établissements liés à nos labos: enlever de la page thèses (ajouter filtre implicite sur "établissement de soutenance" / ou le faire en amont dès le pipeline?)
* [ ] Montants APC consultables via /stats (à envisager une fois que les problèmes de données seront résolus)
* [ ] Publications: facette sujets?
* [ ] Facettes: tester l'option "caché par défaut" / + harmoniser singulier/pluriel

# Cas particuliers, bizarreries à élucider
* [ ] 164107: pourquoi type autre?
* [ ] 165068 type "commmentary"; 86931 type "meeting report" => comment prendre en compte ces types (et empêcher openalex d'imposer le type article); réfléchir au type "report"
* [ ] 30172 un recueil de proceedings fusionné avec tous ses chapitres
* [ ] 182637 et 182636: vérifier si DataCite indique relation
* [ ] 107270 et 869915 Computing Pivot-Minors: un article faussement typé preprint par openalex; + question des arxiv_id (déduire le DOI et vice-versa)
* [ ] fusion entre article et conference_paper: 12362
* [ ] 205492 et 205499: pourquoi pas de fusion? (lesdeux résolvent vers le même DOI)
* [ ] 165425: fusion d'un article et d'un dataset
* [ ] « Daniel Régnier-Roux » incompatible avec la personne 2958 (« daniel roux ») Identifiant hal_person_id='1169' déjà attribué à person_id=2958 avec statut 'pending' ; impossible d'attribuer à person_id=44830. (Correct par hasard; mais l'incompatibilité est anormale)

# Idées pour plus tard, éventuellement
## Fonctionnalités
* financements (projets ANR, projets européens)
* stats en compte fractionnaire vs compte entier
* collaborations nationales et internationales: identification des structures partenaires; évolution des collaborations dans le temps (graphes de collaboration par labo, avec visualisation animée par année)
* définir des groupes de pays (UE, continents) pour la facette "pays des co-auteurs"
* citation count / cité par... (DOI)
* règles de correction de métadonnées et règles de déduplication de publications: actuellement logées dans le code; possibilité de les stocker en base et de les rendre configurables via l'UI?
* OpenAPC: j'ai utilisé les données sur les APC UCA, mais il faudrait partir du dump complet et matcher tous les DOI des publis UCA pour voir quels établissements ont payé les APC quand ce n'est pas l'UCA
## Détails techniques
* audit trail: uniformiser les types d'action qui génèrent un log ou pas + interface pour les consulter
* rendre les extracteurs interruptibles avec ctrl+C sous Windows
* mettre en place des slugs pour les URL?

# Pas nécessaire de le régler, du moment qu'on le documente quelque part
* [ ] re-tester le circuit des imports RH => pas urgent, pas d'imports csv à terme en prod

# Qualité / Doc
* [ ] Audit complet "nommage des variables/fonctions/classes/méthodes/tables/colonnes". S'assurer que le code est structure-agnostique. Supprimer abréviations cryptiques. Revoir certains noms trop restrictifs (publication->document? journal->container?) ou incohérents (extract/cross_import)
* [ ] Audit complet "documentation/docstrings/commentaires". S'assurer que tout est à jour et non-jargonneux.
* [ ] Documenter la duplication de données (vues matérialisées, tables et colonnes dérivées) et leur cycle de vie + quantifier poids vs gain de performance en lecture
* [ ] Documenter les process incrémentaux (flag `dirty`) vs recalcul complet, et les arbitrages entre gain de temps et risque de drift; chaque process incrémental doit avoir un mode `--full-rebuild`
