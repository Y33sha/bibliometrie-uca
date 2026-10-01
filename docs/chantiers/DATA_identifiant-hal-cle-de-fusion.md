# Chantier — Dépôts HAL distincts fusionnés par une notice OpenAlex ou ScanR

## Contexte

Des publications réunissent à tort des documents distincts, qui ont chacun leur dépôt HAL :

- une communication à un colloque, puis le chapitre ou l'article qui en est tiré ;
- un même travail présenté à plusieurs congrès ;
- plusieurs chapitres d'un même livre ;
- un livre et l'un de ses chapitres.

La fusion vient d'OpenAlex ou de ScanR, qui rapprochent ces dépôts : leur notice liste plusieurs identifiants HAL. Chaque identifiant listé est une clé de fusion ([keys.py](../../domain/source_publications/keys.py)). La notice réunit donc dans une même publication des notices HAL qui n'ont entre elles aucune clé commune.

Une notice OpenAlex ou ScanR relie 2 581 paires de notices HAL qui n'ont aucun identifiant commun (DOI, NNT, PMID), dans 1 790 publications. Les paires de même type, même titre et même année restent réunies par cette clé. En simulation, la règle retenue scinde 915 publications : 845 en deux, 70 en trois ou plus.

| Types des deux notices HAL | Paires | Même titre | Même année | Même conteneur |
|---|---|---|---|---|
| `conference_paper` / `conference_paper` | 621 | 94 % | 64 % | 9 % |
| `article` / `conference_paper` | 344 | 93 % | 35 % | 0 % |
| `conference_paper` / `poster` | 248 | 74 % | 79 % | 16 % |
| `article` / `article` | 184 | 91 % | 71 % | 0 % |
| `book_chapter` / `conference_paper` | 161 | 96 % | 12 % | 7 % |
| `book_chapter` / `book_chapter` | 140 | 43 % | 79 % | 61 % |
| `poster` / `poster` | 134 | 87 % | 74 % | 6 % |
| `book` / `book_chapter` | 59 | 5 % | 92 % | 0 % |

Ces fusions rendent aussi le type de la publication instable. La publication prend le type de sa notice HAL quand elle n'a ni notice Crossref ni notice DataCite. Si elle réunit deux notices HAL de types différents, l'une ou l'autre l'emporte selon le run. 424 publications sont dans ce cas.

## Décisions

- **La clé de fusion HAL d'une notice est le premier identifiant HAL qu'elle liste.** Une notice HAL porte le sien. Une notice ScanR ou OpenAlex rejoint la publication de la première notice HAL listée.
    - ScanR : la première listée est le dépôt HAL dont la notice est tirée (`halhal-…`).
    - OpenAlex : sur titre, type et année, la première listée concorde avec la notice OpenAlex dans 54 % des cas. Une autre concorde sans la première dans 15 % des cas.
- **Les autres identifiants HAL listés restent dans `external_ids`.** La phase `relations` relie les publications distinctes qui partagent un identifiant HAL.
- **Deux publications distinctes qui partagent une clé sont reliées**, qu'elles portent un DOI ou non.
- **Les doublons de dépôt HAL fusionnent par les autres clés** : DOI, ou type, titre et année identiques. Ceux qui diffèrent sur ces champs relèvent de la phase `metadata_correction`.

## Phasage

### 1. Clé de fusion HAL

- [x] `project_confirmation_keys` : seul le premier identifiant HAL listé donne un token de fusion.
- [x] Requête de voisinage de la réconciliation : égalité sur le premier identifiant HAL.
- [x] Migration : index btree sur le premier identifiant HAL, à la place de l'index GIN sur le tableau.
- [x] Tests : une notice OpenAlex listant deux notices HAL rejoint la première, et les deux notices HAL forment deux publications.

### 2. Relations entre publications à clé partagée

- [x] Requête des paires à clé partagée : retirer la condition sur les DOI.
- [x] Arête vers une publication sans DOI.
- [x] Tests : deux publications sans DOI qui partagent un identifiant HAL sont reliées.

### 3. Run et contrôle

- [x] `run_pipeline --from publications --rebuild-publications`.
- [x] Publications scindées : la base passe de 65 869 à 66 927 publications.
- [x] Relations entre les publications scindées : les 1 110 paires de publications séparées par la règle sont reliées. Les relations par clé partagée passent de 510 à 1 494, dont 1 121 `is_related_to`, 331 `is_preprint_of` et 29 `is_part_of`.
- [x] Publications 140244 et 22606 : une publication par dépôt HAL. La publication 11084 garde ses quatre dépôts : trois communications de même titre et de même année, et un poster que deux notices ScanR typées `other`, de même titre et de même année, relient aux communications.
- [x] Publications dont la source la plus prioritaire porte deux types : 67, contre 425.

### 4. Type des notices ScanR issues de HAL

Une notice ScanR issue de HAL porte souvent un type générique : 11 647 des 26 646 notices dont le dépôt HAL est en base ont un type différent du sien (8 393 communications et 1 865 posters typés `other`, des recensions et des synthèses typées `article`). Deux notices ScanR `other` de même titre et de même année relient alors deux dépôts HAL de types différents. Environ 37 des 67 publications dont la source décisive porte encore deux types sont dans ce cas.

- [x] Correction unaire : une notice ScanR issue de HAL prend le type corrigé de son dépôt HAL, calculé depuis la notice HAL.
- [ ] Run et contrôle : notices ScanR retypées, publications dont la source décisive porte deux types.

## Questions ouvertes

- **Arbitrage du type par consensus.** Le type d'une publication vient de la première source qui en porte un, dans l'ordre de priorité. Piste : un consensus des sources indépendantes, ScanR étant écarté quand sa notice est issue de HAL.
- **Doublons de dépôt HAL.** Deux dépôts du même document qui diffèrent par le type ou l'année restent séparés. Règles de convergence à définir dans `metadata_correction`.
- **Livres et chapitres de même DOI.** OpenAlex réunit un livre et ses chapitres quand leurs dépôts HAL portent le même DOI. La correction par DOI partagé les sépare côté HAL ; à vérifier côté OpenAlex après le run.
- **Chemins indirects.** 252 paires de notices HAL sont réunies par une troisième notice, sans pont direct ni DOI commun. Origine à examiner après le run.
