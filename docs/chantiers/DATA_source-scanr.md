# Chantier — Source ScanR

## Contexte

ScanR agrège HAL, Crossref, theses.fr et des affiliations extraites du texte intégral des publications. Ses enregistrements sources redisent le plus souvent les autres sources. ScanR apporte en propre :

- des identifiants externes (`externalIds`), parfois ceux d'une autre publication au même titre ;
- des affiliations d'auteurs, tirées de HAL ou du texte intégral ;
- l'IdRef des auteurs, trouvé par matching.

Chacun de ces apports produit des erreurs. Chaque correction serait une règle propre à ScanR. Le bilan mesure les pertes et les corrections dues au retrait de la source `scanr`, ou à l'abandon de ses affiliations. Sauf mention contraire, les mesures datent du 2026-11-10. Les scripts des mesures du 2026-11-26 sont dans `data/experiments/source-scanr/`, ceux de la résolution des personnes dans `data/experiments/resolution-personnes/`. La source `scanr_patents` est remplacée par OPS (chantier [brevets](archived/2026-11-10_DATA_brevets.md)).

## Bilan

### Moissonnage

| Mode d'entrée dans le staging | Enregistrements sources |
|---|---|
| Moissonnage par affiliation | 62 357 |
| `fetch_missing` par DOI | 3 782 |
| `fetch_missing` par identifiant HAL | 4 419 |
| Moissonnage par identifiant de personne | 7 548 |

`fetch_missing` cherche dans les autres sources les identifiants donnés par ScanR. Enregistrements sources récupérés par `fetch_missing` et reliés à leur publication seulement par un identifiant ScanR :

| Source | Recherche par | Enregistrements sources | Dans une publication du périmètre |
|---|---|---|---|
| HAL | identifiant HAL | 394 | 356 |
| theses.fr | NNT | 1 238 | 1 |
| DataCite | DOI | 87 | 73 |
| OpenAlex | DOI | 50 | 49 |
| Crossref | DOI | 44 | 36 |

### Réconciliation

Exemple : dans ScanR, une thèse de 2020 soutenue à Montpellier a pour identifiant secondaire l'identifiant HAL d'une communication de 2017 au même titre. Le futur directeur de thèse signe cette communication avec un laboratoire du périmètre. La publication réunit les deux et entre dans le périmètre.

- Au 2026-11-26 (`reconciliation_sans_scanr.py`), 158 publications sont réunies seulement par les clés de confirmation de leurs enregistrements sources ScanR. 80 réunissent des documents de types ou d'années différents, surtout une communication ou un poster et l'article de même titre. 12 réunissent une thèse et un autre document, 11 des documents de titres différents. 44 réunissent un preprint et sa version publiée, 11 deux enregistrements sources du même document.
- 53 publications réunissent une thèse et un autre type de document, tous deux présents hors de ScanR. ScanR fait le lien dans 9 cas. Dans les autres cas, une œuvre OpenAlex de type thèse contient l'identifiant HAL d'un poster, d'une communication ou d'un livre, ou l'inverse.

### Affiliations

Provenance des affiliations ScanR (`datasource`) :

- `hal`, ou aucune pour un enregistrement source issu d'un dépôt HAL : les structures HAL de tous les auteurs du dépôt, attribuées à chacun ;
- `bso3_publications_dump`, `parsed_fr`, `all_parsed_fr` : extraction du texte intégral. ScanR garde souvent un seul auteur et lui attribue les adresses de toute la publication ;
- `theses` : établissement, école doctorale et laboratoire de la thèse.

Mesures :

