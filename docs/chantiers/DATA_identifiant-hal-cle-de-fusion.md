# Chantier — Dépôts HAL distincts fusionnés par une notice OpenAlex ou ScanR

## Contexte

Des publications réunissent à tort des documents distincts, qui ont chacun leur dépôt HAL :

- une communication à un colloque, puis le chapitre ou l'article qui en est tiré ;
- un même travail présenté à plusieurs congrès ;
- plusieurs chapitres d'un même livre ;
- un livre et l'un de ses chapitres.

La fusion vient d'OpenAlex ou de ScanR, qui rapprochent ces dépôts : leur notice liste plusieurs identifiants HAL. Chaque identifiant listé est une clé de fusion ([keys.py](../../domain/source_publications/keys.py)). La notice réunit donc dans une même publication des notices HAL qui n'ont entre elles aucune clé commune.

Une notice OpenAlex ou ScanR est le seul lien de 2 581 paires de notices HAL, dans 1 790 publications.

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

- [ ] `project_confirmation_keys` : seul le premier identifiant HAL listé donne un token de fusion.
- [ ] Tests : une notice OpenAlex listant deux notices HAL rejoint la première, et les deux notices HAL forment deux publications.

### 2. Relations entre publications à clé partagée

- [x] Requête des paires à clé partagée : retirer la condition sur les DOI.
- [x] Arête vers une publication sans DOI.
- [x] Tests : deux publications sans DOI qui partagent un identifiant HAL sont reliées.

### 3. Run et contrôle

- [ ] `run_pipeline --from publications --rebuild-publications`.
- [ ] Publications scindées, et relations créées entre elles.
- [ ] Publications 140244, 22606 et 11084 : une publication par dépôt HAL.
- [ ] Publications dont la source la plus prioritaire porte deux types : décompte restant.

### 4. Documentation

- [ ] Mise à jour de la documentation.

## Questions ouvertes

- **Arbitrage du type par consensus.** Le type d'une publication vient de la première source qui en porte un, dans l'ordre de priorité. Piste : un consensus des sources indépendantes, ScanR étant écarté quand sa notice est issue de HAL.
- **Doublons de dépôt HAL.** Deux dépôts du même document qui diffèrent par le type ou l'année restent séparés. Règles de convergence à définir dans `metadata_correction`.
- **Livres et chapitres de même DOI.** OpenAlex réunit un livre et ses chapitres quand leurs dépôts HAL portent le même DOI. La correction par DOI partagé les sépare côté HAL ; à vérifier côté OpenAlex après le run.
- **Chemins indirects.** 252 paires de notices HAL sont réunies par une troisième notice, sans pont direct ni DOI commun. Origine à examiner après le run.
