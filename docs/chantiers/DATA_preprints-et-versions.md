# Chantier — Preprints et versions d'une publication

## Contexte

Un preprint à DOI forme une publication distincte, reliée à sa version publiée par `is_preprint_of`. Une copie de repository rejoint la version publiée qu'elle déclare. Un preprint reste à part, même quand il se déclare version de l'article.

OpenAlex et ScanR suivent un autre modèle : un work réunit le preprint et l'article, le preprint y est une localisation `submittedVersion`. Les localisations OpenAlex (`source_record_locations`) suivent ce modèle : la copie arXiv figure parmi les localisations de l'article, alors que l'enregistrement source DataCite arXiv forme sa propre publication. Les identifiants OpenAlex le suivent aussi : le work de l'article contient en `secondary` le `hal_id` du dépôt HAL du preprint. Un enregistrement source preprint sans DOI rejoint ainsi la publication de l'article par une clé partagée.

La réconciliation coupe une composante par ancres, les DOI `primary` et `derived` : deux ancres distinctes désignent deux œuvres (`domain/publications/reconciliation.py`). Le DOI d'une forme secondaire (version Zenodo, pièce d'un jeu de données, DOI à suffixe de version) a une cible dans `doi_targets`, que la réconciliation lit à la place du DOI. Les formes d'une œuvre rejoignent ainsi sa publication. L'enregistrement source DataCite d'une forme secondaire est écarté de la réconciliation quand sa cible est le DOI `primary` d'un autre enregistrement source.

La phase `relations` reconstruit `publication_relations` à chaque run. Elle suit `finalize`, qui calcule le périmètre et les compteurs. L'option `--no-extras` l'omet.

Le volet Accès de la fiche d'une publication classe ses copies ouvertes par version (éditeur, acceptée, soumise, inconnue), puis par ordre d'arrivée. Les localisations HAL et DataCite sont sans version : une localisation OpenAlex arXiv en `submittedVersion` passe devant le dépôt HAL. La phase `publications` calcule l'adresse d'accès (`best_copy_url`) et le statut open access d'une publication recalculée, sur les copies de ses enregistrements sources.

### Typologie du 2026-11-01, base locale

Le type d'une publication vient du premier enregistrement source typé, dans l'ordre de priorité des sources (theses.fr, Crossref, DataCite, HAL, OpenAlex, ScanR, WoS), puis dans l'ordre d'arrivée.

**Clés de réunion.** Un work OpenAlex ou un enregistrement source ScanR cite en `secondary` les `hal_id` de plusieurs dépôts HAL : preprint, article, communication, poster. La clé de confirmation d'un type d'identifiant est l'identifiant de rôle le plus fort, puis de plus petite valeur : entre plusieurs dépôts, le numéro décide. OpenAlex type aussi `preprint` des works de dépôts HAL d'articles. Le bloc de métadonnées (type, titre, année) relie alors un tel work à l'enregistrement source DataCite arXiv (3059).

**Publications qui contiennent un enregistrement source preprint et un enregistrement source d'un type publié.** L'ancre est le DOI de la publication, jugé sur les enregistrements sources Crossref, DataCite, HAL et theses.fr dont il est le DOI propre.

| Ancre | Publications | Enregistrements sources réunis | Type retenu | Exemples |
|---|---|---|---|---|
| DOI de la version publiée | 644 | dépôt HAL preprint sans DOI (209), qui cite le DOI (31) ; work OpenAlex typé preprint : arXiv (182), dépôt HAL (114), qui cite le DOI (87), au DOI de la publication (29) | publié, sauf 19474 | 1800, 373, 292, 25884 |
| DOI du preprint, type publié donné par OpenAlex ou ScanR seuls | 200 | work OpenAlex typé article : arXiv, Zenodo, discussions Copernicus, DESY | preprint | 9524, 184561, 312726 |
| DOI du preprint, dépôt HAL d'un type publié | 142 | article (72), communication (62), chapitre (6), data paper | preprint | 3059, 299298, 2658 |
| Sans DOI | 144 | dépôt HAL d'un type publié, work OpenAlex du dépôt typé preprint | type HAL | 26982, 3060 |

Dépôts HAL d'un type publié réunis au DOI d'un preprint :

