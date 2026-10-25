# Chantier — Modèle des conteneurs

## Contexte

Le conteneur d'une publication est ce qui la publie ou l'héberge. Le schéma en donne trois représentations :

- `publishing.journals`, que référence `publications.journal_id` ;
- `publishing.monographs`, que référence `publications.monograph_id` : livres et volumes d'actes, avec ou sans ISBN, avec un `journal_id` vers leur collection ;
- `publications.container_title`, un titre libre quand aucune des deux tables ne convient.

Le chantier [Monographies](2026-10-25_DATA_monographies.md) sépare les livres et les volumes d'actes, dans `monographs`, des séries dont ils font partie, dans `journals`.

`journals` réunit encore des choses de natures différentes. Son type (`journal_type`) vaut :

- `journal`, `book_series`, `proceedings`, `media` : des publications en série ;
- `repository`, `preprint_server`, `ebook_platform` : des localisations, qui hébergent des publications sans les publier ;
- `unknown`.

Les colonnes de `journals` décrivent une revue : présence dans le DOAJ, modèle open access, APC. Elles n'ont pas de sens pour un entrepôt. Le modèle open access (`oa_model`) a une valeur propre aux entrepôts, `repository`.

Le nom `journals` couvre ainsi des collections d'ouvrages, des serveurs de prépublications et des entrepôts de données. Il désigne mal son contenu.

### Localisations

Une publication désigne une version d'une œuvre. Un preprint forme une publication distincte, reliée à l'article par `is_preprint_of`. Une copie déposée de la version publiée rejoint la publication de l'article.

Trois sources décrivent les localisations d'un document :

- OpenAlex donne le lieu, l'URL, la version (`submittedVersion`, `acceptedVersion`, `publishedVersion`) et la licence de chaque localisation. La normalisation garde les URL, les identifiants et la licence de la localisation principale.
- Crossref donne la cible de résolution du DOI (`resource.primary.URL`) et les URL du texte intégral (`link`). La normalisation ne les lit pas.
- Unpaywall donne les localisations en open access. Le pipeline lit seulement son statut open access.

Localisations OpenAlex du raw store local : 105 586 works, 322 036 localisations.

- 97 % des localisations ont un lieu. OpenAlex range parmi les entrepôts des index (DOAJ) et des agrégateurs (Europe PMC).
- 40 % des works réunissent plusieurs versions.
- Les localisations d'entrepôt sont presque toutes en `submittedVersion` (200 949 sur 258 875), y compris dans HAL pour des articles publiés, et dans Cairn, qui héberge des versions publiées. Leur version est donc peu fiable.
- Sur 6 080 localisations arXiv en `submittedVersion` d'une publication autre qu'un preprint, 5 051 désignent un preprint qui n'a pas de publication propre.

Test de l'API Unpaywall sur 120 DOI du périmètre, tirés au hasard :

- les 104 DOI Crossref ont une réponse, les 16 DOI DataCite aucune ;
- Unpaywall donne seulement les localisations en open access : 25 DOI n'en ont aucune ;
- une localisation comporte le type d'hébergeur (`publisher` ou `repository`), la version, la licence, l'URL de la page et du PDF, la date d'ouverture, et pour un entrepôt son institution et son identifiant (`endpoint_id`, présent sur 367 localisations d'entrepôt sur 396) ;
- les versions suivent la répartition d'OpenAlex : 330 localisations d'entrepôt sur 396 sont en `submittedVersion`, PubMed Central compris ;
- la date de publication est au jour pour 86 DOI, au 1er janvier pour 18.

### Éditeur d'une publication

Une publication a l'éditeur de sa revue : ni `publications` ni `source_records` n'ont de `publisher_id`. Quand une revue change d'éditeur, ses anciens articles passent au nouvel éditeur. L'enregistrement source garde le nom d'éditeur de la source dans `biblio.publisher`, sans le rattacher à `publishers`. Ce nom est présent dans tous les enregistrements Crossref et DataCite, 92 % des WoS, 64 % des ScanR, 56 % des HAL et 38 % des OpenAlex. Chez Crossref, c'est le membre actuel ; chez DataCite, souvent la plateforme (« arXiv »).

