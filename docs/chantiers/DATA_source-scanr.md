# Chantier — Retrait de la source ScanR

## Contexte

ScanR agrège HAL, Crossref, theses.fr et des affiliations extraites du texte intégral des publications. Ses enregistrements sources redisent le plus souvent les autres sources. ScanR apporte en propre :

- des identifiants externes (`externalIds`), parfois ceux d'une autre publication au même titre ;
- des affiliations d'auteurs, tirées de HAL ou du texte intégral ;
- l'IdRef des auteurs, trouvé par matching.

Chacun de ces apports produit des erreurs. Chaque correction serait une règle propre à ScanR. Le bilan mesure, au 2026-11-10, les pertes et les corrections dues au retrait de la source `scanr`. La source `scanr_patents` est remplacée par OPS (chantier [brevets](archived/2026-11-10_DATA_brevets.md)).

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

- Dans 937 publications, l'identifiant HAL `secondary` d'un enregistrement source ScanR est le seul lien entre deux groupes d'enregistrements sources. 377 groupes sont de même type et de même année. Les autres groupes sont surtout des versions successives d'un travail : communication puis article, poster puis article, prépublication puis article. Dans 78 cas, les deux groupes n'ont aucune année commune. 11 publications réunissent une thèse et un autre type de document.
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

### Résolution des personnes

Le critère IdRef précède le critère de nom. Une contribution sans contribution source du périmètre est rattachée seulement par épinglage ou par identifiant.

- 36 998 contributions sont rattachées par IdRef. Pour 27 764, seul ScanR donne l'IdRef. 27 297 sont du périmètre et désignent 5 567 personnes.
- Sans ScanR, un autre identifiant rattache 4 de ces contributions. Le nom en rattache probablement 25 731 : une contribution source d'une autre source est du périmètre, et son nom désigne seulement cette personne. Le nom de 267 contributions est ambigu ou absent des formes de nom.
- 307 des 1 713 IdRef confirmés de personnes viennent de ScanR seul.
- 1 299 contributions, dans 1 134 publications, ont pour seules contributions sources du périmètre des contributions sources ScanR. Elles perdent leur personne.
- Au 2026-11-03, les autres sources contredisaient l'IdRef ScanR seul dans 7,6 % des cas tranchés. 9 des 14 cas contredits relus étaient des homonymes. Parmi 16 cas sans information, 9 étaient plausibles. Les 7 autres étaient des thèses, avec l'IdRef d'un membre du jury ou du directeur.

### Périmètre

- 75 346 publications sont du périmètre. ScanR est présent dans 65 157, seule source dans 11.
- 865 publications ont pour seules contributions sources du périmètre des contributions sources ScanR. Sans ScanR, 85 restent du périmètre : un identifiant d'une autre source y rattache une personne de la fiche RH. Environ 780 sortent du périmètre :
  - 187 par une affiliation ScanR. Sur 20 relues, l'affiliation est contredite par les autres sources dans 11 cas, du texte parasite dans 3 cas (biographie, comité éditorial, texte du livre), plausible sans confirmation dans 5 cas, indéterminée dans 1 cas ;
  - environ 595 par la fiche RH d'une personne rattachée par l'IdRef ScanR.

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

Les mots-clés ScanR comprennent des concepts Wikidata attribués par ScanR. La fiche de la publication les affiche. Ils restent hors des sujets.

### Code

Règles propres à ScanR hors de `pipeline/ingestion/scanr/` :

- correction du type d'un enregistrement source ScanR issu d'un dépôt HAL (`SCANR_FROM_HAL_TO_HAL_TYPE`) ;
- alignement des auteurs : listes d'auteurs tronquées (`SCANR_TRUNCATED_LENGTHS`), copie d'un dépôt HAL écartée du vote des listes d'auteurs (`DEFERRED_SOURCE`) ;
- `fetch_missing` : recherche dans ScanR par identifiant HAL ;
- rôles, types de document, licences, détection des pays, identifiant ScanR dans la liste et la fiche des publications.

## Questions ouvertes

- Justesse des rattachements par l'IdRef ScanR seul, dans les quelque 595 publications du périmètre par la fiche RH : échantillon à relire.
- Usage des 2 010 résumés et des 22 617 listes de mots-clés fournis par ScanR seul.
