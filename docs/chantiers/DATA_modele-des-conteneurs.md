# Chantier — Modèle des conteneurs

## Contexte

Le conteneur d'une publication est ce qui la publie ou l'héberge. Le schéma en donne trois représentations :

- `publishing.journals`, que référence `publications.journal_id` ;
- `publishing.monographs`, que référence `publications.monograph_id` : livres et volumes d'actes, avec ou sans ISBN, avec un `journal_id` vers leur collection ;
- `publications.container_title`, un titre libre quand aucune des deux tables ne convient.

Le chantier [Monographies](DATA_monographies.md) sépare les livres et les volumes d'actes, dans `monographs`, des séries dont ils font partie, dans `journals`.

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

Publications qui partagent un identifiant arXiv sans être typées preprint : 189 paires. Dans 135 paires, l'une des deux a un DOI arXiv. Les autres réunissent une communication et un article (27), un erratum ou un addendum et son article (6), un jeu de données et son article (5), deux publications de même type (16). Parmi ces dernières, des copies d'entrepôt restent séparées de leur article (Apollo `10.17863`, DESY `10.3204`), et des identifiants arXiv sont attribués à tort.

2 352 des 4 357 enregistrements DataCite arXiv sont typés `article`, d'après leur type brut. Aucun n'est rattaché à ArXiv.org, donc la correction `JOURNAL_TYPE_PREPRINT_SERVER_TO_PREPRINT` ne s'applique pas. 184 des 1 148 publications à DOI arXiv ont un autre type que `preprint`.

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

- **Localisations.** Elles comptent peu d'entrées, car deux normaliseurs les écartent. OpenAlex ne cherche aucune revue quand la localisation principale est un entrepôt, HAL, theses.fr ou une plateforme d'ebooks (`should_skip_publisher_journal`). DataCite garde seulement les conteneurs qui désignent une revue (`container_names_a_journal`). Restent SSRN (172 publications), bioRxiv (205), Research Square (trois entrées, dont une `unknown` de 87 publications), medRxiv et ChemRxiv (`unknown`), Preprints.org, ArXiv.org, Zenodo (`journal`).
- **`ebook_platform`.** 38 entrées sur 39 sont des sources OpenAlex au nom d'un éditeur suivi de « eBooks » (« ENS Éditions eBooks »). Elles désignent un éditeur, pas un lieu.
- **`unknown`.** 61 entrées sont les universités qui délivrent les thèses ScanR (« Université Clermont Auvergne (2021-...) », « Lyon », « Normandie »), avec l'ABES pour éditeur, soit 1 395 publications.
- **`media`.** Ce sont des publications en série : *The Conversation France* (378), *Revue Politique et Parlementaire* (102), *Le Monde*.
- **Deux codages des localisations.** Le type (`journal_type`) et le modèle open access `repository` se contredisent. Seuls bioRxiv, Research Square et ArXiv.org ont `oa_model = repository`, contre SSRN, medRxiv et Research Square typé `unknown`.
- **Localisations hors de `journals`.** 57 990 publications ont un identifiant HAL, 5 256 un PMCID, 5 051 un identifiant arXiv, 2 109 un NNT, 74 533 des URL. 22 726 publications ont seulement un `container_title` : colloque, livre ou archive.

Usages du type dans le code :