Mesure sur une base proche de la production (`measure_journal_publisher_changes`) : 42 revues ont deux éditeurs de préfixe DOI sur des périodes disjointes, pour 719 publications. 315 d'entre elles ont un éditeur de préfixe différent de celui de la revue (*animal* : Cambridge jusqu'en 2020, Elsevier ensuite). L'ISSN rattache ces publications à la même revue, donc aucun doublon de revue n'apparaît.

Trois données désignent l'éditeur d'un DOI Crossref :

- **Le titulaire du préfixe** (`doi_prefixes`) reste l'éditeur d'origine.
- **Le membre qui détient le DOI** (`member`, `publisher`) change avec la revue. Les DOI d'*animal* en 10.1017, préfixe de Cambridge, sont détenus par Elsevier. Sur les 37 250 enregistrements Crossref du raw store local, 1 519 ont un membre autre que le titulaire du préfixe, dont 1 181 hors des 42 revues. Les principaux cas : bioRxiv et medRxiv passés à openRxiv (442), Research Square à Springer (213), revues vendues (de BMJ, Springer, Cambridge et OUP à Elsevier, de Hindawi à Wiley, de Lavoisier à JLE).
- **Le domaine de résolution** désigne l'hébergeur : `agupubs.onlinelibrary.wiley.com` pour l'American Geophysical Union, `linkinghub.elsevier.com` pour l'American Dairy Science Association, `books.openedition.org` pour les presses universitaires. Il désigne parfois le propriétaire : `comptes-rendus.academie-sciences.fr`, pour les revues que Centre Mersenne héberge. Le raw store compte 1 459 domaines. 50 couvrent 82 % des enregistrements, 200 en couvrent 92 %.

Le membre Crossref est tantôt la société savante (AGU), tantôt l'éditeur commercial (OUP pour *Plant Physiology*, revue de l'ASPB), tantôt la plateforme (Centre Mersenne, OpenEdition). Sur 6 609 revues à publications Crossref, 6 446 ont un seul éditeur de préfixe. 1 995 d'entre elles ont un autre éditeur en base, pour 6 045 publications. Dans 1 818 de ces cas, l'éditeur de la revue n'a aucun membre Crossref.

### Inventaire

Mesure du 2026-10-24, sur une base proche de la production :

| `journal_type` | Entrées | Avec ISSN | Publications | Monographies rattachées |
|---|---|---|---|---|
| `journal` | 9 663 | 9 355 | 37 732 | 168 |
| `unknown` | 778 | 446 | 2 277 | 4 |
| `book_series` | 250 | 240 | 870 | 540 |
| `proceedings` | 180 | 96 | 1 147 | 760 |
| `media` | 44 | 33 | 633 | 0 |
| `ebook_platform` | 39 | 1 | 68 | 1 |
| `preprint_server` | 4 | 2 | 242 | 0 |
| `repository` | 3 | 1 | 175 | 0 |

- **Localisations.** Elles comptent peu d'entrées, car deux normaliseurs les écartent. OpenAlex ne cherche aucune revue quand la localisation principale est un entrepôt, HAL, theses.fr ou une plateforme d'ebooks (`should_skip_publisher_serial`). DataCite garde seulement les conteneurs qui désignent une revue (`container_names_a_journal`). Restent SSRN (172 publications), bioRxiv (205), Research Square (trois entrées, dont une `unknown` de 87 publications), medRxiv et ChemRxiv (`unknown`), Preprints.org, ArXiv.org, Zenodo (`journal`).
- **`ebook_platform`.** 38 entrées sur 39 sont des sources OpenAlex au nom d'un éditeur suivi de « eBooks » (« ENS Éditions eBooks »). Elles désignent un éditeur, pas un lieu.
- **`unknown`.** 61 entrées sont les universités qui délivrent les thèses ScanR (« Université Clermont Auvergne (2021-...) », « Lyon », « Normandie »), avec l'ABES pour éditeur, soit 1 395 publications.
- **`media`.** Ce sont des publications en série : *The Conversation France* (378), *Revue Politique et Parlementaire* (102), *Le Monde*.
- **Deux codages des localisations.** Le type (`journal_type`) et le modèle open access `repository` se contredisent. Seuls bioRxiv, Research Square et ArXiv.org ont `oa_model = repository`, contre SSRN, medRxiv et Research Square typé `unknown`.
- **Localisations hors de `journals`.** 57 990 publications ont un identifiant HAL, 5 256 un PMCID, 5 051 un identifiant arXiv, 2 109 un NNT, 74 533 des URL. 22 726 publications ont seulement un `container_title` : colloque, livre ou archive.