- 45 articles sans aucun DOI, tous avec revue. 14 sont reliés par `is_preprint_of` à une version publiée distincte.
- 27 articles qui citent le DOI du preprint (2934 : article de Nature Communications déposé avec le DOI bioRxiv).
- 57 communications sans aucun DOI, aucune avec revue ou recueil. 12 sont reliées.

16 publications typées version publiée sont dans le périmètre par leurs seuls enregistrements sources preprint.

**Autres cas.**

- Revue d'un preprint : 149 discussion papers (Copernicus) prennent la revue de l'article par l'espace de noms DOI (`SERIAL_BY_DOI_NAMESPACE`) ; 70 preprints prennent celle d'un dépôt HAL d'article réuni.
- Working papers typés `other` : le type `other` de DataCite passe devant le type `preprint` de HAL. 87 publications, dont 72 à DOI OSF (`10.17605`) (14691, 255632).
- Œuvres distinctes réunies : 496 publications typées communication ont un enregistrement source Crossref `article` et un dépôt HAL communication, dont 154 avec plusieurs dépôts HAL. 620 réunit un article de revue et une communication de 2021 par les `hal_id` secondaires de ScanR : le sous-type de la communication l'emporte sur `article`.

**Simulation de scission.** `plan_reconciliation` est rejoué sur les membres de chaque publication où OpenAlex, ScanR ou un dépôt HAL cite un `hal_id`, un identifiant arXiv ou un DOI secondaire. La règle V5 écarte, entre natures différentes (preprint, version publiée) :

- le `hal_id` secondaire cité par un enregistrement source OpenAlex ou ScanR qui décrit un autre document (DOI ou identifiant arXiv dérivé) ;
- l'identifiant arXiv d'un enregistrement source d'un type publié. Une copie arXiv compte comme preprint.

| Règle | Publications scindées | Parts détachées |
|---|---|---|
| `hal_id` secondaires d'OpenAlex et ScanR tous écartés | 1 344 | dépôts HAL d'articles, de communications, de chapitres détachés de leur propre version : doublons |
| Écartés quand l'enregistrement source cite plusieurs `hal_id` | 461 | mêmes doublons, moins nombreux |
| V5 | 357 | 197 dépôts HAL preprint détachés d'une version publiée, 109 dépôts HAL d'un type publié détachés d'un preprint, 46 works OpenAlex arXiv, 1 doublon (171019) |
| V5, plus le DOI secondaire cité par un work OpenAlex preprint | 550 | 190 works OpenAlex arXiv de plus, dont celui de 165044 |

Sous V5, 21 versions publiées sortent du périmètre, leur part détachée y reste. La simulation ignore les autres publications : une part détachée peut en rejoindre une par une autre clé.

**Relecture de 50 scissions V5.** Dépôt HAL preprint détaché d'un article : 25 scissions justes sur 25. Dépôt HAL d'un type publié détaché d'un preprint : 11 justes, 11 doutes, 3 « même œuvre ». Les réserves portent sur des communications sans actes, des documents hors édition (HDR, document de travail), et des articles sans localisation éditeur, arXiv pour seule source.

**Simulation de fusion.** Seuls les DOI extérieurs aux serveurs de preprints du registre coupent les composantes. Simulation sur les composantes qui contiennent un DOI de serveur de preprints (39 900 enregistrements sources), pendant un moissonnage :

- 1 032 fusions de publications. 927 réunissent une paire `is_preprint_of` : relation déclarée par Crossref (387) ou DataCite (107), clé partagée (231), titre (202). 28 réunissent le même preprint déposé sur deux serveurs (arXiv et Research Square, deux DOI SSRN).
- 2 060 enregistrements sources orphelins rattachés à une publication, dont 1 401 DataCite arXiv. 236 enregistrements sources changent de publication. 8 publications se scindent en partie.
- Le doublon WoS 301756 rejoint 165044 : l'ancre arXiv de la composante empêchait l'enregistrement WoS sans DOI de rejoindre l'article.
- 813 paires `is_preprint_of` restent distinctes : discussion papers Copernicus (189), dépôts DESY (132), RWTH (83) et Zenodo (16) typés preprint, preprints sans DOI (130), preprints de serveurs reliés sans clé partagée (arXiv 114, bioRxiv 35, SSRN 35).
- Le DOI d'un dépôt institutionnel typé preprint (DESY, RWTH) reste une ancre, et devient le DOI de la publication fusionnée.
- Une publication sans DOI extérieur aux serveurs de preprints garde l'un des DOI de ses serveurs comme DOI.