- **Espaces de noms DOI** : aucun pour `repository`, `preprint_server`, `ebook_platform` et `book_series` (`domain/journals/doi_namespaces.py`).
- **Typage** : l'enrichissement OpenAlex type seulement une entrée `unknown` (`repository`, `conference`, `book series`, `ebook platform`). `type_proceedings_journals` et `link_monographs_to_collections` posent `proceedings` et `book_series`. La vérification Sudoc traite `proceedings` et `book_series` comme des séries de volumes (`holds_volumes`).
- **Corrections du type de document** : `media` donne `media`, `proceedings` donne `conference_paper`, `preprint_server` donne `preprint` (`domain/source_records/metadata_correction/rules.py`). La fusion de deux revues requalifie les publications absorbées d'après le type de la cible.
- **Open access** : statuts attendus selon `oa_model`, types de document attendus selon `journal_type`, pour le tableau de bord d'une revue (`domain/journals/expected.py`).
- **DOAJ et APC** : ils concernent en pratique les seules entrées `journal`. 2 266 sont dans le DOAJ et 3 725 ont des APC, contre 54 et 2 pour les autres types.
- **Interface** : libellé du type, choix du type dans l'administration, liste des recueils d'actes probables.

### Points des autres fiches que le modèle conditionne

- [Conférences et actes](DATA_conferences-et-actes.md) : noms d'archive dans `container_title`, retypage des séries d'actes typées `journal` ou `book_series`.
- [Revues divergentes selon les sources](DATA_revues-divergentes-entre-sources.md) : couples d'une revue et d'un dépôt ou d'un serveur de preprints ; correction de la revue d'après Crossref, qui remplacerait une localisation par une revue.
- [Monographies](DATA_monographies.md) : conversion d'une entrée de `journals` en monographie dans l'administration, documentation.

## Décisions

- Trois natures distinctes :
  - publication en série : revue, collection d'ouvrages, série d'actes ;
  - publication isolée : monographie, livre ou volume d'actes, rattachée ou non à une série ;
  - localisation : entrepôt, serveur de prépublications, plateforme.
- Les localisations sortent de `journals`.
- Schéma :
  - `publishers` et `doi_prefixes`, inchangées. Le titulaire d'un préfixe est l'éditeur d'origine de ses DOI ;
  - `serials`, à la place de `journals` : revues, collections d'ouvrages, séries d'actes, médias. Les ISSN, les formes de nom, les espaces de noms DOI, le DOAJ, les APC et le modèle open access y restent. Aucune colonne d'éditeur ;
  - `monographs` : livres et volumes d'actes, rattachés à leur série (`serial_id`) ;
  - `platforms` : lieux qui hébergent des publications. Type (`repository`, `preprint_server`, `publisher_platform`, `unknown`), nom et identifiant de la source OpenAlex. Une archive et un entrepôt de données sont des `repository`, que le type de document distingue. Un document déposé sur un serveur de preprints est un preprint ; un entrepôt ne dit rien du type de ses documents ;
  - `platform_domains` : domaine → plateforme, plateforme nullable ;
  - `source_record_locations` : localisations d'un enregistrement source, réécrites à chaque normalisation. URL de la page et du PDF, identifiant OAI-PMH, version dans le vocabulaire de la source, licence, open access, plateforme nullable. OpenAlex les alimente, puis Crossref ;
  - `publisher_id` sur `source_records` et `publications`, écrit par l'agrégation : le titulaire du préfixe pour un DOI Crossref, à défaut l'éditeur que donnent les sources ;
  - `doi_prefix`, colonne générée de `publications`, pour les jointures sur `doi_prefixes`.
