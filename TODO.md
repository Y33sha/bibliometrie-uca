python -m interfaces.cli.oneshot.backfill_source_record_publishers
python -m interfaces.cli.oneshot.apply_known_platforms
run_pipeline --only publications

# Pipeline
* [ ] bloquer les opérations destructrices côté admin lorsque le pipeline est actif (recenser les actions qui peuvent poser problème)
* [ ] plafond d'interrogations sudoc
## Extraction
* [ ] bioRxiv, medRxiv: voir si on moissonne ces identifiants; possibilité de récupérer les DOI à partir des identifiants comme dans ArXiv? (ex. publi 2757)
* [ ] chercher dans ScanR par hal-id? (généraliser cross-import à tous les identifiants et toutes les sources)
## Suite du traitement
* [ ] enrich_journals_from_openalex: montants APC par journal jamais remis à jour. Probablement pas utile de les moissonner.
* [ ] doaj_payload: garder ou virer?
* [ ] réévaluer l'utilité du flag in_perimeter sur la table publications
* [ ] déduplication par métadonnées: ajouter condition journal_id pour les articles? container title pour les chapitres?
* [ ] documents ScanR qui portent plusieurs DOI: comment stocker l'autre?
* [ ] règles de priorité entre sources pour les métadonnées: assouplir selon les cas de figure (notice OpenAlex ou ScanR dérivées de HAL => HAL doit primer)

# Données
* [ ] DUMAS: comment distinguer mémoires et thèses d'exercice?
* [ ] place_name_forms n'a pas de clé étrangère vers countries
* [ ] publi 106296: gérer les adresses résultant d'une erreur de parsing (à quel niveau: exclure adresses? exclure source_contributions? - gestion manuelle, détection automatisée) / Cf personne 62293
* [ ] goldschmidt abstracts: faire un nouveau type abstract, ou le mettre comme "conférence"?
* [ ] titres de revues: OpenAlex zappe les apostrophes; corriger
* [ ] conserver l'historique des structures
* [ ] identifiants mal placés et neutralisés par le pipeline: auditer
* [ ] récupérer date de publication complète au lieu de l'année seule
* [ ] doublons dans journal_name_forms.form_normalized
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
* [ ] créer des catégories de personnes (personnel UCA, chercheurs associés, anciens doctorants, méga-collab de physique des particules) => et pouvoir configurer la visibilité des groupes dans l'UI publique (beaucoup d'adresses UCA dans les collaborations ALICE/ATLAS sont décalées dans les sources, ce qui pourrit la base avec des milliers de fausses "personnes UCA")
* [ ] admin/persons, facette "à confirmer": décomptes aberrants
* [ ] journals/expected.py: faire quelque chose de ça, ou supprimer
* [ ] distinct_persons: créer circuit DELETE
* [ ] volet latéral pour Editeurs et Revues
## Publique
* [ ] page "affiliations suspectes hal": requête incorrecte, capture trop de publis + problème de perf
* [ ] Filtres supplémentaires possibles: `has_doi` (crossref, datacite, other, none); `corresponding_is_in_perimeter`; `peer_reviewed`? (suppose de posséder la donnée ou de pouvoir la déduire des sources); premier/dernier auteur (sur l'onglet publications de la page personne)

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
* 206321: pourquoi UNH non reconnue?
* 221243: pourquoi pas fusionné avec son hal-id?
* 81408: openalex, source hal; mais pas de doc hal correpondant
* 27059: Epidemiological impact ofNeisseria gonorrhoeaeandChlamydia trachomatisscreening in men having sex with men: a modelling study => normaliser toutes les balises en espaces puis supprimer les espaces doubles

# Idées pour plus tard, éventuellement
## Fonctionnalités
* financements (projets ANR, projets européens)
* stats en compte fractionnaire vs compte entier
* collaborations nationales et internationales: identification des structures partenaires; évolution des collaborations dans le temps (graphes de collaboration par labo, avec visualisation animée par année)
* définir des groupes de pays (UE, continents) pour la facette "pays des co-auteurs"
* citation count / cité par... (DOI)
* OpenAPC: j'ai utilisé les données sur les APC UCA, mais il faudrait partir du dump complet et matcher tous les DOI des publis UCA pour voir quels établissements ont payé les APC quand ce n'est pas l'UCA
## Détails techniques
* mettre en place des slugs pour les URL (au moins pour labos et personnes)?
