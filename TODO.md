# Backfill à lancer sur base de prod:
python -m interfaces.cli.oneshot.backfill_detach_datacite_journals
puis: run_pipeline --only publishers_journals

# Pipeline
* [ ] bloquer les opérations destructrices côté admin lorsque le pipeline est actif (recenser les actions qui peuvent poser problème)
## Extraction
* [ ] ajouter extraction par ORCID: vérifier pertinence (tester différentes sources, auditer le gain)
* [ ] bioRxiv, medRxiv: voir si on moissonne ces identifiants; possibilité de récupérer les DOI à partir des identifiants comme dans ArXiv? (ex. publi 2757)
* [ ] chercher dans ScanR par hal-id? (généraliser cross-import à tous les identifiants et toutes les sources)
## Suite du traitement
* [ ] enrich_journals_from_openalex: montants APC par journal jamais remis à jour. Probablement pas utile de les moissonner.
* [ ] doaj_payload: garder ou virer?
* [ ] CLI `seed_journals_doi_prefix`: intégrer au pipeline? + recalculer les anciens pour tenir compte des nouveaux (chaque doi_prefix de journal doit être unique et aussi précis que possible; à cette occasion, réécrire la fonction resolve_journal_by_doi de manière moins alambiquée)
* [ ] réévaluer l'utilité du flag in_perimeter sur la table publications
* [ ] suggested countries: jamais remis à null
* [ ] déduplication par métadonnées: ajouter condition journal_id pour les articles? container title pour les chapitres?
* [ ] documents ScanR qui portent plusieurs DOI: comment stocker l'autre?
* [ ] règles de priorité entre sources pour les métadonnées: assouplir selon les cas de figure (notice OpenAlex ou ScanR dérivées de HAL => HAL doit primer)
* [ ] normalisation des caractères non-latins?

# Code
* [ ] modules partagés app/pipeline: à sortir plutôt que d'autoriser l'app à importer des modules du pipeline?

# Données
* [ ] DUMAS: comment distinguer mémoires et thèses d'exercice?
* [ ] place_name_forms n'a pas de clé étrangère vers countries
* [ ] publi 106296: gérer les adresses résultant d'une erreur de parsing (à quel niveau: exclure adresses? exclure source_authorships? - gestion manuelle, détection automatisée) / Cf personne 62293
* [ ] rejected_authorships: au niveau des source_authorships ou source_publications?
## Corrections
* [ ] détection d'incohérences `doi_prefix`/`publisher_id`/`journal_id`: auditer d'abord, classifier les cas de divergence selon leur cause
* [ ] créer circuit pour correction automatisée du `journal_type` (titre terminé par ` eBooks` => plateforme d'ebooks; titre contenant `International Conference` ou `International Symposium` => proceedings)
* [ ] typage data_paper automatisé par journal (ex. *Scientific Data*; créer un journal_type dédié?); chercher aussi "dataset" dans les titres
* [ ] règle à créer: si DOI de forme ISBN + _n => conference_paper ou chapitre / si forme ISBN: proceedings ou book (trancher selon type du "journal")
* [ ] noms de containers OpenAlex aberrants ("SPIRE - Sciences Po Institutional REpository") => faire quelque chose; quelle valeur ajoutée du champ `container` par rapport au `journal_id`? trouver comment exploiter la colonne, sinon supprimer.
* [ ] doc_types souvent suspects, à investiguer: "preprint", "autre" (voir aussi si le type "article" peut être affiné selon des critères objectifs)
## Explorer autres sources possibles
* [ ] Dimensions?; ArXiv, PMC, Pubmed; Sudoc? (liens personnes-thèses plus complets que theses.fr, j'ai l'impression); Cairn, Persée pour augmenter couverture SHS?
* [ ] y a-t-il une API pour contrôler les ISSN?

# UI
## Admin
* [ ] fusion / dé-fusion manuelle de publications: circuit à créer (interface de gestion du référentiel de publications, sur le modèle de admin/persons; avec requêtes pour repérer doublons probables et fusions suspectes)
* [ ] créer des catégories de personnes (personnel UCA, chercheurs associés, anciens doctorants, méga-collab de physique des particules) => et pouvoir configurer la visibilité des groupes dans l'UI publique (beaucoup d'adresses UCA dans les collaborations ALICE/ATLAS sont décalées dans les sources, ce qui pourrit la base avec des milliers de fausses "personnes UCA") | ou alors un simple BOOL "visible dans l'UI"?
* [ ] admin/persons, facette "à confirmer": décomptes aberrants
* [ ] journals/expected.py: faire quelque chose de ça, ou supprimer
* [ ] distinct_persons: créer circuit DELETE
* [ ] admin/countries: aligner les boutons à droite
* [ ] runs pipeline: les messages d'erreur n'affichent aucune info utile (Can't reconnect until invalid transaction is rolled back. Please rollback() fully before proceeding (Background on this error at: https://sqlalche.me/e/20/8s2b))
* [ ] admin/person: ne pas proposer d'absorber un homonyme si les deux ont une fiche RH
## Publique
* [ ] page "affiliations suspectes hal": requête incorrecte, capture trop de publis + problème de perf
* [ ] Filtres supplémentaires possibles: `has_doi` (crossref, datacite, other, none); `corresponding_is_in_perimeter`; `peer_reviewed`? (suppose de posséder la donnée ou de pouvoir la déduire des sources); licence; premier/dernier auteur (sur l'onglet publications de la page personne)
* [ ] thèses d'autres établissements liés à nos labos: enlever de la page thèses (ajouter filtre implicite sur "établissement de soutenance" / ou le faire en amont dès le pipeline?)
* [ ] Montants APC consultables via /stats (à envisager une fois que les problèmes de données seront résolus)

# Cas particuliers, bizarreries à élucider
* [ ] 164107: pourquoi type autre?
* [ ] 165068 type "commmentary"; 86931 type "meeting report" => comment prendre en compte ces types (et empêcher openalex d'imposer le type article); réfléchir au type "report"
* [ ] 30172 un recueil de proceedings fusionné avec tous ses chapitres
* [ ] 182637 et 182636: vérifier si DataCite indique relation
* [ ] 107270 et 869915 Computing Pivot-Minors: un article faussement typé preprint par openalex; + question des arxiv_id (déduire le DOI et vice-versa)
* [ ] fusion entre article et conference_paper: 12362
* [ ] 165425: fusion d'un article et d'un dataset
* [ ] « Daniel Régnier-Roux » incompatible avec la personne 2958 (« daniel roux ») Identifiant hal_person_id='1169' déjà attribué à person_id=2958 avec statut 'pending' ; impossible d'attribuer à person_id=44830. (Correct par hasard; mais l'incompatibilité est anormale)
* [ ] "Total phase persons : 3 new, 51333 updated" comment est-ce possible, avec 14k personnes en base?
* [ ] 172655 titre mal formé (notation mathématique mal développée)
* 116323: comment empêcher la fusion de l'ouvrage et de ses chapitres?
* 100685: pourquoi preprint?
* 138474: 1 seul document alors que le preprint devrait être distinct

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
* rendre les extracteurs interruptibles avec ctrl+C sous Windows
* mettre en place des slugs pour les URL (au moins pour labos et personnes)?
* passer les grandes listes en pagination par curseur (plus de plafond nécessaire) + curseur pour les exports csv — "suppose de faire passer la connexion de la dépendance au flux, FastAPI la refermant avant l'envoi du corps"
