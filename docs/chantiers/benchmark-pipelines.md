# Benchmark — pipelines de publications d'autres établissements

## Contexte

Document de référence, extérieur aux fiches chantier. Lecture du code de six projets, au 2026-10-11, sans exécution. Chaque idée renvoie au fichier où elle se voit et se clôt sur un verdict.

- **CRISalid** : un moissonneur qui interroge les sources personne par personne (`svp-harvester`), un graphe Neo4j qui regroupe les notices et les rattache aux personnes (`crisalid-ikg`), et l'interface (`sovisuplus`), lue pour son modèle de données. Les étapes s'enchaînent par événements, avec RabbitMQ.
- **rialto-airflow** : le pipeline de Stanford, en Python et PostgreSQL, orchestré par Airflow. Il moissonne les publications des chercheurs de l'université, trouvés par leur ORCID, et complète les notices par DOI. Il consolide ensuite chaque champ, puis publie une base que lit Tableau.
- **ReCiter** : l'attribution des publications PubMed aux personnes, à Weill Cornell. Il part de chaque personne de l'annuaire, cherche des articles candidats dans PubMed, puis note chaque candidat.
- **OpenAIRE** : le graphe européen de la recherche. Il agrège des entrepôts moissonnés en OAI-PMH et des sources comme Crossref, ORCID ou DataCite. Il fusionne par identifiant, enrichit, nettoie, dédoublonne, puis calcule des indicateurs. Il n'a pas d'entité « personne ». Lu dans la [documentation](https://graph.openaire.eu/docs/graph-production-workflow/), et en partie dans le code du dédoublonnage (`dnet-dedup`, `dnet-hadoop`).
- **Academic Observatory** : les workflows de l'observatoire de l'université Curtin. Des dumps complets de sources ouvertes sont chargés dans BigQuery, puis des requêtes SQL produisent une table par DOI et des agrégats par établissement, pays, revue, financeur. Ni personnes ni décisions humaines.
- **BiblioRef** : l'outil de l'université Jean Moulin Lyon 3, développé par la société DyoNeo. Un moissonneur en Python part d'un annuaire de chercheurs et interroge un connecteur par source (HAL, OpenAlex, Sudoc). L'application est en Node.js. Lu depuis des archives, sauf l'interface.

Les liens vers les dépôts sont en fin de document.

## Organisation du code et du run

### Le graphe du run dans un seul fichier (rialto)

- Où : [`dags/harvest_incremental.py`](https://github.com/sul-dlss/rialto-airflow/blob/main/rialto_airflow/dags/harvest_incremental.py), 227 lignes.
- Chaque tâche a une docstring et se réduit à un appel de fonction d'un module.
- Les groupes (moissonnage, complétion par DOI) servent à l'affichage, pas à l'ordre.
- **Verdict : adopté**, dans `pipeline/graph.py`. Le graphe déclare en plus ce que chaque nœud lit et écrit, et les tests en vérifient l'ordre. La fonction qui exécute un nœud est déclarée dans le `build()` de sa phase : le graphe reste une déclaration, lisible sans importer le code des phases.

### Une requête par fichier, nommée par ce qu'elle fait (CRISalid)

- Où : crisalid-ikg, [`app/graph/neo4j/queries/`](https://github.com/CRISalid-esr/crisalid-ikg/tree/dev-main/app/graph/neo4j/queries). Plus d'une centaine de fichiers `.cypher`, chargés par leur nom.
- **Verdict : écarté.** Une partie de nos requêtes est assemblée par le code (portée optionnelle, filtres). La requête reste à côté du code qui lie ses paramètres et lit son résultat.

### Un schéma de travail et un schéma de diffusion (rialto)

- Où : [`schema/rialto.py`](https://github.com/sul-dlss/rialto-airflow/blob/main/rialto_airflow/schema/rialto.py) pour la base de travail, [`schema/reports.py`](https://github.com/sul-dlss/rialto-airflow/blob/main/rialto_airflow/schema/reports.py) pour la base que lit Tableau, alimentée par [`publish/`](https://github.com/sul-dlss/rialto-airflow/tree/main/rialto_airflow/publish).
- Les consommateurs ne lisent jamais la base de travail.
- **Verdict : écarté.** L'administration édite les tables du pipeline, et ses éditions ont un effet immédiat dans l'interface publique par les recalculs ciblés. Une base de diffusion retarderait cet effet jusqu'à la publication suivante. La question se pose si un consommateur en lecture seule apparaît en production.

### Des notices d'exemple pour les tests (rialto)

- Où : [`test/`](https://github.com/sul-dlss/rialto-airflow/tree/main/test), dossier `data/`.
- Les tests lisent des notices d'exemple figées dans le dépôt.
- **Verdict : adopté**, par le jeu de données commun aux tests du pipeline : quelques notices réelles par source, avec les réponses des API enregistrées.

### Les réglages hors du code (CRISalid)

- Où : crisalid-ikg, [`publication_sources_policies.yaml`](https://github.com/CRISalid-esr/crisalid-ikg/blob/dev-main/publication_sources_policies.yaml) : ordre des sources et stratégie de fusion par type de document.
- Où : svp-harvester, [`identifiers.yml`](https://github.com/CRISalid-esr/svp-harvester/blob/dev-main/identifiers.yml) : types d'identifiants de personnes, par ordre de priorité.
- **Verdict : écarté.** Les priorités entre sources restent dans le code (`domain/sources/registry.py`) : leur logique est appelée à changer (assouplissement selon les cas, consensus entre sources), au-delà d'un simple ordre réglable.

### Un graphe qui attend ses sources (Academic Observatory)

- Le workflow de consolidation commence par des capteurs qui attendent la fin de chaque workflow de source.
- Acquisition et transformation sont deux graphes distincts. La transformation ne fait aucun appel réseau, à une exception près : l'alignement des noms d'entrepôts d'Unpaywall sur ROR.
- **Verdict : écarté.** Les enrichissements (agence des DOI, DOAJ, Sudoc, Unpaywall) appellent des API à partir des données transformées : ils restent dans la transformation. L'attente des sources relève d'un orchestrateur comme Airflow.

## Acquisition des sources

### Un connecteur par source : un service et une base chacun (BiblioRef)

- Où : [`utils/tools.py`](https://gitlab.com/biblioref/harvester/harvester/-/blob/main/utils/tools.py), [`start.py`](https://gitlab.com/biblioref/harvester/harvester/-/blob/main/start.py), [`connector-base`](https://gitlab.com/biblioref/connectors/connector-base) et son [guide de création d'un connecteur](https://gitlab.com/biblioref/connectors/connector-base/-/blob/main/FORK_GUIDE.md).
- Chaque source (HAL, OpenAlex, Sudoc) est un service à part, qui expose trois routes : `/ping`, `/researchproducts/?start_date=…` (notices nouvelles ou modifiées depuis une date), `/researchproduct/<id>` (une notice).
- Chaque connecteur est une copie (« fork ») du connecteur de base : même arborescence, mêmes classes, seuls `connector/data_collector.py` et `connector/data_binding.py` changent vraiment.
- Chaque connecteur a sa propre base PostgreSQL, où il range ses notices dans un modèle commun. Une notice déjà connue est supprimée puis recréée si la source donne une date de modification plus récente.
- Le moissonneur interroge d'abord chaque connecteur actif ; si l'un ne répond pas, le run s'arrête et l'échec est journalisé. Il lit ensuite les bases des connecteurs par leur API.
- Les connecteurs actifs, leur adresse et leur ordre de priorité sont dans une table `source`.
- Un run hebdomadaire par cron, qui demande les notices modifiées depuis la date du dernier run réussi.
- **Verdict : écarté.** Nos sources sont des modules d'un même paquet, qui partagent leur code commun et leur base. Une source qui ne répond pas est coupée par son circuit-breaker, et le run continue sans elle.

### Le moissonnage part de l'annuaire (BiblioRef)

- Où : `collectDatasByAuthor` dans [`connector-hal/connector/data_collector.py`](https://gitlab.com/biblioref/connectors/connector-hal/-/blob/main/connector/data_collector.py), et `getQueryAuthors` dans `classes/utils/tools.py`.
- Les connecteurs lisent dans la base principale les personnes de l'annuaire rattachées à une structure du périmètre, leurs identifiants et leurs périodes de présence.
- Chaque personne est interrogée par ses identifiants, sur la seule période où elle était dans une structure du périmètre (date de publication entre la date d'entrée et la date de sortie).
- HAL peut aussi être interrogé par structure, avec l'identifiant AuréHAL. OpenAlex et le Sudoc ne le sont que par personne.
- Le champ de la source qui correspond à chaque type d'identifiant est déclaré en base (`sourceidentifiertype`), pas dans le code.
- Une nouvelle période de présence ajoutée à l'annuaire est marquée ; le run suivant moissonne cette période, puis le marqueur est levé.
- **Verdict : écarté.** Nous moissonnons par affiliation au périmètre, et les personnes naissent des signatures : une personne absente d'un annuaire a ses publications.

### Des versions datées plutôt que des mises à jour (Academic Observatory)

- Chaque source est chargée comme un instantané daté (tables suffixées par la date). La consolidation désigne explicitement l'instantané qu'elle lit.
- Une table de « releases » garde, par source, la date du dernier instantané traité ; un run sans nouvel instantané s'arrête au premier test.
- **Verdict : écarté.** Chaque import d'une notice écrase le précédent, et un document disparu de sa source disparaît : la base représente ce qui existe en ligne.

### Le contrôle du schéma des sources (Academic Observatory)

- Où : `compare_schemas` dans [`openalex_telescope/tasks.py`](https://github.com/The-Academic-Observatory/academic-observatory-workflows/blob/main/academic-observatory-workflows/academic_observatory_workflows/openalex_telescope/tasks.py).
- Le schéma déduit du dump est comparé au schéma attendu, versionné dans le dépôt. Un écart envoie une alerte, sans bloquer le chargement.
- **Verdict : à étudier.** Un changement de format d'une source passe inaperçu : la normalisation lit une valeur vide.

## Métadonnées

### Un fichier par champ consolidé (rialto)

- Où : [`distiller/`](https://github.com/sul-dlss/rialto-airflow/tree/main/rialto_airflow/distiller) : `title.py`, `pub_year.py`, `journal_issn.py`, `open_access.py`…
- Chaque fichier est une courte liste de règles, par ordre de priorité des sources. [`title.py`](https://github.com/sul-dlss/rialto-airflow/blob/main/rialto_airflow/distiller/title.py) fait 26 lignes.
- Pour savoir quelle source donne le titre, on ouvre le fichier de ce nom.
- **Verdict : écarté.** Chez nous, la plupart des champs suivent une règle commune (priorité des sources, union des listes), appliquée en une ligne dans `refresh_from_sources`. Les champs à règle propre (`doc_type`, `oa_status`) ont leur fonction dans `domain/publications/`.

### La notice la plus riche, par score (CRISalid)

- Où : crisalid-ikg, [`global_richest_merge_strategy.py`](https://github.com/CRISalid-esr/crisalid-ikg/blob/dev-main/app/services/documents/merge_strategies/global_richest_merge_strategy.py).
- Chaque notice reçoit un score pondéré : longueur du résumé, nombre de contributeurs, de mots-clés, présence d'une date. La mieux notée fournit les métadonnées.
- Une autre manière de choisir que la priorité fixe entre sources.
- **Verdict : écarté.** La richesse d'une notice ne dit rien de la justesse de chacun de ses champs. Les règles de choix entre sources restent champ par champ.

### L'origine de chaque champ consolidé (BiblioRef)

- Où : [`classes/interfaces/researchproduct.py`](https://gitlab.com/biblioref/harvester/harvester/-/blob/main/classes/interfaces/researchproduct.py), [`utils/fields_origin.json`](https://gitlab.com/biblioref/harvester/harvester/-/blob/main/utils/fields_origin.json).
- Les notices d'un même document sont triées par priorité de source ; pour chaque champ (titre, type, auteurs, disciplines, mots-clés, open access…), la première source qui le renseigne l'emporte.
- La source et l'identifiant de la notice retenue sont enregistrés champ par champ, dans une colonne JSON (`researchproductorigin`).
- **Verdict : en projet**, dans le chantier « Gestion des publications dans l'administration » : le volet d'une publication compare ses notices champ par champ. La règle qui choisit entre elles est déterministe : l'origine de la valeur retenue s'y lit sans être stockée.

### Des vocabulaires de synonymes, réappliqués en fin de chaîne (OpenAIRE)

- Où : [documentation](https://graph.openaire.eu/docs/graph-production-workflow/cleaning).
- Un vocabulaire associe à chaque terme la liste de ses synonymes. « Article » et « Article (author) » donnent « Article ».
- Le nettoyage est rejoué en fin de chaîne, parce que les vocabulaires changent après l'agrégation d'une source.
- **Verdict : équivalent en place.** La traduction des types de document et des langues vers notre vocabulaire se fait avec les corrections, à partir de la valeur brute de la source. Cette étape relit toutes les notices à chaque run : un synonyme ajouté ou une règle de correction modifiée s'applique au stock dès le run suivant.

### Des identifiants de rapprochement déduits (CRISalid)

- Où : svp-harvester, [`services/identifiers/rules/`](https://github.com/CRISalid-esr/svp-harvester/tree/dev-main/app/services/identifiers/rules).
- Deux règles : l'identifiant HAL tiré de l'URL, le PPN Sudoc tiré de l'identifiant ScanR (`sudoc258403519`).
- Une règle par fichier, appliquée à la notice avant tout regroupement.
- **Verdict : équivalent en place.** La normalisation tire l'identifiant HAL et le DOI des URL et des identifiants OAI, l'identifiant arXiv des URL arxiv.org (`domain/publications/identifiers.py`), avant la réconciliation. Le PPN Sudoc ne sert de clé de rapprochement à aucune de nos sources.

### Les libellés des concepts complétés (CRISalid)

- Où : svp-harvester, [`services/concepts/`](https://github.com/CRISalid-esr/svp-harvester/tree/dev-main/app/services/concepts).
- Pour un sujet fourni avec un identifiant (IdRef, Wikidata, JEL), le référentiel est interrogé et ses libellés préférés et alternatifs sont enregistrés.
- Cela unifie les libellés. Cela ne filtre pas les sujets aberrants.
- **Verdict : en projet**, dans le chantier sur la qualité des sujets : les notices stockent les codes des sujets, une table remplie depuis les référentiels des sources donne leurs libellés.

## Regroupement des publications

### La fusion par identifiant, avant le dédoublonnage (OpenAIRE)

- Où : [documentation](https://graph.openaire.eu/docs/graph-production-workflow/merge-by-id).
- Étape distincte et antérieure au dédoublonnage : regroupement par égalité stricte de l'identifiant, fusion des propriétés et des provenances.
- En cas de types contradictoires, un ordre fixe : publication, jeu de données, logiciel, autre.
- Le dédoublonnage par similarité ne traite ensuite que ce qui reste.
- **Verdict : équivalent en place.** La réconciliation regroupe les notices par égalité de leurs identifiants, ou du triplet type, titre normalisé et année, sans comparaison de similarité. Le dédoublonnage par similarité qui la suivrait est à l'étude dans le chantier de résolution avec Splink.

### Des identifiants de confiance et d'autres non (OpenAIRE)

- Où : [dédoublonnage des produits de recherche](https://graph.openaire.eu/docs/graph-production-workflow/deduplication/research-products).
- Un identifiant de confiance égal suffit à regrouper deux enregistrements.
- Un identifiant égal mais non garanti (champ `alternateid`) ne suffit pas : il faut en plus des titres similaires à plus de 0,9.
- Sans identifiant commun, le contrôle est strict : nombres d'auteurs cohérents, versions cohérentes dans le titre, titres similaires à plus de 0,95, et une part d'auteurs communs (plus de 60 % si le titre dépasse 30 caractères, plus de 90 % sinon).
- Des types incompatibles interdisent le regroupement.
- **Verdict : équivalent en place**, sous une autre forme. La correction des métadonnées efface le DOI des notices qui le partagent à tort avec une autre œuvre (ouvrage et chapitre, chapitres de titres différents). La réconciliation ne regroupe que par des identifiants corrigés.

### Le blocage et ses garde-fous (OpenAIRE)

- Clés de blocage des publications : l'identifiant ; ou le nombre d'auteurs, le nombre de mots du titre et des fragments de ses trois premiers mots.
- Dans un bloc, les enregistrements sont triés par titre et chacun n'est comparé qu'aux 50 suivants.
- Un groupe est plafonné à 200 membres.
- **Verdict : écarté.** Notre volume ne demande ni fenêtre glissante ni blocage approximatif. Un plafond de taille séparerait à tort les jeux de données de plusieurs centaines de pièces.

### Quatre étapes, une table entre chacune (dnet-dedup)

- Où : les jobs [`SparkCreateSimRels`, `SparkCreateMergeRels`, `SparkCreateDedupEntity`](https://github.com/dnet-team/dnet-dedup/tree/master/dnet-dedup-test/src/main/java/eu/dnetlib/jobs).
- Les étapes :
  1. **blocage** : des fonctions rangent les enregistrements dans des blocs de candidats ;
  2. **relations de similarité** : les paires d'un bloc sont comparées, celles qui concordent sont écrites ;
  3. **relations de fusion** : composantes connexes sur les relations de similarité, puis choix de l'identifiant du groupe ;
  4. **enregistrement représentant** : construit à partir des membres du groupe.
- Chaque étape lit ce que la précédente a écrit. Rien ne passe en mémoire de l'une à l'autre.
- **Verdict : à l'étude**, dans le chantier de résolution avec Splink : le découpage de `publications.reconcile` suivrait ces étapes.

### Un identifiant de groupe qui survit aux runs (dnet-dedup)

- Où : `SparkCreateMergeRels.java` et `IdGenerator.java`, même dossier.
- Dans chaque groupe, un enregistrement pivot est élu. L'identifiant du groupe est dérivé de celui du pivot.
- Critères d'élection : pivot déjà utilisé lors d'une génération précédente, identifiant délivré par une autorité, source (Crossref pour les publications, DataCite pour les jeux de données), date la plus ancienne, plus petit identifiant.
- Le code et la documentation ne donnent pas le même ordre pour les deux premiers critères. Non vérifié directement.
- Une table d'historique conserve les pivots pendant 12 mois.
- Quand un ancien pivot se retrouve dans un groupe mené par un autre, une relation de fusion relie l'ancien identifiant de groupe au nouveau.
- **Verdict : équivalent en place.** La réconciliation conserve la publication qui a déjà le DOI du groupe, sinon une publication à laquelle une notice du groupe est déjà rattachée. La relation de l'identifiant absorbé vers l'identifiant conservé est la table de redirection (voir « La trace de l'entité absorbée »).

### Les règles déclarées dans un fichier par type d'entité (dnet-dedup)

- Où : par exemple [`pub.new.tree.conf.json`](https://github.com/dnet-team/dnet-dedup/blob/master/dnet-pace-core/src/test/resources/eu/dnetlib/pace/config/pub.new.tree.conf.json).
- Le fichier déclare les champs, les fonctions de blocage, et un arbre de décision : à chaque nœud, un comparateur, un seuil, et la suite selon le résultat.
- Le résultat a trois valeurs : concordant, non concordant, indéterminé quand le champ manque. Chaque cas a sa branche.
- Pour les publications : identifiants égaux, sinon contrôle du type, de la version dans le titre et du nombre d'auteurs, puis titre presque identique.
- Les comparateurs sont une classe chacun, dans [`pace/tree/`](https://github.com/dnet-team/dnet-dedup/tree/master/dnet-pace-core/src/main/java/eu/dnetlib/pace/tree).
- **Verdict : écarté.** Les réglages de Splink tiennent ce rôle, y compris le cas du champ manquant, qui a son propre niveau dans chaque comparaison.

### Une liste de titres exclus du rapprochement (dnet-dedup)

- Où : la clé `blacklists` du même fichier.
- Des expressions régulières écartent les titres génériques : « Inside Front Cover », « Note from the Editor », « Poster presentations »…
- **Verdict : équivalent en place.** La clé de rapprochement par type, titre normalisé et année n'est posée que pour un titre de plus de 30 caractères, ce qui élimine les titres génériques.

## Attribution des publications aux personnes

### Les rôles des signatures (CRISalid)

- `SourcePerson` : l'auteur tel que la source le décrit.
- `SourceContribution` : son lien à la notice, avec un rôle. Le terme couvre aussi les éditeurs scientifiques et les directeurs de thèse.
- Les rôles sont ceux du vocabulaire de la Library of Congress (`aut`, `edt`…).
- **Verdict : équivalent en place.** La signature (`source_authorships`) a ses rôles, dans notre vocabulaire (`author`, `editor`, `thesis_director`…). `domain/publications/authorship_roles.py` y traduit les rôles de chaque source, dont les codes MARC Relator (Library of Congress) que fournissent HAL et ScanR.

### Le rapprochement des auteurs en deux temps (CRISalid)

- Où : crisalid-ikg, [`source_contributor_mapping_service.py`](https://github.com/CRISalid-esr/crisalid-ikg/blob/dev-main/app/services/source_contributors/source_contributor_mapping_service.py).
- Premier temps : à l'intérieur d'un document, les auteurs des différentes sources sont regroupés par similarité de nom.
- Second temps : chaque groupe est rattaché à une personne, par identifiant puis par nom.
- **Verdict : équivalent en place.** Le rattachement « cross-source » de la cascade rattache une signature à la personne de sa jumelle d'une autre source, dans la même publication et à la même position d'auteur. Il intervient avant toute création de personne.

### Un dossier par type d'indice (ReCiter)

- Où : [`algorithm/evidence/targetauthor/`](https://github.com/wcmc-its/ReCiter/tree/master/src/main/java/reciter/algorithm/evidence/targetauthor) : `name/`, `email/`, `affiliation/`, `department/`, `grant/`, `knownrelationship/`, `journalcategory/`, `degree/`…
- Chaque indice est une classe qui reçoit les articles et la personne, et rend un score.
- Les indices ne se lisent pas entre eux. Le moteur les lance en parallèle : l'ordre n'a pas d'effet sur le résultat.
- **Verdict : à l'étude**, dans le chantier de résolution avec Splink : chaque comparaison de Splink joue le rôle d'un indice.

### Chaque indice laisse une trace lisible (ReCiter)

- Où : [`ReCiterFeatureGenerator.java`](https://github.com/wcmc-its/ReCiter/blob/master/src/main/java/reciter/engine/ReCiterFeatureGenerator.java).
- Un indice n'écrit pas seulement un score. Il enregistre ce qui a concordé : l'adresse électronique trouvée, la forme du nom, l'affiliation.
- La sortie, pour chaque article, réunit le score total, la décision humaine éventuelle et la liste de ces traces. L'interface de validation les affiche.
- **Verdict : à l'étude**, dans le chantier de résolution avec Splink.

### Les indices activés et pondérés en configuration (ReCiter)

- Où : [`application.properties`](https://github.com/wcmc-its/ReCiter/blob/master/src/main/resources/application.properties).
- Une ligne par indice pour l'activer (`strategy.email=true`), une ligne par poids (`strategy.email.emailMatchScore=8`).
- Les mots-clés qui reconnaissent l'établissement dans une affiliation y sont aussi.
- **Verdict : écarté.** La cascade actuelle n'a pas de poids : elle applique des règles ordonnées, qui restent dans le code. Si Splink remplace la cascade, Splink estime les poids à partir des données : un réglage manuel est sans objet.

### Une classe par manière de chercher des candidats (ReCiter)

- Où : [`xml/retriever/pubmed/`](https://github.com/wcmc-its/ReCiter/tree/master/src/main/java/reciter/xml/retriever/pubmed) : par nom complet, par initiale, par adresse électronique, par affiliation, par financement, par ORCID.
- L'équivalent du blocage dans le couplage d'enregistrements : chaque stratégie élargit ou resserre l'ensemble des candidats.
- **Verdict : équivalent en place.** La cascade charge ses candidats par plusieurs voies réunies (identifiant fort partagé, position déjà rattachée dans une autre source, forme de nom). Avec Splink, les règles de blocage tiennent ce rôle.

### L'origine et la confiance de chaque valeur déduite (OpenAIRE)

- Où : [Crossref](https://graph.openaire.eu/docs/graph-production-workflow/aggregation/non-compatible-sources/crossref_unpaywall), [propagation](https://graph.openaire.eu/docs/graph-production-workflow/deduction-and-propagation/propagation).
- Un ORCID fourni par Crossref est étiqueté `pending_orcid`, avec une confiance de 0,9. Un ORCID obtenu par propagation est marqué « potentiel ».
- **Verdict : équivalent en place.** La fiabilité d'un identifiant dépend aussi de son origine, sans degré intermédiaire : un ORCID déposé par l'auteur est retenu (`raw_orcid` d'OpenAlex), un ORCID attribué par l'algorithme d'une source est ignoré (ORCID de WoS, `author.orcid` d'OpenAlex).

### Le rattachement des ORCID aux auteurs (OpenAIRE)

- Où : [documentation](https://graph.openaire.eu/docs/graph-production-workflow/enrichment-by-pid/orcid-enrichment).
- Le rapprochement passe par l'œuvre : on prend les œuvres déclarées dans le profil ORCID, on retrouve le produit de même identifiant, puis on compare les noms à l'intérieur de ce seul produit.
- Comparaison des noms par stratégies successives, de la plus sûre à la plus lâche : nom complet, nom inversé, mots triés avec tolérance des initiales, nom de crédit, autres noms.
- Un profil ORCID rattaché à un auteur est retiré des comparaisons suivantes.
- **Verdict : écarté.** Les œuvres d'un profil ORCID y arrivent pour l'essentiel depuis Crossref et DataCite, quand l'ORCID y est déposé. Ces dépôts sont déjà lus par nos sources. Les déclarations manuelles sont rares.

## Décisions humaines

### La fusion humaine, arête entre notices (CRISalid)

- Où : crisalid-ikg, [`equivalence_service.py`](https://github.com/CRISalid-esr/crisalid-ikg/blob/dev-main/app/services/source_records/equivalence_service.py), [`source_record_dao.py`](https://github.com/CRISalid-esr/crisalid-ikg/blob/dev-main/app/graph/neo4j/source_record_dao.py), et `merge_documents` dans [`document_service.py`](https://github.com/CRISalid-esr/crisalid-ikg/blob/dev-main/app/services/documents/document_service.py).
- L'étiquette concerne une arête entre deux notices, pas le groupe :
  - `INFERRED_EQUIVALENT` : déduite des identifiants partagés, recalculée librement ;
  - `ASSERTED_EQUIVALENT` : posée par une fusion humaine, jamais recalculée ;
  - `PREDICTED_EQUIVALENT` : lue par le code, créée nulle part pour l'instant.
- Le groupe est la composante connexe sur les trois types d'arêtes. Le document en est la matérialisation.
- Fusionner A et B crée une arête affirmée entre chaque notice de A et chaque notice de B, puis relance le calcul des composantes. La fusion contraint le calcul.
- **Verdict : en projet**, dans le chantier « Gestion des publications dans l'administration ». Une décision humaine sur un lien est une entrée de la résolution. Pour les publications, un jeton de fusion forcée posé sur des notices jouerait le rôle de l'arête affirmée : une clé commune, prise en compte par le même regroupement. CRISalid n'a pas de contrainte de scission.

### Les décisions humaines entrent entre les étapes 2 et 3 (dnet-dedup)

- Où : dans le code actuel, les jobs `SparkCopyOpenorgsSimRels`, `SparkCopyOpenorgsMergeRels` et `SparkWhitelistSimRels` ([dossier](https://code-repo.d4science.org/D-Net/dnet-hadoop/src/branch/master/dhp-workflows/dhp-dedup-openaire/src/main/java/eu/dnetlib/dhp/oa/dedup)). Le dernier n'a pas pu être lu.
- Pour les organisations, l'algorithme produit des suggestions. Des curateurs les approuvent, les écartent, ou créent une relation que l'algorithme n'a pas vue ([documentation](https://graph.openaire.eu/docs/data-provision/deduplication/organizations)).
- Ces décisions sont des relations ajoutées ou retirées avant le calcul des composantes.
- **Verdict : à l'étude**, dans le chantier de résolution avec Splink.

### Les décisions humaines servent trois fois (ReCiter)

- **Elles s'imposent.** Un article accepté ou rejeté garde son statut quel que soit son score.
- **Elles deviennent des indices pour les autres articles.** Où : [`evidence/targetauthor/feedback/`](https://github.com/wcmc-its/ReCiter/tree/master/src/main/java/reciter/algorithm/evidence/targetauthor/feedback). Pour un candidat, on compte les articles déjà acceptés et rejetés de la même personne qui partagent sa revue, un co-auteur, un mot-clé, une institution, une citation. Quinze indices de ce type.
- **Elles servent à entraîner et à mesurer.** Où : [`resources/scripts/`](https://github.com/wcmc-its/ReCiter/tree/master/src/main/resources/scripts) et [`Analysis.java`](https://github.com/wcmc-its/ReCiter/blob/master/src/main/java/reciter/engine/erroranalysis/Analysis.java). Les scores des indices sont combinés par un petit réseau de neurones entraîné sur les acceptations et les rejets. La précision et le rappel sont calculés contre ces mêmes décisions.

- Pour l'entraînement, le score d'un article est calculé sans sa propre décision, pour qu'elle ne s'explique pas par elle-même.
- **Verdict : en place** pour la première : les confirmations et les rejets sont des entrées de la résolution. Les deux autres sont à l'étude dans le chantier de résolution avec Splink.

### Les corrections de champs stockées à part (CRISalid)

- Où : crisalid-ikg, [`change_service.py`](https://github.com/CRISalid-esr/crisalid-ikg/blob/dev-main/app/services/changes/change_service.py) et [`processors/`](https://github.com/CRISalid-esr/crisalid-ikg/tree/dev-main/app/services/changes/processors).
- Titre, résumé, type et sujets corrigés sont des nœuds attachés au document, réappliqués après chaque recalcul à partir des notices.
- Le résultat est le même qu'une saisie humaine prioritaire. Ce qui compte : la valeur humaine n'est jamais stockée seulement dans la colonne dérivée.
- **Verdict : équivalent en place** pour les revues et les éditeurs. Une correction de revue est écrite dans la colonne, et le champ est marqué (`manual_fields`) : le pipeline n'écrit plus un champ marqué. Le pipeline remplit seulement les champs vides d'un éditeur. La correction des publications reste à faire, dans le chantier « Gestion des publications dans l'administration ».

### Le verrouillage (BiblioRef)

- Une publication ou un auteur a un booléen `locked`. Une publication verrouillée n'est plus touchée par le dédoublonnage.
- C'est le troisième mécanisme de la gestion des données de référence (après la source prioritaire et la contrainte de la résolution), avec sa limite : la publication ne reçoit plus les mises à jour des sources.
- **Verdict : écarté.** Une décision humaine vise un champ ou un lien, pas l'entité entière : le reste de l'entité suit les sources.

### La trace de l'entité absorbée (CRISalid)

- Où : crisalid-ikg, [`create_or_update_document.cypher`](https://github.com/CRISalid-esr/crisalid-ikg/blob/dev-main/app/graph/neo4j/queries/create_or_update_document.cypher).
- Le document absorbé reçoit une arête `TO_BE_MERGED_INTO` vers celui qui survit.
- **Verdict : adopté**, pour les entités qui ont une page publique : une table de redirection des identifiants absorbés, écrite par chaque fusion. À faire avant la mise en production de l'interface publique.

## Structures et affiliations

### L'alignement des affiliations sur ROR (OpenAIRE)

- Où : [documentation](https://graph.openaire.eu/docs/graph-production-workflow/enrichment-by-mining/affiliation_matching).
- Méthode : classer l'affiliation (université, laboratoire, hôpital, entreprise), raccourcir la chaîne autour de ses mots-clés, comparer aux noms de ROR par similarité cosinus, puis départager les homonymes avec la chaîne complète.
- Seuils : 0,64 pour les universités, 0,87 pour les autres.
- **Verdict : écarté.** Les sources fournissent le ROR des organisations des signatures (OpenAlex pour quasiment toutes, WoS pour 98 %).

### Des affiliations élargies par la hiérarchie de ROR (Academic Observatory)

- Où : `doi.sql.jinja2` et `create_ror_hierarchy_table` dans [`doi_workflow/tasks.py`](https://github.com/The-Academic-Observatory/academic-observatory-workflows/blob/main/academic-observatory-workflows/academic_observatory_workflows/doi_workflow/tasks.py).
- Une table matérialise, pour chaque organisation ROR, tous ses ascendants. Une publication est attribuée à l'organisation de l'auteur et à toute sa généalogie.
- **Verdict : à l'étude**, dans le chantier sur les collaborations entre structures : l'agrégation des organisations des co-auteurs par ROR cité, ou par établissement obtenu en remontant la hiérarchie de ROR.

### La manière dont une structure a été attribuée (BiblioRef)

- Où : [`classes/interfaces/structure.py`](https://gitlab.com/biblioref/harvester/harvester/-/blob/main/classes/interfaces/structure.py), [`utils/structurechoice.py`](https://gitlab.com/biblioref/harvester/harvester/-/blob/main/utils/structurechoice.py).
- Chaque lien signature-structure a un code, qui dit comment il a été établi. Les valeurs : saisie manuelle, fourni par la source, appartenance datée de la personne dans l'annuaire à la date de publication, structure de l'annuaire retrouvée parmi celles de la signature, structure du périmètre, ou premier type de structure dans un ordre fixe (laboratoire, unité, établissement…).
- **Verdict : équivalent en place.** Un lien entre adresse et structure a la forme de nom qui l'a établi, ou aucune s'il est manuel, et son statut de confirmation.

### Un annuaire riche (BiblioRef)

- Où : [`bdd`](https://gitlab.com/biblioref/saas-app/bdd), fichier `1_Création/biblioref.sql`.
- Pour chaque personne : appartenances datées aux structures, grades, diplômes, disciplines, sections, mots-clés, identifiants.
- Pour chaque structure : tutelles typées (principale ou non), formes de nom, et un historique des créations, fusions et scissions (`structurecreation`, avec les structures d'origine).
- **Verdict : à étudier.** Nos structures n'ont pas d'historique : une fusion de laboratoires n'est pas gérée. Un historique des fusions et des scissions, prolongé vers le passé, rattacherait une publication ancienne à l'unité qui a succédé à son laboratoire.

## Ce qu'on écarte en bloc

### CRISalid

- **L'enchaînement par événements et RabbitMQ**. Adapté à un usage interactif et à des règles locales. Avec une résolution qui compare des noms sur tout le corpus, le traitement notice par notice serait lent et dépendrait de l'ordre d'arrivée.
- **Les DAO génériques à une seule implémentation** : une interface et une classe pour chaque accès aux données, sans seconde implémentation.
- **Une classe par type de message**. Une trentaine de fichiers pour émettre des événements.
- **Le type élu par ordre des sources**. Le premier type connu gagne, sans règle de cohérence.
- **La liste entière des contributeurs remplacée par la dernière correction**. Nos confirmations et rejets visent un lien à la fois.
- **Le dédoublonnage par identifiants seuls**. Aucun rapprochement par titre.
- **Le lien structure-publication par l'appartenance des personnes**. Les publications d'un laboratoire sont celles de ses membres dans l'annuaire, sans lecture des adresses.

### rialto

- **Le traitement publication par publication en Python** (`distill.py`). Convient à leur volume, pas à nos étapes ensemblistes.
- **Le dédoublonnage par identifiants seuls**. Aucun rapprochement par titre.

### ReCiter

- **Une classe de contexte par indice**, de 11 à 30 lignes, qui ne fait que déléguer. En Python, une fonction par indice suffit.
- **L'appel du modèle par un script Python lancé depuis Java**, avec échange de fichiers.
- **L'infrastructure** : DynamoDB, S3 et files SQS d'Amazon.

### dnet-dedup

- **Spark, Oozie et Java** : dimensionnés pour des centaines de millions d'enregistrements.

### Academic Observatory

- **BigQuery, Google Cloud, Astronomer, Kubernetes** : dimensionnés pour des dumps de plusieurs centaines de gigaoctets.
- **Le DOI comme seule clé** : rien pour les documents sans DOI, ni pour un DOI erroné.
- **Les affiliations d'OpenAlex reprises telles quelles** : aucune lecture des adresses.

### BiblioRef

- **La date de publication au jour près comme condition du dédoublonnage** : deux sources donnent souvent des dates différentes pour le même document.
- **La suppression puis la recréation de la publication à chaque fusion** : identifiant instable, décisions perdues.
- **Le rattachement d'auteurs par égalité de nom, sans contrôle des homonymes.**
- **La comparaison de chaque notice à tout le stock en mémoire.**
- **Le code commun recopié dans chaque connecteur**, au lieu d'une bibliothèque partagée.
- **Les corrections écrites dans les tables du moissonneur**, protégées seulement par le verrou.

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
- **[biblioref (GitLab)](https://gitlab.com/biblioref)** — université Jean Moulin Lyon 3, développé par DyoNeo. Python pour le moissonneur (2 600 lignes) et les connecteurs (2 400 à 4 100 lignes chacun), Node.js (25 700 lignes de TypeScript) et Angular pour l'application, PostgreSQL. Lus, depuis des archives : [`harvester`](https://gitlab.com/biblioref/harvester/harvester), [`connector-base`](https://gitlab.com/biblioref/connectors/connector-base), [`connector-hal`](https://gitlab.com/biblioref/connectors/connector-hal), [`connector-openalex`](https://gitlab.com/biblioref/connectors/connector-openalex), [`connector-sudoc`](https://gitlab.com/biblioref/connectors/connector-sudoc), [`awesome-biblioref`](https://gitlab.com/biblioref/awesome-biblioref/awesome-biblioref). Un seul commit par dépôt, septembre 2025. Puis [`bdd`](https://gitlab.com/biblioref/saas-app/bdd) et [`backend`](https://gitlab.com/biblioref/saas-app/backend). Non lu : `frontend`. Présentation : [*Arabesques*](https://publications-prairial.fr/arabesques/index.php?id=4433).

### Repérés, non lus

- **[dataesr/affiliation-matcher](https://github.com/dataesr/affiliation-matcher)** — alignement d'une affiliation brute sur ROR et le RNSR.
- **[ourresearch/openalex-walden](https://github.com/ourresearch/openalex-walden)** — pipelines d'OpenAlex, sur Databricks.
- **[conditor-project](https://github.com/conditor-project)** — dédoublonnage de la production française, Inist. État de maintenance non vérifié.