- 6 847 contributions sources ScanR, dans 2 987 publications, ont la structure HAL d'un autre auteur du dépôt HAL. Pour 637, cette structure est du périmètre. 321 contributions, dans 270 publications, sont du périmètre seulement par cette structure. 319 sont rattachées à une personne. Dans chacune de ces publications, une autre contribution est du périmètre.
- Au 2026-11-03, 3 412 contributions du périmètre, dans environ 2 700 publications, reposent sur ScanR seul. Les autres sources de la contribution contredisent ScanR dans environ 1 450 cas, en majorité faux. Elles sont muettes dans environ 1 960 cas, en majorité justes.
- 337 personnes hors RH ont toutes leurs contributions du périmètre dans cet ensemble. Sur 20 tirées au hasard, 17 sont extérieures au périmètre.
- Au 2026-11-26 (`laboratoires_et_pays.sql`), ScanR seul donne le laboratoire du périmètre de 1 799 des 142 147 contributions à laboratoire. Pour 925 d'entre elles, le dépôt HAL copié par l'enregistrement source ScanR donne ce laboratoire à un autre auteur. Pour 554, ce laboratoire est absent des contributions sources du dépôt HAL. 328 ont un laboratoire d'une autre provenance. ScanR donne aussi un laboratoire supplémentaire à 64 contributions.
- Au 2026-11-26 (`pays.sql`, `pays_exemples.sql`), ScanR seul donne un pays à 2 379 publications du périmètre : 757 fois le code « sans pays » (`xx`), 104 fois la France, 2 008 fois un autre pays. Sur 25 de ces autres pays tirés au hasard, 12 désignent un partenaire étranger plausible. 8 viennent de la structure HAL d'une alliance universitaire européenne, au pays Espagne. 3 viennent d'un pays mal détecté ou d'un texte parasite, 2 sont indéterminés.

### Résolution des personnes

Le critère IdRef précède le critère de nom. Une contribution sans contribution source du périmètre est rattachée seulement par épinglage ou par un identifiant à verdict humain.

- 36 998 contributions sont rattachées par IdRef. Pour 27 764, seul ScanR donne l'IdRef. 27 297 sont du périmètre et désignent 5 567 personnes.
- Sans ScanR, un autre identifiant rattache 4 de ces contributions. Le nom en rattache probablement 25 731 : une contribution source d'une autre source est du périmètre, et son nom désigne seulement cette personne. Le nom de 267 contributions est ambigu ou absent des formes de nom.
- 307 des 1 713 IdRef confirmés de personnes viennent de ScanR seul.
- Au 2026-11-03, les autres sources contredisaient l'IdRef ScanR seul dans 7,6 % des cas tranchés. 9 des 14 cas contredits relus étaient des homonymes. Parmi 16 cas sans information, 9 étaient plausibles. Les 7 autres étaient des thèses, avec l'IdRef d'un membre du jury ou du directeur.
- Au 2026-11-24 (`audit_rapide.py`), l'IdRef de ScanR diffère de l'IdRef d'une autre source de la même contribution dans 811 contributions sur 81 850.
- Au 2026-11-26 :
  - l'IdRef de ScanR est absent des IdRef confirmés de la personne rattachée dans 659 contributions sur 51 579 (`idref_scanr_confirme.py`). 273 sont rattachées par ORCID, 195 par le nom, 68 par compte HAL, 53 par un IdRef en attente de la personne donné par ScanR, 43 par épinglage. Dans 120 de ces contributions, une autre source donne un IdRef confirmé de la personne ;
  - 217 personnes ont plusieurs IdRef non rejetés (`identifiants_fautifs.py`). Sans ScanR, 137 d'entre elles gardent un seul IdRef.
- Fausses attributions rejetées par l'administration, au 2026-11-24 : 88 paires comportaient un identifiant de la personne, donné à l'homonyme par une source. L'IdRef de ScanR est seul dans 58 de ces paires, présent dans 7 autres.
- Clusters de deux publications signalés au 2026-11-24 : 7 clusters relèvent probablement d'un homonyme, presque tous rattachés par IdRef. Dans 3 d'entre eux, ScanR est la seule source à donner un IdRef.

### Périmètre

- 75 346 publications sont du périmètre. ScanR est présent dans 65 157, seule source dans 11.
- Au 2026-11-26 (`perimetre_scanr_seul.py`, `analyse_perimetre.py`), 743 des 75 841 publications du périmètre tirent tous leurs indices de contributions sources ScanR :
  - 524 par la fiche RH d'une personne, désignée par l'identifiant d'une contribution source ScanR. 519 des 574 contributions concernées viennent du moissonnage de ScanR par identifiant de personne. 318 sont sans adresse dans les autres sources. Types : 249 articles, 97 chapitres, 34 comptes rendus, 32 livres. Fausses attributions estimées : 88 à 135 contributions. Sur 30 relues, 4 sont signées par un homonyme ;
  - 232 par une affiliation ScanR, dont 13 aussi par la fiche RH. Sur 20 relues au 2026-11-10, l'affiliation est contredite par les autres sources dans 11 cas, du texte parasite dans 3 cas (biographie, comité éditorial, texte du livre), plausible sans confirmation dans 5 cas, indéterminée dans 1 cas.

