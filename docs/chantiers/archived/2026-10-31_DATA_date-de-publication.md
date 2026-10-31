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

## Décisions

- La date de publication (`publication_date`) a une précision (`publication_date_precision`) : année, mois ou jour. Une date à l'année tombe le 1er janvier, une date au mois le 1er du mois.
- `publication_year` reste, calculée depuis la date par PostgreSQL (colonne générée).
- La date d'un enregistrement source est celle du champ de date de sa source (tableau du contexte), et l'année en dérive. HAL : `publicationDate_s`, à défaut l'année `producedDateY_i`. Crossref : la première date plausible parmi `published`, `issued`, `published-online`, `published-print` et `approved`.
- OpenAlex et ScanR : le 1er janvier est ramené à l'année, le 1er d'un autre mois au mois.
- WoS garde sa date à l'année : la source n'est plus moissonnée.
- La date d'une publication est celle de la source prioritaire, précisée par les autres sources quand elles concordent : même année, et même mois quand la date retenue est au mois.
- Les listes de publications affichent l'année et se trient par date. La fiche publication affiche la date à sa précision (« 14 janv. 2025 »). L'export CSV donne l'année et la date ISO 8601 réduite à sa précision (« 2025-01 »).

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

- [x] Date et précision (année, mois, jour) sur les enregistrements sources et sur les publications (86bf8a5af)

### Phase 3 — Normalisation

- [x] Date de chaque source, avec sa précision. Jours fictifs ramenés à l'année ou au mois (539503b89)
- [x] Remise en conformité du stock depuis le raw store (`rewrite_publication_dates`, 539503b89). Les enregistrements sources absents du raw store et ceux de WoS gardent leur date à l'année.

### Phase 4 — Date de la publication

- [x] Arbitrage entre les dates des enregistrements sources ; la sauvegarde d'une publication écrit sa date (2b884962f)
- [x] `publication_year` en colonne générée depuis la date (bcf4d5710)

### Phase 5 — Usages

- [x] Tri des listes par date ; date sur la fiche publication, dans le tableau comparatif des sources et dans l'export CSV (9345eb0ce)

### Phase 6 — Documentation

- [x] Mise à jour de la documentation (9877e18b4)

## Questions ouvertes
