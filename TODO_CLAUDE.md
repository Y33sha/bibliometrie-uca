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
