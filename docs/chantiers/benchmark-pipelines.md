# Benchmark — pipelines de publications d'autres établissements

## Contexte

Document de référence, extérieur aux fiches chantier. Lecture du code de six projets, au 2026-10-11, sans exécution. Chaque idée renvoie au fichier où elle se voit.

- **CRISalid** : le moissonneur (`svp-harvester`), le graphe (`crisalid-ikg`), et le modèle de données de l'interface (`sovisuplus`).
- **rialto-airflow** : le pipeline de Stanford.
- **ReCiter** : l'attribution des publications PubMed aux personnes, à Weill Cornell.
- **dnet-dedup** : le dédoublonnage du graphe d'OpenAIRE. Lecture partielle, voir la liste des dépôts.
- **Academic Observatory** : les workflows de l'observatoire de l'université Curtin.
- **BiblioRef** : l'outil de l'université Jean Moulin Lyon 3. Moissonneur et connecteurs, lus depuis des archives ; application non lue.

Les liens vers les dépôts sont en fin de document.

## Organisation du code

### Le découpage d'ensemble : acquisition, transformation, diffusion

- **rialto** : trois paquets, dans l'ordre du run. [`harvest_incremental/`](https://github.com/sul-dlss/rialto-airflow/tree/main/rialto_airflow/harvest_incremental) contient un module par source (`openalex.py`, `wos.py`, `crossref.py`, `pubmed.py`…), qui moissonne et charge dans la base de travail, puis `deduplicate.py` et `distill.py`. [`distiller/`](https://github.com/sul-dlss/rialto-airflow/tree/main/rialto_airflow/distiller) consolide, un fichier par champ. [`publish/`](https://github.com/sul-dlss/rialto-airflow/tree/main/rialto_airflow/publish) alimente la base de diffusion. Les graphes Airflow sont à part, dans `dags/`.
- **Academic Observatory** : deux familles de dossiers ([`academic_observatory_workflows/`](https://github.com/The-Academic-Observatory/academic-observatory-workflows/tree/main/academic-observatory-workflows/academic_observatory_workflows)). Un `<source>_telescope/` par source télécharge le dump et le charge dans BigQuery : `telescope.py` pour le graphe, `tasks.py` pour les fonctions, `schema/` pour les tables. Un `<produit>_workflow/` par transformation, avec son SQL dans `sql/` : `doi_workflow/`, `oa_dashboard_workflow/`. Les deux familles n'ont aucun module commun.
- **CRISalid** : deux applications. svp-harvester moissonne : [`app/harvesters/<source>/`](https://github.com/CRISalid-esr/svp-harvester/tree/dev-main/app/harvesters) contient le client, le constructeur de requêtes et les convertisseurs vers un modèle commun. Les résultats sont stockés dans sa base et publiés sur une file de messages. crisalid-ikg les reçoit ([`app/amqp/`](https://github.com/CRISalid-esr/crisalid-ikg/tree/dev-main/app/amqp)) et consolide le graphe dans [`app/services/<entité>/`](https://github.com/CRISalid-esr/crisalid-ikg/tree/dev-main/app/services) : documents (avec `merge_strategies/`), personnes, revues, organisations.
- **openalex-walden** : [`notebooks/ingest/`](https://github.com/ourresearch/openalex-walden/tree/main/notebooks/ingest) contient un notebook par source (Crossref, DataCite, HAL, PubMed, dépôts…). La transformation a un dossier par entité : `authors/`, `institutions/`, `publishers/`, `sources/`, `topics/`, et `end2end/` pour l'assemblage des works. [`jobs/`](https://github.com/ourresearch/openalex-walden/tree/main/jobs) déclare un fichier YAML par chaîne.
- **ReCiter** : un service, sans run par lots. Chaque source a son paquet de récupération (`pubmed/retriever/`, `scopus/retriever/`) ; l'attribution est à part ([`algorithm/`, `engine/`](https://github.com/wcmc-its/ReCiter/tree/master/src/main/java/reciter)).
- **dnet-dedup** : la bibliothèque de rapprochement seule ([`dnet-pace-core/`](https://github.com/dnet-team/dnet-dedup/tree/master/dnet-pace-core)), sans acquisition. Une chaîne Spark plus large l'appelle.

Ce qui se dégage :

- Tous séparent l'acquisition, un dossier ou un module par source, de la transformation. CRISalid en fait deux applications, l'Academic Observatory deux familles de workflows.
- La transformation est rangée par entité produite (walden, crisalid-ikg) ou par produit (Academic Observatory), jamais par source.
- La diffusion, quand elle existe, est un troisième temps distinct (rialto, `publish/`).

### Le graphe du run dans un seul fichier

- Où : rialto, [`dags/harvest_incremental.py`](https://github.com/sul-dlss/rialto-airflow/blob/main/rialto_airflow/dags/harvest_incremental.py), 227 lignes.
- Chaque tâche a une docstring et se réduit à un appel de fonction d'un module.
- Les groupes (moissonnage, complétion par DOI) servent à l'affichage, pas à l'ordre.
- La forme ne dépend pas d'Airflow : c'est ce que serait `run.py`.

### Un module par source, qui contient tout ce qui la concerne

- Où : rialto, [`harvest_incremental/openalex.py`](https://github.com/sul-dlss/rialto-airflow/blob/main/rialto_airflow/harvest_incremental/openalex.py). Le même fichier porte `harvest()` (moissonnage) et `fill_in()` (récupération par DOI).
- Le code est rangé par source, le graphe fixe l'ordre.
- Chez nous : `extract`, `fetch_missing`, `fetch_stale` et `fetch_truncated` d'une même source iraient dans un seul module.

### Les mêmes rôles de fichiers dans chaque source

- Où : svp-harvester, [`app/harvesters/hal/`](https://github.com/CRISalid-esr/svp-harvester/tree/dev-main/app/harvesters/hal) et les dossiers voisins.
- Quand une source dépasse un fichier, chaque dossier contient les mêmes rôles : client HTTP, constructeur de requêtes, convertisseur vers le modèle commun, table des types de document.
- Les sources actives sont déclarées dans [`harvesters.yml`](https://github.com/CRISalid-esr/svp-harvester/blob/dev-main/harvesters.yml).

### Une requête par fichier, nommée par ce qu'elle fait

- Où : crisalid-ikg, [`app/graph/neo4j/queries/`](https://github.com/CRISalid-esr/crisalid-ikg/tree/dev-main/app/graph/neo4j/queries). Plus d'une centaine de fichiers `.cypher`, chargés par leur nom.
- Chez nous : des fichiers `.sql` à côté de chaque étape. Un développeur peut les lire sans connaître Python.

### Un fichier par champ consolidé

- Où : rialto, [`distiller/`](https://github.com/sul-dlss/rialto-airflow/tree/main/rialto_airflow/distiller) : `title.py`, `pub_year.py`, `journal_issn.py`, `open_access.py`…
- Chaque fichier est une courte liste de règles, par ordre de priorité des sources. [`title.py`](https://github.com/sul-dlss/rialto-airflow/blob/main/rialto_airflow/distiller/title.py) fait 26 lignes.
- Pour savoir quelle source donne le titre, on ouvre le fichier qui porte ce nom.
- Chez nous : la logique de `refresh_from_sources`, éclatée par champ.

### Un schéma de travail et un schéma de diffusion

- Où : rialto, [`schema/rialto.py`](https://github.com/sul-dlss/rialto-airflow/blob/main/rialto_airflow/schema/rialto.py) pour la base de travail, [`schema/reports.py`](https://github.com/sul-dlss/rialto-airflow/blob/main/rialto_airflow/schema/reports.py) pour la base que lit Tableau, alimentée par [`publish/`](https://github.com/sul-dlss/rialto-airflow/tree/main/rialto_airflow/publish).
- Les consommateurs ne lisent jamais la base de travail.

### Des tests en miroir

- Où : rialto, [`test/`](https://github.com/sul-dlss/rialto-airflow/tree/main/test). Un fichier de test par module, même arborescence, avec un dossier `data/` de notices d'exemple.

### Les réglages hors du code

- Où : crisalid-ikg, [`publication_sources_policies.yaml`](https://github.com/CRISalid-esr/crisalid-ikg/blob/dev-main/publication_sources_policies.yaml) : ordre des sources et stratégie de fusion par type de document.
- Où : svp-harvester, [`identifiers.yml`](https://github.com/CRISalid-esr/svp-harvester/blob/dev-main/identifiers.yml) : types d'identifiants de personnes, par ordre de priorité.

## Résolution d'entités et décisions humaines

### Un lien entre notices typé par son origine

- Où : crisalid-ikg, [`equivalence_service.py`](https://github.com/CRISalid-esr/crisalid-ikg/blob/dev-main/app/services/source_records/equivalence_service.py) et [`source_record_dao.py`](https://github.com/CRISalid-esr/crisalid-ikg/blob/dev-main/app/graph/neo4j/source_record_dao.py).
- L'étiquette porte sur une arête entre deux notices, pas sur le groupe :
  - `INFERRED_EQUIVALENT` : déduite des identifiants partagés, recalculée librement ;
  - `ASSERTED_EQUIVALENT` : posée par une fusion humaine, jamais recalculée ;
  - `PREDICTED_EQUIVALENT` : lue par le code, créée nulle part pour l'instant.
- Le groupe est la composante connexe sur les trois types d'arêtes. Le document en est la matérialisation.
- Chez nous : savoir, pour chaque rattachement, s'il vient d'une règle ou d'une décision.

### La fusion humaine est une entrée du regroupement

- Où : crisalid-ikg, `merge_documents` dans [`document_service.py`](https://github.com/CRISalid-esr/crisalid-ikg/blob/dev-main/app/services/documents/document_service.py).
- Fusionner A et B crée une arête affirmée entre chaque notice de A et chaque notice de B, puis relance le calcul des composantes.
- La fusion n'est pas une correction rejouée après coup : elle contraint le calcul.

### La trace de l'entité absorbée

- Où : crisalid-ikg, [`create_or_update_document.cypher`](https://github.com/CRISalid-esr/crisalid-ikg/blob/dev-main/app/graph/neo4j/queries/create_or_update_document.cypher).
- Le document absorbé reçoit une arête `TO_BE_MERGED_INTO` vers celui qui survit.
- Chez nous : la table de redirection des identifiants fusionnés.

### Les corrections de champs stockées à part

- Où : crisalid-ikg, [`change_service.py`](https://github.com/CRISalid-esr/crisalid-ikg/blob/dev-main/app/services/changes/change_service.py) et [`processors/`](https://github.com/CRISalid-esr/crisalid-ikg/tree/dev-main/app/services/changes/processors).
- Titre, résumé, type et sujets corrigés sont des nœuds attachés au document, réappliqués après chaque recalcul à partir des notices.
- Le résultat est le même qu'une saisie humaine prioritaire. Ce qui compte : la valeur humaine n'est jamais stockée seulement dans la colonne dérivée.

### Le rapprochement des auteurs en deux temps

- Où : crisalid-ikg, [`source_contributor_mapping_service.py`](https://github.com/CRISalid-esr/crisalid-ikg/blob/dev-main/app/services/source_contributors/source_contributor_mapping_service.py).
- Premier temps : à l'intérieur d'un document, les auteurs des différentes sources sont regroupés par similarité de nom.
- Second temps : chaque groupe est rattaché à une personne, par identifiant puis par nom.
- À comparer avec notre cascade, qui part des signatures une à une.

### Des identifiants de rapprochement déduits

- Où : svp-harvester, [`services/identifiers/rules/`](https://github.com/CRISalid-esr/svp-harvester/tree/dev-main/app/services/identifiers/rules).
- Deux règles : l'identifiant HAL tiré de l'URL, le PPN Sudoc tiré de l'identifiant ScanR (`sudoc258403519`).
- Une règle par fichier, appliquée à la notice avant tout regroupement.

### Le vocabulaire

- `SourcePerson` : l'auteur tel que la source le décrit.
- `SourceContribution` : son lien à la notice, avec un rôle. Le terme couvre aussi les éditeurs scientifiques et les directeurs de thèse.
- Les rôles sont ceux du vocabulaire de la Library of Congress (`aut`, `edt`…).

## Attribution des publications aux personnes : ReCiter

ReCiter pose le problème par personne. Pour chaque personne de l'annuaire, il cherche des articles candidats dans PubMed, puis note chaque candidat. Il ne regroupe pas les signatures entre elles : le code de regroupement existe encore dans le dépôt, mais le moteur ne l'appelle plus.

### Un dossier par type d'indice

- Où : [`algorithm/evidence/targetauthor/`](https://github.com/wcmc-its/ReCiter/tree/master/src/main/java/reciter/algorithm/evidence/targetauthor) : `name/`, `email/`, `affiliation/`, `department/`, `grant/`, `knownrelationship/`, `journalcategory/`, `degree/`…
- Chaque indice est une classe qui reçoit les articles et la personne, et rend un score.
- Les indices ne se lisent pas entre eux. Le moteur les lance en parallèle : l'ordre n'a pas d'effet sur le résultat.
- Chez nous : une alternative à la cascade, où chaque passe dépend des précédentes.

### Chaque indice laisse une trace lisible

- Où : [`ReCiterFeatureGenerator.java`](https://github.com/wcmc-its/ReCiter/blob/master/src/main/java/reciter/engine/ReCiterFeatureGenerator.java).
- Un indice n'écrit pas seulement un score. Il enregistre ce qui a concordé : l'adresse électronique trouvée, la forme du nom, l'affiliation.
- La sortie, pour chaque article, réunit le score total, la décision humaine éventuelle et la liste de ces traces. L'interface de validation les affiche.
- Chez nous : plus riche que `resolution_mode`, qui ne dit que la règle qui a rattaché.

### Les indices activés et pondérés en configuration

- Où : [`application.properties`](https://github.com/wcmc-its/ReCiter/blob/master/src/main/resources/application.properties).
- Une ligne par indice pour l'activer (`strategy.email=true`), une ligne par poids (`strategy.email.emailMatchScore=8`).
- Les mots-clés qui reconnaissent l'établissement dans une affiliation y sont aussi.

### Les décisions humaines servent trois fois

- **Elles s'imposent.** Un article accepté ou rejeté garde son statut quel que soit son score.
- **Elles deviennent des indices pour les autres articles.** Où : [`evidence/targetauthor/feedback/`](https://github.com/wcmc-its/ReCiter/tree/master/src/main/java/reciter/algorithm/evidence/targetauthor/feedback). Pour un candidat, on compte les articles déjà acceptés et rejetés de la même personne qui partagent sa revue, un co-auteur, un mot-clé, une institution, une citation. Quinze indices de ce type.
- **Elles servent à entraîner et à mesurer.** Où : [`resources/scripts/`](https://github.com/wcmc-its/ReCiter/tree/master/src/main/resources/scripts) et [`Analysis.java`](https://github.com/wcmc-its/ReCiter/blob/master/src/main/java/reciter/engine/erroranalysis/Analysis.java). Les scores des indices sont combinés par un petit réseau de neurones entraîné sur les acceptations et les rejets. La précision et le rappel sont calculés contre ces mêmes décisions.

Pour l'entraînement, le score d'un article est calculé sans sa propre décision, pour qu'elle ne s'explique pas par elle-même.

### Repérer l'auteur visé, puis noter

- Où : [`TargetAuthorSelection.java`](https://github.com/wcmc-its/ReCiter/blob/master/src/main/java/reciter/algorithm/evidence/targetauthor/TargetAuthorSelection.java).
- Première étape : trouver, parmi les auteurs de la notice, celui qui peut être la personne. Seconde étape : noter l'article à partir de cet auteur.
- Les deux questions sont séparées dans le code.

### Une classe par manière de chercher des candidats

- Où : [`xml/retriever/pubmed/`](https://github.com/wcmc-its/ReCiter/tree/master/src/main/java/reciter/xml/retriever/pubmed) : par nom complet, par initiale, par adresse électronique, par affiliation, par financement, par ORCID.
- L'équivalent du blocage dans le couplage d'enregistrements : chaque stratégie élargit ou resserre l'ensemble des candidats.

### Ce qu'on écarte chez ReCiter

- **Une classe de contexte par indice**, de 11 à 30 lignes, qui ne fait que déléguer. En Python, une fonction par indice suffit.
- **Des fichiers de plus de 1 000 lignes** pour le nom et pour le repérage de l'auteur visé.
- **L'appel du modèle par un script Python lancé depuis Java**, avec échange de fichiers.
- **L'infrastructure** : DynamoDB, S3 et files SQS d'Amazon.
- **Le code mort** : le regroupement d'articles n'est plus appelé mais reste dans le dépôt.

## Le graphe d'OpenAIRE

Lu dans la documentation du graphe, et pour le dédoublonnage dans le code (`dnet-dedup`, `dnet-hadoop`).

### La chaîne d'ensemble

Dans l'ordre de la [documentation](https://graph.openaire.eu/docs/graph-production-workflow/) :

1. **Agrégation.** Les entrepôts conformes aux directives d'OpenAIRE sont moissonnés en OAI-PMH. Les autres sources (Crossref, ORCID, PubMed, DataCite…) ont chacune leur traitement. Crossref est repris par dump complet, chaque mois.
2. **Fusion par identifiant.** Les enregistrements qui portent le même identifiant sont fusionnés, sans comparaison.
3. **Enrichissement par identifiant.** Les ORCID sont rattachés aux auteurs.
4. **Enrichissement par fouille.** Affiliations, citations, classification, à partir des métadonnées et du texte intégral.
5. **Nettoyage.** Les valeurs sont ramenées à des vocabulaires contrôlés.
6. **Dédoublonnage.** Produits de recherche et organisations.
7. **Déduction et propagation.** Des propriétés passent d'un objet à un autre par règle.
8. **Indicateurs**, **finalisation**, **indexation**, **statistiques**.

Il n'y a pas d'entité « personne ». Un auteur est une propriété de chaque produit, et aucune étape ne désambiguïse les auteurs entre produits.

### La fusion par identifiant, avant le dédoublonnage

- Où : [documentation](https://graph.openaire.eu/docs/graph-production-workflow/merge-by-id).
- Étape distincte et antérieure au dédoublonnage : regroupement par égalité stricte de l'identifiant, fusion des propriétés et des provenances.
- En cas de types contradictoires, un ordre fixe : publication, jeu de données, logiciel, autre.
- Le dédoublonnage par similarité ne traite ensuite que ce qui reste.

### Des identifiants de confiance et d'autres non

- Où : [dédoublonnage des produits de recherche](https://graph.openaire.eu/docs/graph-production-workflow/deduplication/research-products).
- Un identifiant de confiance égal suffit à regrouper deux enregistrements.
- Un identifiant égal mais non garanti (champ `alternateid`) ne suffit pas : il faut en plus des titres similaires à plus de 0,9.
- Sans identifiant commun, le contrôle est strict : nombres d'auteurs cohérents, versions cohérentes dans le titre, titres similaires à plus de 0,95, et une part d'auteurs communs (plus de 60 % si le titre dépasse 30 caractères, plus de 90 % sinon).
- Des types incompatibles interdisent le regroupement.
- Chez nous : répond à la situation « deux publications regroupées à tort par un DOI commun ».

### Le blocage et ses garde-fous

- Clés de blocage des publications : l'identifiant ; ou le nombre d'auteurs, le nombre de mots du titre et des fragments de ses trois premiers mots.
- Dans un bloc, les enregistrements sont triés par titre et chacun n'est comparé qu'aux 50 suivants.
- Un groupe est plafonné à 200 membres.

### L'origine et la confiance de chaque valeur déduite

- Où : [Crossref](https://graph.openaire.eu/docs/graph-production-workflow/aggregation/non-compatible-sources/crossref_unpaywall), [propagation](https://graph.openaire.eu/docs/graph-production-workflow/deduction-and-propagation/propagation).
- Un ORCID fourni par Crossref est étiqueté `pending_orcid`, avec une confiance de 0,9. Un ORCID obtenu par propagation est marqué « potentiel ».
- Chez nous : à rapprocher du statut des identifiants de personnes.

### Le rattachement des ORCID aux auteurs

- Où : [documentation](https://graph.openaire.eu/docs/graph-production-workflow/enrichment-by-pid/orcid-enrichment).
- Le rapprochement passe par l'œuvre : on prend les œuvres déclarées dans le profil ORCID, on retrouve le produit de même identifiant, puis on compare les noms à l'intérieur de ce seul produit.
- Comparaison des noms par stratégies successives, de la plus sûre à la plus lâche : nom complet, nom inversé, mots triés avec tolérance des initiales, nom de crédit, autres noms.
- Un profil ORCID rattaché à un auteur est retiré des comparaisons suivantes.

### Des vocabulaires de synonymes, réappliqués en fin de chaîne

- Où : [documentation](https://graph.openaire.eu/docs/graph-production-workflow/cleaning).
- Un vocabulaire associe à chaque terme la liste de ses synonymes. « Article » et « Article (author) » donnent « Article ».
- Le nettoyage est rejoué en fin de chaîne, parce que les vocabulaires changent après l'agrégation d'une source.
- Chez nous : la situation « règle de correction modifiée ».

### L'alignement des affiliations sur ROR

- Où : [documentation](https://graph.openaire.eu/docs/graph-production-workflow/enrichment-by-mining/affiliation_matching).
- Méthode : classer l'affiliation (université, laboratoire, hôpital, entreprise), raccourcir la chaîne autour de ses mots-clés, comparer aux noms de ROR par similarité cosinus, puis départager les homonymes avec la chaîne complète.
- Seuils : 0,64 pour les universités, 0,87 pour les autres.
- Chez nous : pour les organisations des co-auteurs.

### Des affiliations déduites par règle

- Un produit moissonné dans l'entrepôt d'un établissement est affilié à cet établissement.
- Une affiliation à une organisation fille est reportée sur l'organisation mère, d'un seul niveau.

## Dédoublonnage par étapes : dnet-dedup (OpenAIRE)

### Quatre étapes, une table entre chacune

- Où : les jobs [`SparkCreateSimRels`, `SparkCreateMergeRels`, `SparkCreateDedupEntity`](https://github.com/dnet-team/dnet-dedup/tree/master/dnet-dedup-test/src/main/java/eu/dnetlib/jobs).
- Les étapes :
  1. **blocage** : des fonctions rangent les enregistrements dans des blocs de candidats ;
  2. **relations de similarité** : les paires d'un bloc sont comparées, celles qui concordent sont écrites ;
  3. **relations de fusion** : composantes connexes sur les relations de similarité, puis choix de l'identifiant du groupe ;
  4. **enregistrement représentant** : construit à partir des membres du groupe.
- Chaque étape lit ce que la précédente a écrit. Rien ne passe en mémoire de l'une à l'autre.
- Chez nous : `publications.reconcile` est un seul nœud parce que le plan et son application partagent le voisinage en mémoire. Ce découpage montre où le scinder.

### Les décisions humaines entrent entre les étapes 2 et 3

- Où : dans le code actuel, les jobs `SparkCopyOpenorgsSimRels`, `SparkCopyOpenorgsMergeRels` et `SparkWhitelistSimRels` ([dossier](https://code-repo.d4science.org/D-Net/dnet-hadoop/src/branch/master/dhp-workflows/dhp-dedup-openaire/src/main/java/eu/dnetlib/dhp/oa/dedup)). Le dernier n'a pas pu être lu.
- Pour les organisations, l'algorithme produit des suggestions. Des curateurs les approuvent, les écartent, ou créent une relation que l'algorithme n'a pas vue ([documentation](https://graph.openaire.eu/docs/data-provision/deduplication/organizations)).
- Ces décisions sont des relations ajoutées ou retirées avant le calcul des composantes.
- C'est la même forme que les arêtes affirmées de CRISalid, et c'est la place qu'auraient nos confirmations et rejets autour de Splink : après la comparaison des paires, avant le regroupement.

### Un identifiant de groupe qui survit aux runs

- Où : `SparkCreateMergeRels.java` et `IdGenerator.java`, même dossier.
- Dans chaque groupe, un enregistrement pivot est élu. L'identifiant du groupe est dérivé de celui du pivot.
- Critères d'élection : pivot déjà utilisé lors d'une génération précédente, identifiant délivré par une autorité, source (Crossref pour les publications, DataCite pour les jeux de données), date la plus ancienne, plus petit identifiant.
- Le code et la documentation ne donnent pas le même ordre pour les deux premiers critères. Non vérifié directement.
- Une table d'historique conserve les pivots pendant 12 mois.
- Quand un ancien pivot se retrouve dans un groupe mené par un autre, une relation de fusion relie l'ancien identifiant de groupe au nouveau.
- Chez nous : la stabilisation des identifiants et la table de redirection, dans le cas où le regroupement serait recalculé.

### Les règles déclarées dans un fichier par type d'entité

- Où : par exemple [`pub.new.tree.conf.json`](https://github.com/dnet-team/dnet-dedup/blob/master/dnet-pace-core/src/test/resources/eu/dnetlib/pace/config/pub.new.tree.conf.json).
- Le fichier déclare les champs, les fonctions de blocage, et un arbre de décision : à chaque nœud, un comparateur, un seuil, et la suite selon le résultat.
- Le résultat a trois valeurs : concordant, non concordant, indéterminé quand le champ manque. Chaque cas a sa branche.
- Pour les publications : identifiants égaux, sinon contrôle du type, de la version dans le titre et du nombre d'auteurs, puis titre presque identique.
- Les comparateurs sont une classe chacun, dans [`pace/tree/`](https://github.com/dnet-team/dnet-dedup/tree/master/dnet-pace-core/src/main/java/eu/dnetlib/pace/tree).

### Une liste de titres exclus du rapprochement

- Où : la clé `blacklists` du même fichier.
- Des expressions régulières écartent les titres génériques : « Inside Front Cover », « Note from the Editor », « Poster presentations »…
- Chez nous : à comparer avec le rapprochement par titre long, type et année.

### Ce qu'on écarte chez dnet-dedup

- **Spark, Oozie et Java** : dimensionnés pour des centaines de millions d'enregistrements.
- **L'arbre de décision en JSON** : un langage de règles maison. Les réglages de Splink tiennent ce rôle.

## Entrepôt à l'échelle mondiale : Academic Observatory (Curtin)

Un pipeline ELT au sens strict : des dumps complets de sources ouvertes chargés dans BigQuery, puis une chaîne de requêtes SQL qui produit une table par DOI et des agrégats par établissement, pays, revue, financeur. Pas d'établissement de référence, pas de personnes, pas de décisions humaines.

### Un dossier par source, avec les mêmes fichiers

- Où : [`academic_observatory_workflows/`](https://github.com/The-Academic-Observatory/academic-observatory-workflows/tree/main/academic-observatory-workflows/academic_observatory_workflows), un dossier `<source>_telescope/` par source.
- Chaque dossier contient `telescope.py` (le graphe des tâches), `tasks.py` (les fonctions appelées), `schema/` (le schéma attendu des tables), `tests/fixtures/` (un extrait de dump et le résultat attendu).
- Le fichier de graphe ne contient que l'enchaînement ; la logique est dans `tasks.py`. Même partage que rialto.

### La consolidation en SQL, une requête par source

- Où : [`doi_workflow/sql/`](https://github.com/The-Academic-Observatory/academic-observatory-workflows/tree/main/academic-observatory-workflows/academic_observatory_workflows/doi_workflow/sql) : `crossref_metadata.sql.jinja2`, `openalex.sql.jinja2`, `unpaywall.sql.jinja2`, `ror.sql.jinja2`… puis `doi.sql.jinja2` qui les joint.
- Les requêtes sont déclarées comme données dans [`queries.py`](https://github.com/The-Academic-Observatory/academic-observatory-workflows/blob/main/academic-observatory-workflows/academic_observatory_workflows/doi_workflow/queries.py) : nom, tables d'entrée, table de sortie. Les requêtes d'une même liste n'ont pas de dépendance entre elles.
- La réconciliation se réduit à une jointure sur le DOI, Crossref servant de référence : une publication sans DOI Crossref n'existe pas.

### Un graphe qui attend ses sources

- Le workflow de consolidation commence par des capteurs qui attendent la fin de chaque workflow de source.
- Acquisition et transformation sont deux graphes distincts. La transformation ne fait aucun appel réseau, à une exception près (voir plus bas).

### Des versions datées plutôt que des mises à jour

- Chaque source est chargée comme un instantané daté (tables suffixées par la date). La consolidation désigne explicitement l'instantané qu'elle lit.
- Une table de « releases » garde, par source, la date du dernier instantané traité ; un run sans nouvel instantané s'arrête au premier test.
- Chez nous : l'équivalent de `pipeline_phase_executions`, pour savoir ce que le dernier run a lu.

### Le contrôle du schéma des sources

- Où : `compare_schemas` dans [`openalex_telescope/tasks.py`](https://github.com/The-Academic-Observatory/academic-observatory-workflows/blob/main/academic-observatory-workflows/academic_observatory_workflows/openalex_telescope/tasks.py).
- Le schéma déduit du dump est comparé au schéma attendu, versionné dans le dépôt. Un écart envoie une alerte, sans bloquer le chargement.
- Chez nous : détecter qu'une source a changé de format avant que la normalisation échoue ou perde des champs en silence.

### Des affiliations élargies par la hiérarchie de ROR

- Où : `doi.sql.jinja2` et `create_ror_hierarchy_table` dans [`doi_workflow/tasks.py`](https://github.com/The-Academic-Observatory/academic-observatory-workflows/blob/main/academic-observatory-workflows/academic_observatory_workflows/doi_workflow/tasks.py).
- Une table matérialise, pour chaque organisation ROR, tous ses ascendants. Une publication est attribuée à l'organisation de l'auteur et à toute sa généalogie.
- Chez nous : l'équivalent de `perimeter_structures`, appliqué aux organisations des co-auteurs.

### Les entrepôts rattachés à un établissement

- Où : `create_repo_institution_to_ror_table`, même fichier.
- Les noms d'entrepôts d'Unpaywall sont alignés sur ROR par l'API d'affiliation de ROR. C'est le seul appel réseau de la consolidation.
- Sert à compter le dépôt en archive ouverte par établissement.

### Ce qu'on écarte chez Academic Observatory

- **BigQuery, Google Cloud, Astronomer, Kubernetes** : dimensionnés pour des dumps de plusieurs centaines de gigaoctets.
- **Le DOI comme seule clé** : rien pour les documents sans DOI, ni pour un DOI erroné.
- **Les affiliations d'OpenAlex reprises telles quelles** : aucune lecture des adresses.

## Outil d'établissement : BiblioRef (Lyon 3)

Lu à partir d'archives : le moissonneur (`harvester`, 2 600 lignes de Python), les connecteurs (`connector-base`, `connector-hal`, `connector-openalex`, `connector-sudoc`, de 2 400 à 4 100 lignes chacun) et le dépôt de présentation (`awesome-biblioref`). Non lus : le schéma de la base, l'API et l'interface. Chaque dépôt a été publié en un seul commit en septembre 2025, développé par la société DyoNeo pour le SCD de Lyon 3.

### Des connecteurs en services séparés, derrière un contrat commun

- Où : [`utils/tools.py`](https://gitlab.com/biblioref/harvester/harvester/-/blob/main/utils/tools.py), [`start.py`](https://gitlab.com/biblioref/harvester/harvester/-/blob/main/start.py).
- Chaque source (HAL, OpenAlex, Sudoc) est un service à part, qui expose trois routes : `/ping`, `/researchproducts/?start_date=…` (notices nouvelles ou modifiées depuis une date), `/researchproduct/<id>` (une notice).
- Le moissonneur interroge d'abord chaque connecteur actif ; si l'un ne répond pas, le run s'arrête et l'échec est journalisé.
- Les connecteurs actifs, leur adresse et leur ordre de priorité sont dans une table `source`.
- Un run hebdomadaire par cron, qui demande les notices modifiées depuis la date du dernier run réussi.

### Un connecteur par source, chacun avec sa base

- Où : [`connector-base`](https://gitlab.com/biblioref/connectors/connector-base), et son [guide de création d'un connecteur](https://gitlab.com/biblioref/connectors/connector-base/-/blob/main/FORK_GUIDE.md).
- Chaque connecteur est une copie (« fork ») du connecteur de base : même arborescence, mêmes classes, seuls `connector/data_collector.py` et `connector/data_binding.py` changent vraiment.
- Chaque connecteur a sa propre base PostgreSQL, où il range ses notices dans un modèle commun. Le moissonneur lit ensuite ces bases par l'API de chaque connecteur.
- Dans la base d'un connecteur, une notice déjà connue est supprimée puis recréée si la source donne une date de modification plus récente.
- Chez nous : l'équivalent de `staging` et de `source_publications`, découpé en une base par source. La duplication du code entre connecteurs est le prix de cette indépendance.

### Le moissonnage part de l'annuaire

- Où : `collectDatasByAuthor` dans [`connector-hal/connector/data_collector.py`](https://gitlab.com/biblioref/connectors/connector-hal/-/blob/main/connector/data_collector.py), et `getQueryAuthors` dans `classes/utils/tools.py`.
- Les connecteurs lisent dans la base principale les personnes de l'annuaire rattachées à une structure du périmètre, leurs identifiants et leurs périodes de présence.
- Chaque personne est interrogée par ses identifiants, sur la seule période où elle était dans une structure du périmètre (date de publication entre la date d'entrée et la date de sortie).
- HAL peut aussi être interrogé par structure, avec l'identifiant AuréHAL. OpenAlex et le Sudoc ne le sont que par personne.
- Le champ de la source qui correspond à chaque type d'identifiant est déclaré en base (`sourceidentifiertype`), pas dans le code.
- Une nouvelle période de présence ajoutée à l'annuaire est marquée ; le run suivant moissonne cette période, puis le marqueur est levé.
- Chez nous : l'inverse du moissonnage par affiliation. Une personne absente de l'annuaire ou sans identifiant n'a pas de publications, sauf dans HAL par structure.

### Les mises à jour

- HAL : notices modifiées depuis un nombre de jours donné.
- OpenAlex : par date de publication seulement. Un commentaire du code note que le filtre par date de mise à jour est payant.
- Le Sudoc : requête SPARQL par IdRef, puis notice complète en MARCXML.
- Aucune gestion des notices disparues d'une source.

### L'origine de chaque champ consolidé

- Où : [`classes/interfaces/researchproduct.py`](https://gitlab.com/biblioref/harvester/harvester/-/blob/main/classes/interfaces/researchproduct.py), [`utils/fields_origin.json`](https://gitlab.com/biblioref/harvester/harvester/-/blob/main/utils/fields_origin.json).
- Les notices d'un même document sont triées par priorité de source ; pour chaque champ (titre, type, auteurs, disciplines, mots-clés, accès ouvert…), la première source qui le renseigne l'emporte.
- La source et l'identifiant de la notice retenue sont enregistrés champ par champ, dans une colonne JSON (`researchproductorigin`).
- Chez nous : savoir d'où vient la valeur affichée, sans recalculer.

### La manière dont une structure a été attribuée

- Où : [`classes/interfaces/structure.py`](https://gitlab.com/biblioref/harvester/harvester/-/blob/main/classes/interfaces/structure.py), [`utils/structurechoice.py`](https://gitlab.com/biblioref/harvester/harvester/-/blob/main/utils/structurechoice.py).
- Chaque lien signature-structure porte un code qui dit comment il a été établi : saisie manuelle, fourni par la source, appartenance datée de la personne dans l'annuaire à la date de publication, structure de l'annuaire retrouvée parmi celles de la signature, structure du périmètre, ou premier type de structure dans un ordre fixe (laboratoire, unité, établissement…).
- Chez nous : à rapprocher de `matched_form_id` et de `resolution_mode`, avec en plus la saisie manuelle comme valeur du même code.

### Le verrouillage

- Une publication ou un auteur porte un booléen `locked`. Une publication verrouillée n'est plus touchée par le dédoublonnage.
- C'est le troisième mécanisme de la gestion des données de référence (après la source prioritaire et la contrainte de la résolution), avec sa limite : la publication ne reçoit plus les mises à jour des sources.

### Le dédoublonnage

- Où : [`utils/researchproduct_deduplication.py`](https://gitlab.com/biblioref/harvester/harvester/-/blob/main/utils/researchproduct_deduplication.py), [`utils/data_binding.py`](https://gitlab.com/biblioref/harvester/harvester/-/blob/main/utils/data_binding.py), [`ALGORITHM.md`](https://gitlab.com/biblioref/harvester/harvester/-/blob/main/ALGORITHM.md).
- Conditions obligatoires : même sous-type de document et même date de publication, au jour près.
- Puis : DOI égal, ou même identifiant de notice, suffit. Sinon il faut au moins un identifiant d'auteur commun, puis des titres proches (score pondéré Levenshtein, Jaro-Winkler et tri des mots, seuil 0,85).
- Chaque notice entrante est comparée à toutes les publications existantes, en mémoire.
- Quand un doublon est trouvé, les publications existantes sont supprimées et une nouvelle est construite à partir de toutes les notices, rechargées une à une auprès des connecteurs : l'identifiant de la publication change.

### Les auteurs

- Où : [`classes/interfaces/author.py`](https://gitlab.com/biblioref/harvester/harvester/-/blob/main/classes/interfaces/author.py).
- Un annuaire (`authorreference`), avec les appartenances datées aux structures, sert de référence. Une signature y est rattachée par identifiant.
- Hors annuaire, une signature est rattachée à un auteur déjà connu par identifiant, sinon par égalité exacte du prénom et du nom, sinon un auteur est créé.

### Ce qu'on écarte chez BiblioRef

- **La date de publication au jour près comme condition du dédoublonnage** : deux sources donnent souvent des dates différentes pour le même document.
- **La suppression puis la recréation de la publication à chaque fusion** : identifiant instable, décisions perdues.
- **Le rattachement d'auteurs par égalité de nom, sans contrôle des homonymes.**
- **La comparaison de chaque notice à tout le stock en mémoire.**
- **Le code commun recopié dans chaque connecteur**, au lieu d'une bibliothèque partagée.

## Métadonnées

### Les types de document traduits par table

- Où : svp-harvester, [`hal_document_type_converter.py`](https://github.com/CRISalid-esr/svp-harvester/blob/dev-main/app/harvesters/hal/hal_document_type_converter.py).
- Une table par source, du type natif vers un vocabulaire commun.

### La notice la plus riche, par score

- Où : crisalid-ikg, [`global_richest_merge_strategy.py`](https://github.com/CRISalid-esr/crisalid-ikg/blob/dev-main/app/services/documents/merge_strategies/global_richest_merge_strategy.py).
- Chaque notice reçoit un score pondéré : longueur du résumé, nombre de contributeurs, de mots-clés, présence d'une date. La mieux notée fournit les métadonnées.
- Une autre manière de choisir que la priorité fixe entre sources.

### Les libellés des concepts complétés

- Où : svp-harvester, [`services/concepts/`](https://github.com/CRISalid-esr/svp-harvester/tree/dev-main/app/services/concepts).
- Pour un sujet fourni avec un identifiant (IdRef, Wikidata, JEL), le référentiel est interrogé et ses libellés préférés et alternatifs sont enregistrés.
- Cela unifie les libellés. Cela ne filtre pas les sujets aberrants.

## Ce qu'on écarte, et pourquoi

- **L'enchaînement par événements et RabbitMQ** (CRISalid). Adapté à un usage interactif et à des règles locales. Avec une résolution qui compare des noms sur tout le corpus, le traitement notice par notice serait lent et dépendrait de l'ordre d'arrivée.
- **Les DAO génériques à une seule implémentation** (CRISalid). Même défaut que nos ports.
- **Une classe par type de message** (CRISalid). Une trentaine de fichiers pour émettre des événements.
- **Le traitement publication par publication en Python** (rialto, `distill.py`). Convient à leur volume, pas à nos étapes ensemblistes.
- **Le type élu par ordre des sources** (CRISalid). Le premier type connu gagne, sans règle de cohérence.
- **La liste entière des contributeurs remplacée par la dernière correction** (CRISalid). Nos confirmations et rejets portent sur un lien à la fois.
- **Le dédoublonnage par identifiants seuls** (CRISalid, rialto). Aucun rapprochement par titre.
- **Le lien structure-publication par l'appartenance des personnes** (CRISalid). Les publications d'un laboratoire sont celles de ses membres dans l'annuaire, sans lecture des adresses.

## Ce que ces exemples ne montrent pas

- CRISalid et rialto n'ont pas de résolution lourde. Le premier s'appuie sur des identifiants alignés dans l'annuaire, le second trouve ses auteurs par ORCID.
- ReCiter part d'un annuaire de personnes connues et cherche leurs articles. Il ne crée pas de personnes à partir des signatures, et ne traite ni les co-auteurs extérieurs ni le dédoublonnage des publications.
- dnet-dedup dédoublonne des publications et des organisations. Son traitement des auteurs n'a pas été lu.
- La forme commune à CRISalid, à dnet-dedup et à Splink : comparer des paires, ajouter les décisions humaines, calculer les groupes, stabiliser leur identifiant, construire l'entité.

## Dépôts

### Lus

- **[sul-dlss/rialto-airflow](https://github.com/sul-dlss/rialto-airflow)** — Stanford. Python, Airflow, PostgreSQL, SQLAlchemy. 5 800 lignes. Dernier commit : 2026-10-05. Son README décrit encore une base recréée à chaque moisson ; le code actuel est incrémental.
- **[CRISalid-esr/svp-harvester](https://github.com/CRISalid-esr/svp-harvester)** — moissonneur par personne. Python, FastAPI, PostgreSQL, RabbitMQ. Dernier commit : 2026-09-11. [Documentation](https://svp-harvester.readthedocs.io/en/latest/).
- **[CRISalid-esr/crisalid-ikg](https://github.com/CRISalid-esr/crisalid-ikg)** — graphe et résolution. Python, FastAPI, Neo4j, RabbitMQ. Dernier commit : 2026-09-09.
- **[CRISalid-esr/sovisuplus](https://github.com/CRISalid-esr/sovisuplus)** — interface. Next.js, Prisma. Lu pour son modèle de données seulement. Dernier commit : 2026-10-07.

- **[wcmc-its/ReCiter](https://github.com/wcmc-its/ReCiter)** — attribution par score, retours humains. Java, Spring Boot, DynamoDB, scripts Python pour le modèle. 287 fichiers, 32 000 lignes. Dernier commit : 2026-09-29. [Fonctionnement pas à pas](https://github.com/wcmc-its/ReCiter/wiki/How-ReCiter-works). Interface de validation : [ReCiter-Publication-Manager](https://github.com/wcmc-its/ReCiter-Publication-Manager).

- **[dnet-team/dnet-dedup](https://github.com/dnet-team/dnet-dedup)** — dédoublonnage d'OpenAIRE. Java, Spark. Dernier commit sur GitHub : 2022-04-26. Lu : configuration, comparateurs, fonctions de blocage.
- **[D-Net/dnet-hadoop](https://code-repo.d4science.org/D-Net/dnet-hadoop)** — code actuel du graphe d'OpenAIRE, module `dhp-dedup-openaire`, fichiers datés de 2023-2024. Lu par résumé : `SparkCreateMergeRels.java`, `IdGenerator.java`. Non lu : `SparkWhitelistSimRels.java` (accès refusé). Le miroir GitHub de ce dépôt date de 2019.
- **[The-Academic-Observatory/academic-observatory-workflows](https://github.com/The-Academic-Observatory/academic-observatory-workflows)** — université Curtin. Python, Airflow, BigQuery, SQL en gabarits Jinja. 31 000 lignes de Python, dont 7 700 de liste d'établissements. Dernier commit : 2026-10-12.
- **[biblioref (GitLab)](https://gitlab.com/biblioref)** — université Jean Moulin Lyon 3, développé par DyoNeo. Python pour le moissonneur, Node.js et Angular pour l'application, PostgreSQL. Lus, depuis des archives : [`harvester`](https://gitlab.com/biblioref/harvester/harvester), [`connector-base`](https://gitlab.com/biblioref/connectors/connector-base), [`connector-hal`](https://gitlab.com/biblioref/connectors/connector-hal), [`connector-openalex`](https://gitlab.com/biblioref/connectors/connector-openalex), [`connector-sudoc`](https://gitlab.com/biblioref/connectors/connector-sudoc), [`awesome-biblioref`](https://gitlab.com/biblioref/awesome-biblioref/awesome-biblioref). Un seul commit par dépôt, septembre 2025. Non lus : `bdd`, `backend`, `frontend`. Présentation : [*Arabesques*](https://publications-prairial.fr/arabesques/index.php?id=4433).

### Repérés, non lus

- **[dataesr/affiliation-matcher](https://github.com/dataesr/affiliation-matcher)** — alignement d'une affiliation brute sur ROR et le RNSR.
- **[ourresearch/openalex-walden](https://github.com/ourresearch/openalex-walden)** — pipelines d'OpenAlex, sur Databricks.
- **[conditor-project](https://github.com/conditor-project)** — dédoublonnage de la production française, Inist. État de maintenance non vérifié.