Usages du type dans le code :

- **Espaces de noms DOI** : aucun pour `repository`, `preprint_server`, `ebook_platform` et `book_series` (`domain/serials/doi_namespaces.py`).
- **Typage** : l'enrichissement OpenAlex type seulement une entrée `unknown` (`repository`, `conference`, `book series`, `ebook platform`). `type_proceedings_serials` et `link_monographs_to_collections` posent `proceedings` et `book_series`. La vérification Sudoc traite `proceedings` et `book_series` comme des séries de volumes (`holds_volumes`).
- **Corrections du type de document** : `media` donne `media`, `proceedings` donne `conference_paper`, `preprint_server` donne `preprint` (`domain/source_records/metadata_correction/rules.py`). La fusion de deux revues requalifie les publications absorbées d'après le type de la cible.
- **Open access** : statuts attendus selon `oa_model`, types de document attendus selon `journal_type`, pour le tableau de bord d'une revue (`domain/serials/expected.py`).
- **DOAJ et APC** : ils concernent en pratique les seules entrées `journal`. 2 266 sont dans le DOAJ et 3 725 ont des APC, contre 54 et 2 pour les autres types.
- **Interface** : libellé du type, choix du type dans l'administration, liste des recueils d'actes probables.

### Points des autres fiches que le modèle conditionne

- [Conférences et actes](2026-10-25_DATA_conferences-et-actes.md) : noms d'archive dans `container_title`, retypage des séries d'actes typées `journal` ou `book_series`.
- [Revues divergentes selon les sources](2026-10-25_DATA_revues-divergentes-entre-sources.md) : couples d'une revue et d'un dépôt ou d'un serveur de preprints ; correction de la revue d'après Crossref, qui remplacerait une localisation par une revue.
- [Monographies](2026-10-25_DATA_monographies.md) : conversion d'une entrée de `journals` en monographie dans l'administration, documentation.

## Décisions

- Trois natures distinctes :
  - publication en série : revue, collection d'ouvrages, série d'actes ;
  - publication isolée : monographie, livre ou volume d'actes, rattachée ou non à une série ;
  - localisation : entrepôt, serveur de prépublications, plateforme.
- Les localisations sortent de `journals`.
- Schéma :
  - `publishers` et `doi_prefixes`, inchangées. Le titulaire d'un préfixe est l'éditeur d'origine de ses DOI ;
  - `serials`, à la place de `journals` : revues, collections d'ouvrages, séries d'actes, médias. Les ISSN, les formes de nom, les espaces de noms DOI, le DOAJ, les APC et le modèle open access y restent. L'éditeur est une colonne dérivée, recalculée à chaque run : la liste des revues trie et filtre par éditeur ;
  - `monographs` : livres et volumes d'actes, rattachés à leur série (`serial_id`) ;
  - `platforms` : lieux qui hébergent des publications. Type (`repository`, `preprint_server`, `publisher_platform`, `unknown`), nom et identifiant de la source OpenAlex. Une archive et un entrepôt de données sont des `repository`, que le type de document distingue. Un document déposé sur un serveur de preprints est un preprint ; un entrepôt ne dit rien du type de ses documents ;
  - `platform_domains` : domaine → plateforme, plateforme nullable ;
  - `source_record_locations` : localisations d'un enregistrement source, réécrites à chaque normalisation. URL de la page et du PDF, identifiant OAI-PMH, version dans le vocabulaire de la source, licence, open access, plateforme nullable. OpenAlex les alimente, puis Crossref ;
  - `publisher_id` sur `source_records` et `publications`, écrit par l'agrégation : le titulaire du préfixe pour un DOI Crossref, à défaut l'éditeur que donnent les sources ;
  - `doi_prefix`, colonne générée de `publications`, pour les jointures sur `doi_prefixes`.