- L'éditeur d'une série est celui de ses publications les plus récentes. Une publication a donc l'éditeur à la date de sa publication.
- Une production hébergée sans être publiée n'a pas d'éditeur : preprint, jeu de données, dépôt. La plateforme qui l'héberge n'en est pas l'éditeur, comme le CCSD pour HAL.
- Une plateforme prend le nom et l'identifiant de sa source OpenAlex. Aucune plateforme n'est créée sans nom fiable : les noms d'institution d'Unpaywall sont erronés (« Asklepios Klinik St. Georg » pour l'archive de Göttingen).
- Unpaywall donne seulement le verdict open access. OpenAlex couvre 99 % des publications à DOI Crossref, et donne aussi les copies fermées et le nom des entrepôts.
- Une fiche de catalogue sans copie du texte n'est pas une localisation : le DOAJ (`doaj.org/article`) est écarté.

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
- [ ] Base de production : fusion manuelle des éditeurs en double (Taylor & Francis et Informa UK, OpenEdition Journals et OpenEdition, De Gruyter et Walter de Gruyter, AIP et AIP Publishing, variantes de SIAM, de World Scientific et de John Libbey Eurotext). Marques d'un éditeur (BioMed Central, Birkhäuser, Lippincott) : fusion ou non à trancher.
- [ ] Titulaires de préfixe « Éditions Techniques [1987-1994] » et « Éditions du Juris-classeur [2009] » sur des revues LexisNexis : à examiner.
- [ ] Éditeur d'une publication lu sur la publication : listes, détail, facettes, statistiques et compteurs `publication_count` des éditeurs passent par `journals.publisher_id` (36 occurrences dans 21 fichiers).
- [ ] Éditeur d'une revue calculé d'après ses publications les plus récentes ; suppression de `journals.publisher_id`.

### Phase 3 — Plateformes et localisations

- [x] Migration : `platforms`, `source_record_locations` (`8d0a6ca00`).
- [x] Normalisation OpenAlex : localisations, plateforme trouvée ou créée pour une source de type `repository` (`8d0a6ca00`).
- [x] Stock : réhydratation du staging OpenAlex et renormalisation. 303 477 localisations sur 105 496 des 111 022 enregistrements OpenAlex, 1 366 plateformes.
- [ ] Serveurs de preprints, en attente de la question « Preprint : publication distincte ou version déposée ? ». La part de preprints par plateforme ne les sépare pas des entrepôts (bioRxiv 66 %, arXiv 24 %, OSF Preprints 22 %, Zenodo 9 %) ; l'attribution de DOI propres non plus (Zenodo, Figshare). Seule une liste fermée de serveurs tient.
- [x] Localisation Crossref : la page de résolution du DOI (`resource.primary.URL`) ; les URL de `link`, points d'accès pour la fouille de texte, sont ignorées (`9ca9efccf`).
- [ ] Stock : réhydratation du staging Crossref et renormalisation.
- [ ] Domaine → plateforme appris depuis les localisations OpenAlex.
- [ ] Entrées de `journals` de type `repository` et `preprint_server` converties en plateformes.
- [ ] Préfixe DOI d'une plateforme (Cairn `10.3917`, OpenEdition `10.4000`, Érudit, Université de Bordeaux `10.20870`) : son titulaire n'est pas l'éditeur, ni le nom que Crossref donne à ses DOI. L'éditeur vient des autres sources, ou de la notice Sudoc de la revue. Règle et oneshot de correction des publications (environ 4 650), selon les questions « Préfixes DOI des plateformes » et « Éditeur d'une revue d'après le Sudoc ».
- [ ] Type `preprint` d'après la plateforme du DOI, à la place du type de la revue : les enregistrements DataCite arXiv n'ont pas de revue.
- [ ] Statistiques : exclusion des preprints ou non, en attente de la question « Preprint : publication distincte ou version déposée ? ».
- [x] Vérification Unpaywall : DOI DataCite écartés (`e1d7daeb6`).

### Phase 4 — Séries

- [ ] Renommage de `journals` en `serials`, et de `monographs.journal_id` en `serial_id`.
- [ ] Thèses ScanR : l'université qui délivre la thèse quitte `journals`.
- [ ] Sources OpenAlex « … eBooks » : rattachement à l'éditeur qu'elles nomment.
- [ ] Enrichissements limités à la nature qu'ils décrivent.
- [ ] Endpoints, pages et filtres.

### Phase 5 — Documentation

- [ ] Mise à jour de `docs/donnees`, `docs/pipeline` et `docs/agregats`.

## Questions ouvertes

- Noms des entités dans l'interface.
- Une publication peut-elle avoir à la fois une série, une monographie et une ou plusieurs localisations ?
- Sort des entrées `unknown`.
- Lien entre une localisation et le statut open access d'une publication (dépôt HAL, prépublication).
- **Preprint : publication distincte ou version déposée ?** Un preprint forme aujourd'hui une publication distincte, reliée à l'article par `is_preprint_of` ; une version converge avec l'article seulement sous un même préfixe DOI. OpenAlex réunit au contraire preprint et article dans un même work, le preprint étant une localisation `submittedVersion`. Les localisations OpenAlex suivent donc ce second modèle : la copie arXiv figure parmi les localisations de l'article, alors que l'enregistrement DataCite arXiv forme sa propre publication. Adopter le modèle d'OpenAlex ferait converger les versions quel que soit le préfixe et remplacerait `is_preprint_of` par la version des localisations ; un preprint jamais publié resterait une publication de type preprint. Aujourd'hui, 1 468 preprints du périmètre ont leur article en base, et une statistique sans filtre de type compte les deux.
- **Table des URL.** Les URL d'une publication viennent d'Unpaywall, de Crossref et d'OpenAlex, avec leur lieu et leur version. Le lieu se déduit du domaine, par une table domaine → lieu que les changements de plateforme font évoluer. Le lieu d'un domaine peut rester inconnu.
- **Maintenance des référentiels.** Chaque table a son régime : recalcul à chaque run, mise à jour incrémentale par file d'attente, ou valeur posée une fois (typage OpenAlex, `doi_prefixes`). Comment rafraîchir une valeur posée une fois ? `doi_prefixes` attribue à Hindawi un préfixe dont Wiley détient les DOI.
- **Responsabilité scientifique et éditeur commercial.** Faut-il distinguer les deux rôles ? Le membre Crossref et le domaine de résolution les séparent dans une partie des cas.
- **Préfixes DOI des plateformes.** Une liste fermée, préfixe DOI → plateforme et son type (`preprint_server` ou `publisher_platform`), plutôt qu'un seuil sur les données. Le bilan Science ouverte tient déjà celle des serveurs de preprints (`PREPRINT_SERVERS`, `interfaces/cli/maintenance/report_open_science.py`) : elle passerait dans le domaine. Pour les plateformes d'éditeurs, une mesure dresse les candidats : un titulaire de préfixe dont les revues ont presque autant d'éditeurs distincts que de revues, d'après HAL, et que HAL ne nomme pour aucune. Ce sont Persée, SciELO, Érudit, Prairial (Lyon 3), Episciences (CCSD), OpenEdition, Cairn, Centre Mersenne, Project MUSE ; l'Université de Bordeaux (`10.20870`, six revues) y échappe. Les métadonnées Crossref d'un article de ces revues nomment seulement la plateforme (`publisher`, `member`).
- **Éditeur d'une revue d'après le Sudoc.** La notice Sudoc de l'ISSN donne les éditeurs successifs et leurs périodes (zone 214, à défaut 210, sous-zones `c` et `d`) : *Multitudes*, Éditions Exils (2000-2004), Multitudes (2004-2006), Éditions Amsterdam (2006-2011), Éditions Inculte (depuis 2012). C'est la seule source qui nomme l'éditeur d'une revue diffusée par une plateforme. Limites relevées : notices sans zone d'éditeur (*animal*, *Annals of Oncology*, *Revue européenne des sciences sociales*), périodes qui se chevauchent (*Finance* : Presses universitaires de France 1982-2023, Presses universitaires de Grenoble 2005-2023). La revérification Sudoc des revues relirait ces zones.
- **Double série.** Un volume LIPIcs appartient à la collection LIPIcs, qui a un ISSN, et à la série de son congrès (STACS, SoCG, ICALP). `monographs.journal_id` en désigne une seule : laquelle ?
- **Ouvrage en plusieurs volumes** (« Current Developments in Biotechnology and Bioengineering »). Chaque volume est-il une monographie, et qu'est-ce qui les relie ?
