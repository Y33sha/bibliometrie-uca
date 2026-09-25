# Chantier — Conférences et actes

## Contexte

Le type `conference_paper` regroupe tout ce qui relève d'une conférence : texte publié dans des actes, résumé, communication orale. Le chantier vise à distinguer le texte publié dans des actes (`conference_paper`) de la communication (type « conférence », à créer).

Les volumes d'actes sont des monographies (`monographs.proceedings`), rattachées à leur série dans `journals` (chantier [Monographies](DATA_monographies.md)).

### Traces de publication

Mesure du 2026-09-25 : 12 874 `conference_paper` dans le périmètre, classés par leur trace la plus forte.

| Trace | Communications |
|---|---|
| Volume d'actes (monographie) | 1 916 |
| Série d'actes ou collection, sans volume | 22 |
| Revue | 1 072 |
| DOI seul | 103 |
| Conteneur de type `unknown` | 5 |
| Aucune | 9 756 |

Une communication sans trace a pu paraître dans des actes absents de la base, ou n'avoir donné lieu à aucun texte.

### Répartition

Mesures du 2026-09-12, sur le périmètre.

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

- **Type de l'entrée `journals`.** `proceedings` et `book_series` désignent des actes. Des séries d'actes sont typées `journal` (IFAC-PapersOnLine, AIP Conference Proceedings, LIPIcs) ou `book_series` (CCIS, IFIP AICT, Lecture Notes in Networks and Systems). OpenAlex écrit le type, seulement sur une entrée de type `unknown`.
- **Volume d'actes.** Le drapeau `proceedings` d'une monographie est parfois faux : Conference Proceedings of the Society for Experimental Mechanics compte 11 volumes marqués livres pour 2 marqués actes, LNCS 34 volumes marqués livres.
- **Résumés de congrès publiés en revue.** Environ 175 sont repérables : 104 dans 14 revues de résumés (Goldschmidt Abstracts, Abstracts with programs de la GSA…), 82 en numéro de supplément. 392 `article` paraissent aussi en numéro de supplément.
- **Crossref.** 2 509 des 2 697 communications à DOI ont un enregistrement Crossref. IEEE et ACM donnent `proceedings-article`, le titre des actes et l'événement, sans ISBN. Le volume IEEE a son propre enregistrement (type `proceedings`) avec ISBN ; son DOI est celui de la communication privé de son dernier segment. Springer donne `book-chapter` avec l'ISBN du volume et la collection. Elsevier donne `journal-article`. `source_publications.meta` garde le nom et l'acronyme du congrès.
- **Résumés.** `meeting abstract` (WoS) et `conference-abstract` (Crossref) donnent `conference_paper`, comme les textes d'actes.
- **HAL**, deux échantillons de 200. Sur 350 communications, `isbn_s` est rempli 8 fois, `bookTitle_s` jamais, `serie_s` parfois, `conferenceTitle_s` toujours. Les ISBN sont lus dans la notice TEI. L'indicateur « avec actes » (`proceedings_s`, non extrait) est rempli presque partout et contredit la revue dans des cas nets (volumes LNCS déclarés sans actes). Il est saisi à la main ; sa fiabilité reste à établir.
- **Recherche externe**, 30 communications d'informatique et de sciences de l'ingénieur sans DOI ni revue. Crossref retrouve la communication par son titre 2 fois (similarité 0,99), le volume par le nom du colloque 1 fois. Les échecs : rencontres françaises sans actes à DOI (la moitié de l'échantillon), congrès internationaux à résumés seuls, actes sans DOI Crossref, éditions pas encore parues. IEEE Xplore et DBLP refusent les requêtes automatiques ; l'API IEEE demande une clé.

### `container_title` sans `journal_id`

- 21 446 publications, 12 032 titres distincts. Le champ porte le nom du colloque (communications 9 734, posters 1 851), le titre du livre (chapitres 3 425) ou le nom d'une archive (prépublications, jeux de données).
- 1 114 correspondent au titre d'une entrée de `journals` : archives 962, revues 102, titre porté à la fois par une revue et une archive 28.
- 440 chapitres ont pour contenant le titre d'un livre en base (193 livres).
- 9 734 communications donnent 7 880 noms de colloque distincts ; 989 sont portés par au moins deux publications.

## Décisions

- Le renommage de `journals` n'est pas prioritaire.
- Les volumes d'actes vivent dans `monographs` ; `journals` porte les séries.
- `conference_paper` désigne un texte publié dans des actes : volume ou série d'actes, `proceedings-article` Crossref, chapitre rattaché à un congrès.
- Le type « conférence » désigne une communication sans texte publié, résumés compris (`meeting abstract`, `conference-abstract`, revues de résumés, numéros de supplément). Il appartient à la famille « Annexes et divers » des filtres.
- La décision se prend sur tous les enregistrements d'une publication (`domain/publications/conference.py`). Un enregistrement qui désigne une communication (résumé, présentation, recueil de résumés HAL) l'emporte sur `article`, `conference_paper` et `preprint`. Une `conference_paper` qu'aucun enregistrement n'atteste devient une `conference`. Attestent une publication : DOI, revue, monographie, congrès déclaré par Crossref ; pour HAL, en outre, `proceedings_s` = 1, une plage de pages, un éditeur, une collection ou un titre de source distinct du congrès. OpenAlex et ScanR recopient les communications HAL en `conference_paper` sans attestation : ces copies ne comptent pas.
- Crossref : un `posted-content` de sous-type `preprint` est un preprint, de sous-type `other` jamais. Copernicus dépose les résumés de ses réunions en `posted-content` de sous-type `other`, avec la forme de présentation en `group-title` : `oral` et `pico` donnent `conference`, `display` donne `poster`.
- La communication et le texte d'actes qui en est issu restent un seul type, `conference_paper`. Leur dédoublonnage (titre proche, année à un an près) relève d'un chantier à part : la clé de rapprochement exige type, titre normalisé et année identiques. Sur 9 631 communications sans trace, 393 ont un jumeau non fusionné.

## Phasage

### Phase 1 — Définitions
- [x] Définir `conference_paper` et le type « conférence »
- [x] Classer le résumé publié en revue (numéro de supplément, revue de résumés)

### Phase 2 — Signaux
- [x] Tester la fiabilité de `proceedings_s`. Lu dans l'API HAL pour 13 085 communications du périmètre, croisé avec leur trace en base :

    | Trace | `proceedings_s` = 1 | = 0 | vide |
    |---|---|---|---|
    | Volume d'actes | 686 | 544 | 330 |
    | Revue | 278 | 468 | 482 |
    | DOI seul | 41 | 39 | 8 |
    | Aucune | 1 465 | 8 499 | 225 |

    La valeur 0 est fausse pour 44 % des communications à volume d'actes : actes IEEE, ACM, Winter Simulation Conference déclarés sans actes. Sans trace en base, les deux valeurs se distinguent. Sur 30 notices à 1, 22 portent des pages, un éditeur, un ISBN, une série ou un titre de source ; plusieurs sont des recueils de résumés (« Book of abstracts », « Recueil des résumés »). Sur 30 notices à 0, une seule porte l'un de ces champs.
- [x] Lire les ISBN de HAL, dans la notice TEI (chantier Monographies)
- [x] Importer l'enregistrement Crossref des communications à DOI (type, ISBN, congrès)
- [ ] Reconnaître les résumés publiés en numéro de supplément
- [ ] Retyper les séries d'actes classées `journal` ou `book_series`. Audit d'une règle à la majorité des monographies : correcte pour l'essentiel de `book_series` à `proceedings` (29 séries, dont quelques séries mixtes à vérifier) ; fausse sur les revues, où elle retype European Respiratory Journal et manque Journal of Physics: Conference Series.
- [ ] Vérifier le drapeau `proceedings` des monographies

### Phase 3 — Volumes d'actes
- [x] Identifier un volume : ISBN, titre, éditeur, collection (chantier Monographies)
- [x] Dédoublonner les volumes
- [x] Rattacher les communications à leur volume

### Phase 4 — Recherche externe
- [ ] Retrouver par son titre le DOI d'une communication sans DOI, dans les disciplines à actes
- [ ] Évaluer l'API IEEE

### Phase 5 — `container_title`
- [x] Rattacher les chapitres à leur livre en base (chantier Monographies)
- [ ] Traiter les noms d'archive

### Phase 6 — Type `conference`
- [x] Valeur `conference` de l'enum `doc_type`, libellé « Conférence », famille « Annexes et divers ». WoS `meeting abstract` et OpenAlex `conference-abstract` y mènent (`fa8c7f8b4`).
- [x] Extraction HAL de `proceedings_s`, `serie_s` et `source_s`, rangés dans `meta` (`68cae439d`). Les pages et l'éditeur sont déjà dans `biblio`.
- [x] Crossref : sous-type des `posted-content` et forme de présentation des résumés Copernicus (`5d22d3fb0`).
- [x] Arbitrage entre communication et texte d'actes, dans l'agrégation (`9b86794d2`).
- [x] Une communication HAL qui porte un ISBN reçoit son volume d'actes, titré par la source ou le congrès (`eb990381d`).
- [ ] Ré-extraction HAL complète, renormalisation Crossref, puis mesure.

## Questions ouvertes

- Le colloque, en tant qu'événement, mérite-t-il une entité distincte des actes ? Le rapprochement des noms doit alors distinguer les éditions (année, numéro).
- Retrouver le DOI manquant d'une notice HAL par son titre vaut pour tous les types de documents : chantier à part ?
- Points laissés en attente par le chantier [Types de documents](archived/2026-06-19_METIER_doc-types.md) : WoS `Article; Proceedings Paper`, posters et communications partageant un DOI.