- L'éditeur d'une série est celui de ses publications les plus récentes : le plus fréquent parmi ses publications de la dernière année qui en a un ; à égalité, le plus fréquent sur toutes les années ; à égalité encore, le plus petit identifiant. Une publication a donc l'éditeur à la date de sa publication. Une forme de nom de revue garde l'éditeur que nomme la source avec ce titre : c'est une observation, qui distingue deux revues homonymes.
- Une production hébergée sans être publiée n'a pas d'éditeur : preprint, jeu de données, dépôt. La plateforme qui l'héberge n'en est pas l'éditeur, comme le CCSD pour HAL.
- Noms : `serials` dans le schéma, le code et l'API ; « Publications en série » dans l'administration, qui veut le nom exact. Les pages publiques gardent le terme courant, « Revues », et l'adresse `/journals`. La phase qui enrichit les référentiels de l'édition prend le nom de leur schéma, `publishing`.
- Une plateforme prend le nom et l'identifiant de sa source OpenAlex. Aucune plateforme n'est créée sans nom fiable : les noms d'institution d'Unpaywall sont erronés (« Asklepios Klinik St. Georg » pour l'archive de Göttingen).
- Unpaywall donne seulement le verdict open access. OpenAlex couvre 99 % des publications à DOI Crossref, et donne aussi les copies fermées et le nom des entrepôts.
- Une fiche de catalogue sans copie du texte n'est pas une localisation : le DOAJ (`doaj.org/article`) est écarté.
- Les plateformes connues forment une liste fermée dans le code, plutôt qu'un seuil sur les données ou une table remplie par le seed : des règles en dépendent, elle change peu, et les plateformes d'éditeurs n'ont pas de source OpenAlex. La part de preprints par plateforme ne sépare pas les serveurs des entrepôts (bioRxiv 66 %, arXiv 24 %, OSF Preprints 22 %, Zenodo 9 %), l'attribution de DOI propres non plus (Zenodo, Figshare). Les plateformes d'éditeurs ont été repérées par une mesure : un titulaire de préfixe dont les revues ont presque autant d'éditeurs distincts que de revues, d'après HAL, et que HAL ne nomme pour aucune.

## Phasage

### Phase 1 — Inventaire

- [x] Revues qui changent d'éditeur, d'après le préfixe DOI de leurs publications (`f02277482`).
- [x] Membre qui détient les DOI Crossref et domaine de résolution, sur le raw store.
- [x] Localisations OpenAlex par lieu et par version, sur le raw store.
- [x] Répartition des entrées de `journals` par type, et des publications rattachées.
- [x] Usages de chaque nature : normalisation, rattachement par préfixe DOI, enrichissements, statut open access, APC, interface.

### Phase 2 — Éditeur des publications

- [x] Migration : `publications.doi_prefix`, colonne générée ; `publisher_id` sur `source_records` et `publications` (`b123a7487`).
- [x] Normalisation : l'enregistrement source reçoit l'éditeur que nomme sa source. Pas d'éditeur pour les types `preprint`, `dataset`, `software`, `report`, `thesis`, `ongoing_thesis`, `hdr`, `memoir`, `poster`, `conference` et `patent`, ni pour un enregistrement DataCite sans série ni monographie (`b123a7487`).
- [x] Agrégation : la publication reçoit le titulaire du préfixe de son DOI Crossref, à défaut le premier éditeur non nul dans l'ordre de priorité des sources. Pas d'éditeur pour les mêmes types (`b123a7487`).
- [x] Suppression des éditeurs vides et fusion d'éditeurs : prise en compte des éditeurs des enregistrements sources et des publications (`b123a7487`).
- [x] Stock : oneshot `backfill_source_record_publishers` depuis `biblio.publisher`, puis phase `publications`. 46 139 publications ont un éditeur ; 9 242 diffèrent de celui de leur revue.

### Phase 3 — Plateformes et localisations

- [x] Migration : `platforms`, `source_record_locations` (`8d0a6ca00`).
- [x] Normalisation OpenAlex : localisations, plateforme trouvée ou créée pour une source de type `repository` (`8d0a6ca00`).
- [x] Stock : réhydratation du staging OpenAlex et renormalisation. 303 477 localisations sur 105 496 des 111 022 enregistrements OpenAlex, 1 366 plateformes.
- [x] Localisation Crossref : la page de résolution du DOI (`resource.primary.URL`) ; les URL de `link`, points d'accès pour la fouille de texte, sont ignorées (`9ca9efccf`).
- [x] Stock : réhydratation du staging Crossref et renormalisation. 37 123 des 41 889 enregistrements Crossref ont leur localisation, 12 421 avec une licence.
- [x] Vérification Unpaywall : DOI DataCite écartés (`e1d7daeb6`).
- [x] Liste fermée des plateformes connues, dans le domaine (`domain/platforms/registry.py`) : serveurs de preprints et plateformes d'éditeurs. Une plateforme prend le type de la liste, à défaut entrepôt. Le bilan Science ouverte la lit (`b72bc40b1`).
- [x] Préfixe DOI d'une plateforme d'éditeurs : ni son titulaire ni un enregistrement source qui le nomme ne donnent l'éditeur de la publication, qui vient des autres sources (`b72bc40b1`).
- [x] Stock : oneshot `apply_known_platforms`, puis phase `publications`. 23 serveurs de preprints. Sur 4 834 publications à préfixe de plateforme d'éditeurs, 4 240 ont un éditeur, aucune la plateforme ; 584 articles de revue restent sans éditeur (OpenEdition 316, Cairn 238). « OpenEdition Journals » (109 publications) est une variante de nom d'OpenEdition, que la fusion de la phase 7 résout.
- [ ] Entrées de `serials` de type `repository` et `preprint_server` converties en plateformes ; valeur `repository` du modèle open access retirée.
- [ ] Domaine → plateforme appris depuis les localisations OpenAlex, quand un usage le demande.

### Phase 4 — Lectures de l'éditeur

- [x] Éditeur d'une publication lu sur la publication : listes, détail, facette, filtres, tableaux croisés, page d'un éditeur et `publishers.publication_count`. Les enregistrements sources montrent l'éditeur que nomme leur source (`137b396ae`).
- [x] Éditeur d'une revue calculé d'après ses publications les plus récentes, dans `finalize` ; la création d'une revue ne le pose plus (`10e964608`).
- [x] Stock : phase `finalize`.

### Phase 5 — Séries

- [x] Renommage de `journals` en `serials`, et de `monographs.journal_id` en `serial_id` (`f73c03b0e`, `947a58f45`). La migration réécrit les valeurs stockées : saisies manuelles, redirections, audit, corrections, métriques de l'historique des phases.
- [x] Phase `publishers_journals` renommée `publishing`, du nom du schéma et du paquet qui portent ses référentiels (`e8655117a`).
- [x] Plateformes d'ebooks. Un titre « … eBooks », nom qu'OpenAlex donne à la plateforme d'ebooks d'un éditeur et que ScanR reprend comme revue, n'est le titre d'aucun conteneur. Une localisation principale OpenAlex sur une plateforme d'ebooks donne l'éditeur de son organisation hôte (`d153cf532`). Type `ebook_platform` retiré (`48fbf4cf0`).
- [x] Stock : oneshot `detach_ebook_platforms` (46 revues, 83 enregistrements sources détachés, 4 043 titres de conteneur retirés), puis phases `publications` et `finalize`.
- [x] Une entrée de type inconnu présente dans le DOAJ devient une revue : 52 entrées `unknown` y sont. Les autres enrichissements touchent seulement des revues, sauf une dizaine d'entrées (`865aeaf95`).
- [x] Localisations HAL : la page du dépôt et le fichier déposé, ouverte quand un fichier est déposé hors embargo (`5a6223609`). Localisations tirées des identifiants arXiv et PMCID, quelle que soit la source ; une plateforme connue prend le nom de la liste (`24f0d24f1`).
- [x] Accès d'une publication d'après ses localisations : meilleure copie ouverte de chaque plateforme, par version puis par ordre d'arrivée ; sur HAL, la copie que donne HAL décide de l'ouverture. Le bouton « Accéder » mène à la meilleure copie, à défaut au DOI ; la liste omet la copie désignée par le DOI. « Référencé par » remplace la liste des sources : toutes sauf Crossref et DataCite, et HAL quand HAL figure parmi les liens d'accès. Les adresses des copies échappent à la règle des hôtes écrits dans le code ; le serveur en vérifie le schéma (`c23128941`, `7b06e34f7`, `bac85aabe`).
- [x] Stock : oneshot `apply_known_platforms` (noms des plateformes connues), puis réhydratation et renormalisation de HAL et d'OpenAlex, seules sources qui portent des identifiants arXiv et PMCID.

### Phase 6 — Documentation

- [x] Mise à jour de `docs/donnees`, `docs/pipeline` et `docs/agregats`, dont la fiche [plateformes et localisations](../../agregats/platforms.md).

### Phase 7 — Défauts antérieurs au chantier

- [x] Éditeurs en double : un éditeur que nomment les sources rejoint le titulaire Crossref de ses préfixes quand au moins 5 de ses enregistrements sources, dont 90 % chez ce titulaire, et des noms compatibles concordent ; 155 fusions sur la base locale (`1e5903a17`). Les marques et les éditeurs rachetés restent distincts (BioMed Central, Birkhäuser, Mary Ann Liebert).
- [x] Oneshot `merge_publisher_aliases` : 57 autres noms qui résistent à la règle (Taylor & Francis et Informa UK, OpenEdition Journals et OpenEdition, AIP, Optica, SPIE…), ici puis en production.
- [x] Entrées de type inconnu dont la majorité stricte des documents sont des articles, d'après le type donné par chaque source : typées revues (563 sur 773 entrées `unknown` de la base locale).
- [x] Thèses ScanR : l'université de soutenance ne donne ni publication en série ni titre de conteneur. 1 452 enregistrements de thèses ScanR rattachés à 66 entrées, dont 60 n'ont pas d'autre usage.
- [x] Stock : réhydratation et renormalisation de ScanR, puis phases `publications` et `finalize`.
- Type des preprints arXiv et exclusion des preprints des statistiques : chantier [Preprints et versions d'une publication](../DATA_preprints-et-versions.md).

## Questions ouvertes

- Sort des entrées `unknown` restantes, qui ne contiennent en majorité ni articles ni articles de congrès : environ 150 sur la base locale.
- Lien entre une localisation et le statut open access d'une publication (dépôt HAL, prépublication).
- **Maintenance des référentiels.** Chaque table a son régime : recalcul à chaque run, mise à jour incrémentale par file d'attente, ou valeur posée une fois (typage OpenAlex, `doi_prefixes`). Comment rafraîchir une valeur posée une fois ? `doi_prefixes` attribue à Hindawi un préfixe dont Wiley détient les DOI.
- **Responsabilité scientifique et éditeur commercial.** Faut-il distinguer les deux rôles ? Le membre Crossref et le domaine de résolution les séparent dans une partie des cas.
- **Éditeur d'une revue d'après le Sudoc.** La notice Sudoc de l'ISSN donne les éditeurs successifs et leurs périodes (zone 214, à défaut 210, sous-zones `c` et `d`) : *Multitudes*, Éditions Exils (2000-2004), Multitudes (2004-2006), Éditions Amsterdam (2006-2011), Éditions Inculte (depuis 2012). C'est la seule source qui nomme l'éditeur d'une revue diffusée par une plateforme. Limites relevées : notices sans zone d'éditeur (*animal*, *Annals of Oncology*, *Revue européenne des sciences sociales*), périodes qui se chevauchent (*Finance* : Presses universitaires de France 1982-2023, Presses universitaires de Grenoble 2005-2023). La revérification Sudoc des revues relirait ces zones. Mesure sur les 584 articles à préfixe de plateforme sans éditeur, de 233 revues : 476 ont un éditeur Sudoc pour leur année, 55 une zone d'éditeur sans période qui couvre l'année, 49 une notice sans zone d'éditeur, 4 aucune notice. 233 ont plusieurs éditeurs pour l'année : la notice garde la première mention, à date ouverte (« Féret & Fils 1899- »), à côté des suivantes (« Éditions Bière 1972- »). Retenir la mention la plus récente qui couvre l'année en laisse 37 ambiguës, dont des imprimeurs et des diffuseurs (« Corlet impr. », « diff. Belin »). Les noms sont les formes du catalogue (« Éd. Eska », « Féret & Fils [etc.] ») : rattachés par leurs formes de nom, ils créeraient des variantes d'éditeurs existants. HAL et ScanR donnent déjà ces mentions pour éditeur : 148 éditeurs de la base sont des mentions de catalogue à éditeurs successifs (« Éditions Techniques [1987-1994] - Éditions du Juris-classeur [1995-2004] - LexisNexis [2005-....] »), pour 1 155 publications. 130 se découpent en segments nom et période ; retenir le segment de l'année de publication les ramènerait à leurs éditeurs.
- **Double série.** Un volume LIPIcs appartient à la collection LIPIcs, qui a un ISSN, et à la série de son congrès (STACS, SoCG, ICALP). `monographs.serial_id` en désigne une seule : laquelle ?
- **Ouvrage en plusieurs volumes** (« Current Developments in Biotechnology and Bioengineering »). Chaque volume est-il une monographie, et qu'est-ce qui les relie ?