Estimation des fausses attributions. Un score mesure la ressemblance d'une publication aux publications solides de la personne, celles qui ont un indice d'une autre source que ScanR. Il somme les poids des indices partagés : coauteurs rattachés, revue, thèmes OpenAlex, domaines HAL. Les poids sont ceux de la détection des attributions suspectes. Un score inférieur à 0,5 isole la publication. Sont isolées 3 à 14 % des publications solides et 97 % des publications rejetées pour la personne par l'administration. Parmi les publications solides entrées seulement par la fiche RH, 8 à 30 % sont isolées. La part isolée d'un groupe donne sa part de fausses attributions, par tranche de nombre de publications solides de la personne. Les deux références de publications solides donnent les bornes de l'estimation.

### Métadonnées

Publications du périmètre où ScanR seul donne la donnée :

| Donnée | Publications |
|---|---|
| Identifiant HAL | 532 |
| PMID | 74 |
| DOI | 37 |
| Résumé | 2 010 |
| Mots-clés | 22 617 |
| Licence | 97 |
| Copie ouverte | 407 |

Le résumé et les mots-clés servent seulement à la fiche de la publication. Les mots-clés ScanR comprennent des concepts Wikidata attribués par ScanR. Ils restent hors des sujets. La copie ouverte donne un lien d'accès dans la liste et la fiche des publications. Le statut open access vient d'Unpaywall. Au 2026-11-26, 52 publications du périmètre ont un sujet Rameau donné par ScanR seul.

### Scénarios

Au 2026-11-26 (`scenarios.py`), deux scénarios pour les 2 588 contributions rattachées et du périmètre par leurs seules contributions sources ScanR :

- retrait de la source `scanr` ;
- ScanR sans affiliations : la normalisation de ScanR omet adresses, structures HAL et ROR. Une contribution source ScanR garde ses identifiants, donc l'indice de la fiche RH.

Une personne sans publication solide compte pour une fausse attribution.

| | Retrait | Sans affiliations |
|---|---|---|
| Publications qui sortent du périmètre | 743 | 219 |
| Contributions qui les font entrer dans le périmètre | 849, dont 216 à 283 fausses | 238, dont 126 à 140 fausses |
| Contributions qui perdent leur personne | 2 172, dont 461 à 557 fausses | 1 291, dont 366 à 408 fausses |
| dont rattachées par l'identifiant ScanR d'une personne à fiche RH | 781 | 0 |
| Personnes sans fiche RH qui perdent toutes leurs contributions d'auteur | 287 | 286 |
| Publications réunies seulement par ScanR | 158 scindées | 158 inchangées |
| Laboratoires et pays donnés par ScanR seul | perdus | perdus |
| Règles propres à ScanR | supprimées | gardées |

### Code

Règles propres à ScanR hors de `pipeline/ingestion/scanr/` :

- correction du type d'un enregistrement source ScanR issu d'un dépôt HAL (`SCANR_FROM_HAL_TO_HAL_TYPE`) ;
- alignement des auteurs : listes d'auteurs tronquées (`SCANR_TRUNCATED_LENGTHS`), copie d'un dépôt HAL écartée du vote des listes d'auteurs (`DEFERRED_SOURCE`) ;
- `fetch_missing` : recherche dans ScanR par identifiant HAL ;
- rôles, types de document, licences, détection des pays, identifiant ScanR dans la liste et la fiche des publications.

## Questions ouvertes

- Les enregistrements sources ScanR rattachés à un enregistrement source INSPIRE-HEP sont-ils aussi sans contributions sources, comme ceux d'OpenAlex ? Ces publications contiennent 110 339 contributions sources ScanR. Au 2026-11-26, 166 contributions du périmètre y reposent sur une affiliation ScanR seule, et aucune publication ne sort du périmètre. L'échantillon du 2026-11-07 en juge 13, toutes fausses.