**Relecture de 41 fusions**, tirées par strate : 39 justes, 1 fausse, 1 doute. La fusion fausse tient à un seul lien : l'enregistrement source ScanR d'un article cite en `secondary` le DOI Research Square d'une autre œuvre (165353, 27616). Le doute porte sur un changement de titre, alors que le dépôt HAL de l'article cite l'identifiant arXiv du preprint (27589, 287499).

**Liens `is_preprint_of`** (relations du 2026-10-31) : 1 724 vers une publication du corpus. 63 viennent de preprints à plusieurs cibles. 78 visent un type non publié, 81 une publication sans DOI vue par HAL, 13 une publication sans DOI vue par le seul WoS (165044 vers 301756, doublon de l'article). 15 relient un preprint du périmètre à une cible hors périmètre. 48 partent d'un preprint qui contient un dépôt HAL d'un type publié.

### Mesures du 2026-10-30

- 2 298 des 3 935 enregistrements sources DataCite arXiv sont typés `article`, d'après leur type d'origine. Aucun n'est écarté de la réconciliation.
- 2 802 couples publication–identifiant arXiv viennent d'une localisation arXiv en `submittedVersion` d'une publication autre qu'un preprint. Pour 2 350, le DOI arXiv est le DOI d'aucune publication.
- 81 paires de publications autres que des preprints partagent un identifiant arXiv actif.

**Paires reliées.** 1 652 paires `is_preprint_of` relient 1 624 preprints à 1 612 publications. Chaque paire vient d'un seul signal :

| Signal | Paires | Titre normalisé identique | Titre très différent (similarité < 0,5) |
|---|---|---|---|
| Relation déclarée par Crossref | 617 | 389 | 31 |
| Clé partagée (arXiv, HAL, PMID) | 547 | 439 | 9 |
| Titre identique | 461 | 461 | 0 |
| Relation déclarée par DataCite | 27 | 19 | 1 |

Le titre change souvent entre preprint et article : les titres différents d'une relation Crossref sont plausibles. Ceux d'une clé partagée sont suspects.

**Type de la cible.** 1 577 paires relient le preprint à une version publiée (article, communication publiée, synthèse, chapitre, data paper, ouvrage, éditorial, lettre). 75 le relient à une œuvre liée : communication orale (55), `other` (8), poster (6), rapport (3), thèse, jeu de données, logiciel. 27 preprints ont plusieurs cibles, et 36 cibles ont plusieurs preprints.

**Auteurs.** Comparaison des noms de famille normalisés, toutes sources confondues :

- tous les auteurs du preprint se retrouvent dans la cible pour 1 384 paires (83,8 %) ;
- au plus 20 % des auteurs du preprint manquent pour 213 paires ;
- plus de 20 % manquent pour 55 paires.

**Année.** Écart entre l'année de la cible et celle du preprint : 0 an (813 paires), 1 an (655), 2 ans (115), 3 ans ou plus (40). La cible précède le preprint dans 29 paires.

**Accès.** Pour 73 paires, la cible est fermée et le preprint ouvert.

**Preprints sans cible.** La base compte 3 500 preprints, dont 3 437 dans le périmètre. 1 851 preprints du périmètre n'ont pas de version publiée reliée. 284 d'entre eux ont, chez une même personne résolue, une publication de titre proche (similarité ≥ 0,8), publiée entre l'année précédente et les trois années suivantes ; 114 à plus de 0,95. Le meilleur candidat est un article pour 212 d'entre eux. Le rapprochement par titre exige l'égalité des titres normalisés et un candidat unique : il manque ces paires. Des titres proches désignent aussi des œuvres distinctes : deux analyses d'amplitude de désintégrations de mésons B, qui diffèrent par une particule.

**Publications à DOI arXiv.** 169 publications à DOI arXiv (`10.48550`) ont un autre type que `preprint`, dont 160 typées `article`. 143 sont reliées à une autre publication par `is_related_to` (DataCite, clé partagée) : ce sont des preprints mal typés, comptés dans la famille « Publications » en plus de leur article.

### Mesure du 2026-11-01 : preprint du périmètre, version publiée hors périmètre

49 paires `is_preprint_of` relient un preprint du périmètre à une version publiée hors périmètre. Classement d'après les adresses des personnes du périmètre du preprint :

- 23 : le preprint entre dans le périmètre par un ROR donné par OpenAlex sans adresse, surtout celui du Laboratoire de Mathématiques Blaise Pascal. Les adresses de ces auteurs désignent d'autres laboratoires de mathématiques.
- 11 : la cible est un enregistrement ScanR seul.
- 8 : ces personnes ont une adresse du périmètre sur le preprint, une autre adresse sur la cible.
- 7 : ces personnes ont une adresse du périmètre sur le preprint, aucune adresse sur la cible.

### Dépôts institutionnels typés preprint, 2026-11-01

Le type DataCite « Working Paper » des dépôts DESY et RWTH donne le type preprint.

| Dépôt | Publications preprint | Reliées à leur version publiée | dont par une clé partagée | Doublons dans le périmètre |
|---|---|---|---|---|
| DESY (`10.3204`) | 173 | 112 | 8 | 69 |
| RWTH (`10.18154`) | 112 | 96 | 46 | 84 |
| Zenodo (`10.5281`) | 25 | 6 | 4 | 5 |
| ResearchGate (`10.13140`) | 4 | 2 | 1 | 0 |

- DESY et RWTH : copies d'articles de collaborations (ATLAS, CMS, LHCb), de même titre et de même année que l'article ou de l'année précédente. Le DOI du dépôt est une ancre. 99 copies DESY et 46 copies RWTH sont reliées à l'article par le seul titre.
- RWTH déclare la copie arXiv (`IsVariantFormOf`, 121 enregistrements sources), DESY la version publiée (27). La règle des formes secondaires écarte ces déclarations, faites par un enregistrement source preprint (`meme_oeuvre_declaree`).
- Zenodo : working papers, publiés ensuite pour certains.
- La version publiée des autres publications est absente de la base : aucun homonyme.

### Remédiation du 2026-11-01

La reconstruction des publications fusionne 1 047 publications. 709 paires `is_preprint_of` restent distinctes. 301756 rejoint 165044. 109 publications au DOI d'un serveur de preprints réunissent un enregistrement source d'un type publié et restent typées preprint, dont 43 avec revue (3059).

La seconde reconstruction, DOI de dépôt compris, fusionne 294 publications. Les publications DESY typées preprint passent de 173 à 19, celles de RWTH de 112 à 38. Les publications Zenodo typées preprint passent de 25 à 84 : des working papers, typés article par OpenAlex, que leur DOI Zenodo faisait passer pour publiés. L'article « Octagon Embeddings » quitte 15705 (319879).

### Discussions Copernicus, simulation du 2026-11-01

Règle simulée : les discussions Copernicus forment un serveur de preprints, au DOI de forme `10.5194/<revue>-<année>-<numéro>`, preprints EGUsphere compris. Le rattachement à une revue par l'espace de noms DOI ignore leurs DOI. Hors règle : anciennes discussions (`amtd-…`, 3 DOI), commentaires (`-ac1`, 416 DOI), suppléments, résumés de congrès.

- 95 publications fusionnent, en 93 groupes : discussion paper et article final. Une fusion est fausse : un discussion paper rejoint une thèse par un work OpenAlex typé thèse (173176, 283259). Cinq autres réunissent des titres modifiés entre la discussion et l'article.
- 110 discussion papers restent seuls, dont 100 du périmètre. Tous deviennent preprints : 52 le sont, 40 sont typés `other` et 18 article. Les 64 rattachés à une revue la perdent.
- Le statut open access des discussion papers seuls passe de `gold` à `green` : copie sur un serveur de preprints.

## Décisions

- **Un preprint et sa version publiée forment une seule publication quand une clé de confirmation les réunit.** Seuls les DOI extérieurs aux serveurs de preprints du registre coupent les regroupements. Une communication sans actes, une HDR ou un article sans localisation éditeur réunit ainsi ses copies de serveurs de preprints.
- **Une copie de dépôt rejoint sa version publiée comme un preprint.** Le DOI d'une archive de copies (DESY, RWTH, GSI, ResearchGate) et le DOI Zenodo d'un dépôt de texte restent hors des ancres. Le DOI Zenodo d'un jeu de données, d'un logiciel ou d'un poster reste une ancre.
- **Le DOI d'une publication est son ancre**, à défaut un DOI de dépôt : serveur de preprints, archive de copies, dépôt de texte sur Zenodo.
- **Dans une publication qui a une version publiée, les enregistrements sources preprint passent après les autres** pour arbitrer le type, la date, le titre et les autres champs. Une publication a une version publiée quand ses enregistrements sources ont une ancre, ou quand un enregistrement source typé autrement que preprint a un conteneur.
- **Une publication publiée par son conteneur prend le type du conteneur** : article dans une revue, communication dans des actes, chapitre dans un ouvrage. La correction des métadonnées aligne déjà le type de l'enregistrement source sur son conteneur.
- **Un dépôt arXiv est un preprint**, même accepté pour publication : la plateforme impose le type.
- **Les copies d'un preprint passent après les autres copies ouvertes dans le volet Accès** : un preprint donne l'accès principal seulement s'il est la seule copie ouverte. Le nom de la plateforme suffit à reconnaître un preprint.
- **Un preprint sans clé commune avec sa version publiée reste une publication distincte et visible**, reliée par `is_preprint_of`. L'administration fusionne la paire à la main. La fusion manuelle ignore les DOI de dépôt, comme la réconciliation.

## Phasage

### Phase 1 — Mesures

- [x] Preprints du périmètre dont la version publiée est hors périmètre
- [x] Typologie des publications qui réunissent un preprint et sa version publiée
- [x] Simulation de scission par nature
- [x] Relecture d'un échantillon de 50 scissions V5
- [x] Simulation de fusion : DOI des serveurs de preprints écartés des ancres
- [x] Relecture d'un échantillon de 41 fusions
- [x] DOI des dépôts institutionnels typés preprint (DESY, RWTH, Zenodo), avant toute règle

### Phase 2 — Fusion des preprints

- [x] Type `preprint` d'après le préfixe DOI du serveur de preprints, pour un enregistrement source sans revue (67c1b73ef)
- [x] Enregistrements sources lus dans l'ordre d'arrivée pour l'agrégation (c1b6d7615)
- [x] DOI des serveurs de preprints écartés des ancres de la réconciliation (7a291b64c)
- [x] DOI de la publication : DOI extérieur aux serveurs de preprints, à défaut DOI d'un serveur de preprints (7a291b64c)
- [x] Fusion manuelle : DOI des serveurs de preprints ignorés (7a291b64c)
- [x] Arbitrage : enregistrements sources preprint après les autres (96b9bc228)
- [x] Remédiation du stock : reconstruction des publications (`--rebuild-publications`), run du 2026-11-01
- [x] Retrait du DOI d'une autre œuvre étendu à toutes les sources, pour la fusion fausse de 15705 (1004d75d1)
- [x] Publication publiée par le conteneur d'un enregistrement source typé autrement que preprint : revue, actes, ouvrage (6269b46ef)
- [x] DOI de dépôt hors des ancres : archives de copies (DESY, RWTH, GSI, ResearchGate), dépôts de textes sur Zenodo ; fusion manuelle comprise (4e4f0775f)
- [x] Remédiation du stock : reconstruction des publications pour les DOI de dépôt, run du 2026-11-01

### Phase 3 — Affichage

- [x] Volet Accès : copies des preprints après les autres copies (b207d36fd)

### Phase 4 — Fin de chantier

- [x] Mise à jour de la documentation : réconciliation, agrégation, fusion manuelle (47015e278)

## Questions ouvertes

- **Discussion papers Copernicus.** Leur DOI coupe : 189 paires `is_preprint_of` restent distinctes, et la fusion manuelle est refusée. 149 discussion papers prennent la revue de l'article par l'espace de noms DOI.
- **Doublons hors preprints.** Copies de repository (Apollo), articles à deux DOI, revues qui changent de préfixe DOI, articles vus par le seul WoS sans DOI (301756) : chaque copie ou double DOI forme une publication de plus.
