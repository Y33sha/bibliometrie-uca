# Chantier — Conférences et actes

## Contexte

Le type `conference_paper` regroupe tout ce qui relève d'une conférence : texte publié dans des actes, résumé, communication orale. Le chantier vise à distinguer le texte publié dans des actes (`conference_paper`) de la communication (type « conférence », à créer), et à identifier les volumes d'actes.

Mesures du 2026-09-12, sur le périmètre.

### Répartition

- 12 126 `conference_paper`. 2 388 sont rattachés à une entrée de `journals` : types `journal` 1 469, `proceedings` 658, `book_series` 149, `unknown` 107. 99 % des rattachés à `proceedings` et 89 % des rattachés à `journal` ont un DOI.
- 9 738 ne sont rattachés à aucune entrée de `journals`. Presque tous viennent de HAL, sans DOI, avec le nom du colloque en `container_title` (HAL `conferenceTitle_s`).
- Préfixes DOI les plus fréquents : IEEE 503, Springer 404, Elsevier 255, ACM 84.

### Discipline

Par domaine HAL (une publication peut relever de plusieurs domaines ; 623 `conference_paper` n'en ont aucun) :

| Domaine HAL | conference_paper | articles | % rattachés à des actes | % avec DOI | % sans DOI ni revue |
|---|---|---|---|---|---|
| Sciences de l'Homme et Société | 5 175 | 6 046 | 0 | 4 | 94 |
| Sciences du Vivant | 2 888 | 7 415 | 1 | 10 | 90 |
| Informatique | 1 702 | 1 238 | 27 | 51 | 49 |
| Sciences de l'ingénieur | 975 | 998 | 11 | 32 | 68 |
| Chimie | 687 | 1 238 | 1 | 7 | 93 |
| Sciences de l'environnement | 617 | 1 209 | 1 | 8 | 92 |
| Physique | 420 | 2 869 | 15 | 43 | 57 |
| Sciences cognitives | 306 | 623 | 3 | 6 | 94 |
| Planète et Univers | 277 | 1 492 | 1 | 25 | 75 |
| Mathématiques | 216 | 652 | 21 | 40 | 58 |
| Statistiques | 139 | 153 | 19 | 32 | 67 |

« Rattachés à des actes » : entrée de `journals` de type `proceedings` ou `book_series`. Deux groupes se dessinent. En sciences humaines, vivant, chimie, environnement et sciences cognitives, les actes identifiables sont quasi absents. En informatique, sciences de l'ingénieur, physique, mathématiques et statistiques, ils sont courants. En Planète et Univers, les DOI désignent en bonne partie des résumés de congrès (EGU chez Copernicus).

### Signaux

- **Type de l'entrée `journals`.** `proceedings` et `book_series` désignent des actes. Des séries d'actes sont typées `journal` : IFAC-PapersOnLine, AIP Conference Proceedings, Winter Simulation Conference, IEEE Intelligent Vehicles Symposium.
- **Résumés de congrès publiés en revue.** Environ 175 sont repérables : 104 dans 14 revues de résumés (Goldschmidt Abstracts, Abstracts with programs de la GSA…), 82 en numéro de supplément. 392 `article` paraissent aussi en numéro de supplément.
- **Crossref**, échantillon de 15 DOI par éditeur. IEEE et ACM donnent `proceedings-article`, le titre des actes et l'événement (nom, lieu, dates), sans ISBN. Le volume IEEE a son propre enregistrement (type `proceedings`) avec ISBN ; son DOI est celui de la communication privé de son dernier segment (5 DOI sur 6, un DOI de 2018 suit un autre schéma). Springer donne `book-chapter` avec l'ISBN du volume et la collection (15 sur 15). Elsevier donne `journal-article`.
- **ISBN en base.** 7 `conference_paper` en portent un. Aucune des 404 communications Springer n'a d'enregistrement Crossref en base.
- **HAL**, deux échantillons de 200. Sur 350 communications, `isbn_s` est rempli 8 fois, `bookTitle_s` jamais, `serie_s` parfois, `conferenceTitle_s` toujours. L'indicateur « avec actes » (`proceedings_s`, non extrait) est rempli presque partout et contredit la revue dans des cas nets (volumes LNCS déclarés sans actes). Il est saisi à la main ; sa fiabilité reste à établir.
- **Recherche externe**, 30 communications d'informatique et de sciences de l'ingénieur sans DOI ni revue. Crossref retrouve la communication par son titre 2 fois (similarité 0,99), le volume par le nom du colloque 1 fois. Les échecs : rencontres françaises sans actes à DOI (la moitié de l'échantillon), congrès internationaux à résumés seuls, actes sans DOI Crossref, éditions pas encore parues. IEEE Xplore et DBLP refusent les requêtes automatiques ; l'API IEEE demande une clé.

### `container_title` sans `journal_id`

- 21 446 publications, 12 032 titres distincts. Le champ porte le nom du colloque (communications 9 734, posters 1 851), le titre du livre (chapitres 3 425) ou le nom d'une archive (prépublications, jeux de données).
- 1 114 correspondent au titre d'une entrée de `journals` : archives 962, revues 102, titre porté à la fois par une revue et une archive 28.
- 440 chapitres ont pour contenant le titre d'un livre en base (193 livres).
- 9 734 communications donnent 7 880 noms de colloque distincts ; 989 sont portés par au moins deux publications.

## Décisions

- Le renommage de `journals` n'est pas prioritaire.

## Phasage

### Phase 1 — Définitions
- [ ] Définir `conference_paper` et le type « conférence »
- [ ] Classer le résumé publié en revue (numéro de supplément, revue de résumés)
- [ ] Fixer le type par défaut des communications indécidables, selon la discipline

### Phase 2 — Signaux
- [ ] Tester la fiabilité de `proceedings_s` sur un échantillon vérifié à la main
- [ ] Extraire de HAL `serie_s` et `isbn_s`, et `proceedings_s` si le test le justifie
- [ ] Importer l'enregistrement Crossref des communications à DOI d'éditeur (type, ISBN, événement)
- [ ] Distinguer à l'import les résumés (`meeting abstract` WoS, `conference-abstract` Crossref) des textes d'actes
- [ ] Retyper les séries d'actes classées `journal`

### Phase 3 — Volumes d'actes
- [ ] Identifier un volume : ISBN, collection et numéro de volume, DOI du volume parent
- [ ] Dédoublonner les volumes
- [ ] Rattacher les communications à leur volume

### Phase 4 — Recherche externe
- [ ] Retrouver par son titre le DOI d'une communication sans DOI, dans les disciplines à actes
- [ ] Évaluer l'API IEEE

### Phase 5 — `container_title`
- [ ] Rattacher les chapitres à leur livre en base
- [ ] Traiter les noms d'archive

## Questions ouvertes

- Où vivent les volumes d'actes : dans `journals` (type `proceedings`), ou comme publications de type `proceedings` ?
- Le colloque, en tant qu'événement, mérite-t-il une entité distincte des actes ? Le rapprochement des noms doit alors distinguer les éditions (année, numéro).
- Retrouver le DOI manquant d'une notice HAL par son titre vaut pour tous les types de documents : chantier à part ?
- Points laissés en attente par le chantier [Types de documents](archived/2026-06-19_METIER_doc-types.md) : WoS `Article; Proceedings Paper`, posters et communications partageant un DOI.
