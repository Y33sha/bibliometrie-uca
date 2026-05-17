# Chantier — Observabilité et robustesse du pipeline

Commencé le 2026-05-16

## Contexte

Deux manques persistants sur la production du pipeline, identifiés de
longue date mais jamais instruits comme chantier dédié :

1. **Aucun check automatique sur les données produites.** À l'issue
   d'un run pipeline, rien ne valide que les comptages sont
   plausibles, qu'on n'a pas explosé les orphelins (publications
   sans authorships, persons sans publications, etc.), ou qu'aucune
   anomalie statistique n'apparaît dans les distributions
   (years, doc_types, sources, OA status…). Un run silencieusement
   cassé peut passer en prod sans alerte. Cf. l'esprit des « tests de
   caractérisation » : on capture la forme attendue des données et on
   alerte sur la dérive.

2. **Dashboard métriques partiel.** Des éléments existent
   (`/admin/pipeline` lit des rapports, certaines métriques de pool DB
   sont remontées) mais c'est éparpillé et fragile. Pas de vue
   consolidée temps de réponse / pool DB / taux d'erreur / durée des
   phases.

## Volets

- **Volet 0 — Sweep `subprocess → import`** (pré-requis du Volet B). État actuel hybride : 12 phases déjà en import direct dans `run_pipeline.py` (via les helpers `_run_*`), 10 invocations encore en `subprocess.run` (les 5 extracteurs + `refetch_truncated`, `fetch_missing_hal_id`, `fetch_missing_doi`, `detect_address_countries`, `suggest_address_countries`). Une invocation subprocess ne peut pas remonter de métriques typées à l'orchestrateur — il faudrait parser stdout. On finit donc le sweep : chaque script restant expose `run(...) -> Metrics`, l'orchestrateur appelle des fonctions et reçoit la struct typée. Pas de perte d'isolation processus en pratique : le `try/except` autour des phases capture déjà les exceptions. Coût estimé ~3-5 h.
- **Volet A — Checks automatiques post-pipeline**. Indépendant : consomme l'état final de la base, pas les métriques de phases.
- **Volet B — Dashboard métriques**. Suppose Volet 0 fait.

## Décisions

1. **Deux volets séparés** (checks data / dashboard), pilotables
   indépendamment. Le volet checks peut démarrer immédiatement ; le
   volet dashboard attend A'.
2. **Checks = tests de caractérisation, pas tests fonctionnels.** Le
   but est de capturer la forme attendue (ranges, ratios, comptages)
   et d'alerter quand la sortie dérive — pas de figer une vérité.
3. **Sortie des checks = rapport lisible + exit code.** Format à
   trancher (JSON pour intégration future, markdown pour lecture).
   Pas de notification email à ce stade — Laura lit les runs à la
   main.
4. **Pas d'outil externe pour le dashboard.** Pas de Grafana, pas de
   Prometheus tant que l'app est mono-utilisateur. Page admin
   FastAPI/Svelte qui lit les JSON métriques et la base, c'est
   suffisant pour le périmètre actuel.

## Phasage

### Volet 0 — Sweep `subprocess → import`

- [x] Dataclass partagé `application/pipeline/_metrics.py:PhaseMetrics` (champs `new`/`updated`/`total`/`errors` + `extras: dict[str, int]` libre + `as_summary()` pour les logs, `merge()` pour les phases multi-helpers).
- [x] `SourceExtractor.run_as_phase(args) -> PhaseMetrics` ajouté à `infrastructure/sources/base.py` (variante non-CLI : laisse remonter les exceptions, retourne les métriques). `run()` reste le wrapper CLI standalone. `ExtractionStats` retiré, remplacé par `PhaseMetrics` dans les 5 extracteurs HAL/OA/WoS/ScanR/theses.
- [x] Logique des 4 autres scripts extraite en fonction importable : `refetch(conn, ...) -> PhaseMetrics`, `async fetch_missing_hal_ids(conn, ...) -> PhaseMetrics`, `detect_countries(conn, ...) -> PhaseMetrics`, `suggest_countries(conn, ...) -> PhaseMetrics`. Chaque `main()` argparse reste comme thin wrapper. `application/pipeline/fetch_missing_doi.run_async` retourne désormais un `PhaseMetrics` au lieu d'un `dict[str, int]`.
- [x] `run_pipeline.py` : remplacement des 10 appels `run_python(...)` par 10 nouveaux helpers `_run_extract_{hal,openalex,wos,scanr,theses}`, `_run_refetch_truncated`, `_run_fetch_missing_hal_id`, `_run_fetch_missing_doi`, `_run_detect_address_countries`, `_run_suggest_address_countries`. `phase_extract`/`phase_cross_imports`/`phase_countries` agrègent via `metrics.merge(...)` et retournent `PhaseMetrics`. L'orchestrateur collecte ces métriques dans `phase_metrics: dict[str, PhaseMetrics]` (consommé par Volet B).
- [x] `run_python` et l'import `subprocess` retirés de `run_pipeline.py`. Plus aucun `subprocess.run` dans le pipeline orchestré.

### Volet A — Checks automatiques post-pipeline

- [ ] **Inventorier les invariants attendus** sur les données
  produites. Au minimum :
  - Comptages : publications actives, persons, authorships,
    structures, addresses (deltas vs run précédent)
  - Orphelins : publications sans authorships, persons sans
    publications, authorships sans person, source_authorships
    sans authorship_id
  - Distributions : years (queue/médiane/mode), doc_types,
    sources, OA status
  - Cohérence : `truth_authorships` ⊆ `authorships`, totaux
    `source_authorships` par source cohérents avec les staging
- [ ] **Implémenter un module `application/pipeline/checks.py`**
  exposant `run_checks(conn) -> CheckReport` (queries SQL, calcul
  des deltas, comparaison à un snapshot du run précédent stocké en
  base).
- [ ] **Hook en fin de `run_pipeline.py`** : exécution
  automatique, exit code non-zéro si seuil critique dépassé.
- [ ] **Page admin** affichant le dernier rapport (réutilise
  l'infrastructure de `/admin/pipeline`).

### Volet B — Dashboard métriques

**Bloqué tant que Volet 0 n'est pas appliqué.**

- [ ] **Modèle de données métriques** : qu'est-ce qu'on stocke,
  comment (table dédiée ? `logs/metrics/*.json` parsés à la
  demande ?).
- [ ] **Page `/admin/metrics`** : agrégation des
  `logs/metrics/<phase>.json` (option A') + métriques pool DB
  (déjà remontées) + taux d'erreur HTTP par source (à exposer
  depuis les adapters async).
- [ ] **Vue historique** : N derniers runs en série temporelle
  (durée par phase, volumes, taux d'erreur).

## Questions ouvertes

- **Format de stockage du snapshot** pour la comparaison
  inter-runs (volet A) : table dédiée, fichier JSON sur disque,
  ou colonne sur `audit_log` ? Trancher avant d'implémenter.
- **Seuils d'alerte** : on les hardcode ou on les rend
  configurables ? Probablement hardcodés au début, configurables
  plus tard si besoin.
- **Volet B vs Grafana DSI** : si la DSI met en place sa propre
  observabilité (logs centralisés, Grafana…) une fois la
  transmission faite, le volet B peut devenir inutile. À
  reconsidérer au moment de la transmission. En attendant, une
  page admin minimaliste suffit.
