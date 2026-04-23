# TODO Claude

## Suite de la refonte `domain/pipeline_modes.py`

- **Docs à mettre à jour** (`monthly` → `full`, 3 modes au lieu de 4) :
  - `README.md` (exemples `--mode`)
  - `docs/exploitation.md` (tableau de planification cron, ligne "monthly")
  - `docs/pipeline.md` (description des modes)
  - `docs/guide-utilisateur.md` (mention "modes weekly et monthly")
- **Crons server-side** : vérifier que les tâches planifiées n'appellent plus
  `--mode monthly` (remplacer par `--mode full`).
- **Harmonisation `extract_theses.py`** : accepter `--mode` et `--year` comme
  les autres extracteurs, pour uniformiser le traitement et permettre un
  éventuel `weekly` theses si besoin un jour (absence actuelle non justifiée
  par la source).

## Suite du split `cross_imports` → `fetch_missing_hal_id` + `fetch_missing_doi`

La phase `cross_imports` a été éclatée en deux phases distinctes, et les 4
scripts `cross_import_<source>.py` ont été fusionnés en un dispatcher unique
`interfaces/cli/pipeline/fetch_missing_doi.py` + un adapter par source dans
`infrastructure/sources/<source>/fetch_missing_doi.py`.

- **Docs à mettre à jour** :
  - `docs/pipeline.md` (section "Phase 2 — cross_imports" à scinder en 2a et 2b,
    références aux 4 scripts `cross_import_<source>.py` qui n'existent plus).
  - `CONTRIBUTING.md` (section "cross_imports" et "Script autonome
    `infrastructure/sources/<source>/cross_import_<source>.py`" — obsolètes).
  - `ROADMAP.md` ligne 194-195 (liste des scripts de cross-import).
- **Backoff `not_found_at` sur DOI** : pour limiter la croissance du pool de
  DOI retentés à chaque run, stocker un `not_found_at TIMESTAMP` sur les DOI
  qu'une source n'a pas pu résoudre, et ne les réessayer qu'après N jours
  (30 ?). Chantier séparé.
