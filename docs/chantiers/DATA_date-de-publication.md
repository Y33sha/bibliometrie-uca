# Chantier — Date de publication

## Contexte

Les enregistrements sources et les publications ont seulement une année (`publication_year`). Toutes les sources donnent une date plus précise, avec une précision variable :

| Source | Champ | Forme |
|---|---|---|
| HAL | `publicationDate_s` | année, mois ou jour |
| OpenAlex | `publication_date` | jour |
| Crossref | `issued` | année, mois ou jour ; `published-online` et `published-print` à part |
| DataCite | `dates` de type `Issued` | année ou jour ; `publicationYear` à défaut |
| ScanR | `publicationDate` | horodatage |
| WoS, API | `pub_info` : `coverdate` (« OCT 2024 »), `early_access_date`, `sortdate` | année, mois ou jour |
| WoS, export tabulé | `PY` (année), `PD` (« OCT 15 », sans année), `EA` (« OCT 2024 ») | année, mois ou jour |
| theses.fr | `dateSoutenance` | jour |

L'année des enregistrements sources HAL vient de `producedDateY_i`.

## Décisions

- La date de publication (`publication_date`) a une précision (`publication_date_precision`) : année, mois ou jour. Une date à l'année tombe le 1er janvier, une date au mois le 1er du mois.
- `publication_year` reste, calculée depuis la date par PostgreSQL (colonne générée).

## Phasage

### Phase 1 — Mesures

Mesures du 2026-10-30 sur tout le stock : 354 711 enregistrements sources, 79 901 publications (`interfaces/cli/oneshot/measure_publication_dates.py`, 3ffc6a8cb ; `data/measures/publication_dates.md`). 2 903 enregistrements sources sont absents du raw store (WoS : 2 549).

- [x] Précision des champs. HAL : jour 55 %, année 29 %, mois 17 %. Crossref `issued` : jour 52 %, mois 33 %, année 15 % ; illisible (`[[null]]`) dans 7 % des cas. DataCite `Issued` : présente dans 77 % des cas, à l'année dans 69 % de ceux-ci. theses.fr : `dateSoutenance` absente dans 14 % des cas. OpenAlex et ScanR : toujours au jour. L'année de `publicationDate_s` diffère de `producedDateY_i` dans 1 % des cas.
- [x] Dates d'OpenAlex et de ScanR au 1er du mois, confrontées aux autres sources d'une même publication. Pour les autres jours, le mois concorde dans 80 % des cas, le jour dans 85 %.
    - 1er janvier (OpenAlex 23 %, ScanR 8 %) : le mois concorde dans 27 % (OpenAlex) et 35 % (ScanR) des cas, le jour dans 10 % et 18 %. C'est un bouche-trou pour une année seule.
    - 1er d'un autre mois (OpenAlex 11 %, ScanR 8 %) : le mois concorde dans 97 % des cas, le jour dans 57 % et 62 %. C'est souvent un bouche-trou pour un mois seul.
- [x] Écarts de date entre les sources d'une même publication. L'année diffère dans 7 à 9 % des paires entre HAL, Crossref, WoS et OpenAlex ou ScanR, dans 1,7 % entre OpenAlex et ScanR. theses.fr concorde avec HAL, OpenAlex et ScanR dans 99 % des cas.
- [x] Crossref : date en ligne et date papier. Les deux sont présentes dans 27 % des cas. `issued` est alors la plus ancienne (98 %). La date papier est postérieure dans 66 % des cas, d'une autre année dans 20 %. Quand les deux dates diffèrent de mois, OpenAlex et ScanR donnent le mois en ligne (80 %). HAL donne le mois en ligne dans 48 % des cas, le mois papier dans 43 %.
- [x] Champs de date de WoS. 1 442 payloads de l'API, 22 395 lignes d'export tabulé. La date d'accès anticipé précède le mois de parution dans 81 % des cas, d'une autre année dans 20 %. `sortdate` est la plus ancienne des dates d'accès anticipé et de parution (91 %). Sans accès anticipé, quand `coverdate` est à l'année ou au mois, `sortdate` tombe toujours le 1er : ce jour est fictif.

### Phase 2 — Schéma

- [ ] Date et précision (année, mois, jour) sur les enregistrements sources et sur les publications.

### Phase 3 — Normalisation

- [ ] Date de chaque source, avec sa précision. Jours fictifs ramenés à l'année.
- [ ] Remise en conformité du stock depuis le raw store. Les enregistrements sources absents du raw store restent sans date.

### Phase 4 — Date de la publication

- [ ] Arbitrage entre les dates des enregistrements sources.
- [ ] `publication_year` en colonne générée depuis la date, une fois les écrivains passés à la date.

### Phase 5 — Usages

- [ ] Affichage de la date sur la fiche publication et dans les exports.

### Phase 6 — Documentation

- [ ] Mise à jour de la documentation.

## Questions ouvertes

- Date d'une publication : la plus ancienne, la plus précise, celle de la source prioritaire ; date en ligne ou date papier.
- Date d'une thèse : date de soutenance.
- 1er d'un autre mois chez OpenAlex et ScanR : jour gardé, ou ramené au mois.
