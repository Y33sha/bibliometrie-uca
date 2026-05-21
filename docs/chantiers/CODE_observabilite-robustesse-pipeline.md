# Chantier — Observabilité et robustesse du pipeline

Commencé le 2026-05-16
En standby en attendant d'avoir des données (plusieurs runs du pipeline)

## Contexte

Deux manques persistants sur la production du pipeline, identifiés de longue date mais jamais instruits comme chantier dédié :

1. **Aucun check automatique sur les données produites.** À l'issue d'un run pipeline, rien ne valide que les comptages sont plausibles, qu'on n'a pas explosé les orphelins (publications sans authorships, persons sans publications, etc.), ou qu'aucune anomalie statistique n'apparaît dans les distributions (years, doc_types, sources, OA status…). Un run silencieusement cassé peut passer en prod sans alerte. Cf. l'esprit des « tests de caractérisation » : on capture la forme attendue des données et on alerte sur la dérive.

2. **Dashboard métriques partiel.** Des éléments existent    (`/admin/pipeline` lit des rapports, certaines métriques de pool DB sont remontées) mais c'est éparpillé et fragile. Pas de vue consolidée temps de réponse / pool DB / taux d'erreur / durée des phases.

## Phases

- **Phase 1 — Sweep `subprocess → import`** (pré-requis de la persistance étendue des `PhaseMetrics`). État au démarrage : 12 phases pipeline déjà en import direct dans `run_pipeline.py` (via les helpers `_run_*`), 10 invocations encore en `subprocess.run`. Une invocation subprocess ne peut pas remonter de métriques typées à l'orchestrateur — il faut parser stdout. Le sweep migre chaque script restant vers `run(...) -> Metrics`.
- **Phase 2 — Snapshots de runs (observables + métriques) post-pipeline**, exposés via une page admin unique. Phase 2.1 = persistance des observables (livrée). Phase 2.2 = enrichissement du payload avec les `PhaseMetrics` + page admin (livrée).
- **Phase 3 — Robustesse runtime + clarté des logs**. Items indépendants : `statement_timeout` sur connexions pipeline (3.1), visibilité dans les UPDATE longs (3.2), clarification + harmonisation des logs d'extraction (3.3).

## Décisions

1. **Snapshot unique par run** : observables (état de la base après run) et `PhaseMetrics` (compteurs d'exécution par phase) cohabitent dans le même payload JSONB de `pipeline_check_snapshots` (à renommer en `pipeline_run_snapshots`). Deux vues du même événement, une seule page admin pour l'afficher.
2. **Observables = tests de caractérisation, pas tests fonctionnels.** Le but est de capturer la forme attendue (ranges, ratios, comptages) et d'alerter quand la sortie dérive — pas de figer une vérité.
3. **Sortie en fin de run = résumé console + JSON persisté en base.** Pas de notification email à ce stade — Laura lit les runs à la main, la page admin (Phase 2.2) ouvre l'historique.
4. **Pas d'outil externe.** Pas de Grafana, pas de Prometheus tant que l'app est mono-utilisateur. Page admin FastAPI/Svelte qui lit le JSON depuis la base, suffisant pour le périmètre actuel.

## Phasage

### Phase 1 — Sweep `subprocess → import`

- [x] Dataclass partagé `application/pipeline/_metrics.py:PhaseMetrics` (champs `new`/`updated`/`total`/`errors` + `extras: dict[str, int]` libre + `as_summary()` pour les logs, `merge()` pour les phases multi-helpers).
- [x] `SourceExtractor.run_as_phase(args) -> PhaseMetrics` ajouté à `infrastructure/sources/base.py` (variante non-CLI : laisse remonter les exceptions, retourne les métriques). `run()` reste le wrapper CLI standalone. `ExtractionStats` retiré, remplacé par `PhaseMetrics` dans les 5 extracteurs HAL/OA/WoS/ScanR/theses.
- [x] Logique des 4 autres scripts extraite en fonction importable : `refetch(conn, ...) -> PhaseMetrics`, `async fetch_missing_hal_ids(conn, ...) -> PhaseMetrics`, `detect_countries(conn, ...) -> PhaseMetrics`, `suggest_countries(conn, ...) -> PhaseMetrics`. Chaque `main()` argparse reste comme thin wrapper. `application/pipeline/fetch_missing_doi.run_async` retourne désormais un `PhaseMetrics` au lieu d'un `dict[str, int]`.
- [x] `run_pipeline.py` : remplacement des 10 appels `run_python(...)` par 10 nouveaux helpers `_run_extract_{hal,openalex,wos,scanr,theses}`, `_run_refetch_truncated`, `_run_fetch_missing_hal_id`, `_run_fetch_missing_doi`, `_run_detect_address_countries`, `_run_suggest_address_countries`. `phase_extract`/`phase_cross_imports`/`phase_countries` agrègent via `metrics.merge(...)` et retournent `PhaseMetrics`. L'orchestrateur collecte ces métriques dans `phase_metrics: dict[str, PhaseMetrics]` (consommé par Phase 2.2).
- [x] `run_python` et l'import `subprocess` retirés de `run_pipeline.py`. Plus aucun `subprocess.run` dans le pipeline orchestré.

### Phase 2 — Snapshots de runs post-pipeline

**Décisions actées au démarrage** (2026-05-21) :
- **Vocabulaire** : « observables » (ou « volumes attendus »), pas « invariants ». Un invariant ne varie pas ; ici on observe une dérive.
- **Pas de hiérarchie erreur/warning** : on ne peut pas savoir a priori si tel delta est possible ou non. Tout est signalé comme « suspect, à examiner ». Pas d'exit code non-zéro.
- **Mode dans le snapshot** : la comparaison se fait vs dernier snapshot **du même mode** (daily/weekly/full), sinon deltas faussés.
- **Runs partiels exclus** : pas de checks si `--only` / `--from`. Le snapshot n'a de sens que sur un run complet.
- **Stockage** : table dédiée `pipeline_check_snapshots(id, ran_at, mode, payload jsonb)`.
- **Sortie** : JSON en base. Résumé console structuré en fin de run (violations + deltas notables). Pas de fichier markdown intermédiaire — la page admin (Phase 2.2) lira le JSON.
- **Seuils** : hardcodés en première version.

#### Phase 2.1 — MVP CLI

- [x] Migration Alembic `pipeline_check_snapshots(id, ran_at, mode, payload jsonb)` + index `(mode, ran_at desc)`.
- [x] Module `infrastructure/observability/pipeline_checks.py` exposant `run_checks(conn, mode) -> CheckReport`, `persist_snapshot(conn, report)`, `render_summary(report)` (queries SQL + comparaison au dernier snapshot du même mode + détection des observables suspects).
- [x] Value objects `Observation` + `CheckReport` + `ObservablesPayload` en `application/ports/pipeline/checks.py` (zone neutre, importée par `infrastructure/observability/`).
- [x] Hook en fin de `run_pipeline.py` : exécution si run complet (pas `--only`/`--from`/`--dry-run`), persistance snapshot, résumé console.
- [x] Tests unit sur la logique de comparaison + détection (20 tests, sans BDD).

**Observables retenus** (livrés) :

| Famille | Observable | Seuil de suspicion |
|---|---|---|
| Volumes | publications, persons (non rejected), authorships (non excluded), addresses, `person_identifiers` (status ≠ rejected), `person_name_forms` (delta vs run précédent même mode) | delta ±5 % |
| Orphelins | publications sans authorships, persons sans publications | delta ±20 % |
| Distributions | ratios `doc_type` (sur publications), `source` (sur source_publications) | shift > 3 pts |
| Qualité matching | count `person_name_forms` ambiguës (≥ 2 `person_id` pour la même forme normalisée) | croissance > 10 % (asymétrique) |

Le delta « nouvelles ambiguës insérées par le run » est dérivé du delta sur le count global vs snapshot précédent.

#### Phase 2.2 — Persistance étendue + page admin (snapshot unique par run)

**Décision 2026-05-21** : un seul snapshot par run, un seul livrable UI. Au lieu de séparer « checks » (état post-run de la BDD) et « métriques » (compteurs d'exécution), on persiste l'ensemble dans le même payload JSONB du même snapshot — c'est deux vues du même événement.

- [x] Migration Alembic `a3f7b2c9d4e1` : rename `pipeline_check_snapshots` → `pipeline_run_snapshots`.
- [x] Payload étendu : `RunSnapshotPayload` = `observables` + `metrics_per_phase` (par phase : `new`/`updated`/`total`/`errors`/`extras`/`duration_s`) + `total_duration_s` + `sources` + `phases_run`. Hook `run_pipeline.py` adapté.
- [x] Endpoint `GET /api/admin/pipeline-runs` (liste résumée) + `GET /api/admin/pipeline-runs/{id}` (détail avec observations recalculées en comparant aux observables du snapshot précédent du même mode).
- [x] Page admin `/admin/pipeline` refondue avec deux onglets :
  - **Snapshots** (par défaut) : liste des derniers runs, drill-down par run (métadonnées, observations groupées par famille avec mise en évidence des suspectes, métriques par phase).
  - **Rapports** : structure existante (markdown) préservée.
- [ ] *(à voir à l'usage)* Vue historique en série temporelle (durées par phase / volumes / observations suspectes sur N runs). Pas urgent.

**Hors scope de ce livrable** (peuvent venir plus tard) :
- Métriques pool DB en temps réel (déjà partiellement remontées sur `/admin/pipeline`)
- Taux d'erreur HTTP par source (nécessiterait d'instrumenter les adapters async)

### Phase 3 — Robustesse runtime + clarté des logs

Items de fiabilité runtime et de lisibilité des logs du pipeline. Indépendants entre eux, à séquencer selon l'urgence rencontrée à l'usage.

#### Phase 3.1 — `statement_timeout` sur les connexions pipeline

PostgreSQL `statement_timeout` annule une requête qui dépasse N millisecondes (lève une `OperationalError` `QueryCanceled` côté SA). Posé sur les connexions du pipeline, il garantit qu'aucune requête ne reste pendante indéfiniment — au pire 10 min, puis interruption + log + escalade vers le `try/except` de phase qui marque l'erreur.

Valeur cible : **10 min** (à confirmer après une passe sur un run réel — il faut que ce soit largement au-dessus du percentile 99 des requêtes pipeline observées, sinon faux positifs sur des phases légitimement longues comme `propagate_is_corresponding`).

**Scope d'application — à trancher** : l'`Engine` SA est partagé entre API, pipeline orchestré et CLI. Trois approches :

- **A. `event.listens_for(engine, "connect")`** : SET le timeout à chaque nouvelle connexion. Simple, central, automatique. Mais s'applique aussi à l'API et aux CLI maintenance, certains endpoints admin (background tasks, propagation massive, cf. [`CODE_background-jobs.md`](CODE_background-jobs.md)) peuvent légitimement dépasser 10 min.
- **B. Helper `pipeline_conn(engine)`** : context manager qui ouvre une connexion + SET timeout. Scope précis, mais migration de 40+ call-sites `interfaces/cli/pipeline/*` + helpers `_run_*` de `run_pipeline.py`.
- **C. A + override par exception** : timeout global via `connect` listener + `SET LOCAL statement_timeout = '0'` dans les endpoints longs connus. Pragmatique : 99 % du code bénéficie du timeout, les exceptions sont explicites et reviewables.

Recommandation initiale : **C** (commencer avec un timeout global large — ex. 30 min — pour laisser respirer ce qui existe aujourd'hui, puis le resserrer au fil des observations).

**Catch + log** : SA lève `sqlalchemy.exc.OperationalError` avec `pgcode = '57014'` (query_canceled). Au niveau orchestrateur `run_pipeline.py`, le `try/except` autour de `fn(...)` capture déjà toute exception et logue l'erreur de phase — ajouter un cas spécifique pour `57014` qui logue clairement « **STATEMENT TIMEOUT** sur phase X — requête annulée après N s ».

- [ ] Trancher l'approche (A / B / C) après mesure des temps réels via les `metrics_per_phase` du Phase 2.2.
- [ ] Implémenter le scope choisi avec une constante centralisée (ex. `PIPELINE_STATEMENT_TIMEOUT_MS = 600_000`).
- [ ] Handler dédié dans `run_pipeline.py` pour distinguer un `query_canceled` d'une autre `OperationalError`.
- [ ] Documenter dans `docs/pipeline.md` (section robustesse) le mécanisme + comment l'override sur un endpoint admin.

#### Phase 3.2 — Visibilité dans les UPDATE longs

`propagate_is_corresponding`, `propagate_roles` et autres UPDATE batch n'émettent qu'un log avant + un log après. Pas de visibilité pendant l'exécution, ce qui rend impossible de distinguer « long mais avance » de « bloqué ».

Pistes (à arbitrer au moment d'implémenter) :
- Découper en batches explicites avec un `log.info` toutes les N rows.
- Ou `RAISE NOTICE` PostgreSQL dans une fonction stockée, capturé côté Python via `connection.info`.

- [ ] Identifier les UPDATE batch qui méritent l'instrumentation (probablement ceux qui dépassent ~1 min en pratique — les mesures de Phase 2.2 aideront).
- [ ] Choisir la mécanique (découpage en batches loggés / `RAISE NOTICE` / autre).

#### Phase 3.3 — Clarification + harmonisation des logs d'extraction

Logs ambigus relevés à l'usage, à élucider et harmoniser entre sources.

- [x] **Extracteur HAL — log d'aiguillage** : reformulé dans le commit `6d5dfa3` (chantier extract→Port). Format actuel : `Aiguillage <collection_code> : total=X, orphelins=Y, pages_full=Z, per_page=N → mode=<incremental|full>`. Sémantique transparente.
- [ ] **Heuristique `choose_extraction_mode`** (séparée du log) : la fonction de coût `n_orphans < full_fetch_pages` ignore la taille de payload par appel, d'où des choix sous-optimaux sur les collections umbrella (`PRES_UCA`/`PRES_CLERMONT`) où le full-fetch est catastrophiquement lent. Limite documentée dans le docstring de [`choose_extraction_mode`](../../domain/sources/hal_extract.py). Pistes : (a) borne dure sur les orphelins (« si `orphans < N`, toujours individuel »), (b) cost function pondérée payload via `hal_per_page_for`, (c) compteur empirique sur les derniers runs. Lien : [`DATA_cycle-vie-staging.md`](DATA_cycle-vie-staging.md) (Phase 1bis).
- [x] **CLI `create_persons_from_source_authorships`** : le log `"✓ Appliqué. → Lancer build_authorships.py pour propager in_perimeter/structure_ids"` (uniquement émis en CLI standalone, jamais par l'orchestrateur qui appelle `run()` directement) suggérait à tort une étape manuelle. Simplifié en `"✓ Appliqué."` — l'enchaînement vers `build_authorships` se fait via le pipeline.
- [x] **Harmonisation new/updated + cadence + préfixe source dans les logs des 5 extracteurs** :
  - **Distinguo new vs updated** : HAL/OA/WoS retournent désormais un `BatchInsertCounts(new, updated)` (port commun `application/ports/pipeline/extract/_common.py`) calculé via `RETURNING (xmax = 0)`. ScanR et theses.fr le faisaient déjà via leur pattern `upsert_doc/_these` avec check `is_new` côté Python. **Note sémantique OpenAlex** : `updated` compte désormais les `ON CONFLICT` déclenchés (« row touchée », même si le `CASE WHEN` n'a finalement rien modifié) — légèrement plus large que l'ancien « raw_hash a changé », mais aligné avec WoS/HAL.
  - **Cadence logs ScanR** : `SCANR_PER_PAGE` 500 → 200 (cohérent avec OpenAlex) + log de progression toutes les 500 docs au lieu de 2000.
  - **Préfixe source dans les logs** : chaque helper `_run_extract_*` de `run_pipeline.py` crée un logger nommé (`setup_logger("hal", ...)`, etc.) au lieu du logger global `pipeline`. Le `record.name` apparaît dans le format JSON (`"logger": "hal"`) et texte (`%(name)s`) — distingue les logs entrelacés en parallèle.
  - **Bilans finaux harmonisés** : les 5 extracteurs utilisent désormais le `log_summary` par défaut de `SourceExtractor` (`=== Terminé : as_summary ===` où `as_summary()` produit `N new, M updated, …`). Les surcharges custom de ScanR/theses.fr/WoS/HAL ont été retirées.

## Questions ouvertes

- **Page admin vs Grafana DSI** : si la DSI met en place sa propre
  observabilité (logs centralisés, Grafana…) une fois la
  transmission faite, la Phase 2.2 (page admin) peut devenir inutile
  — le JSON persisté en base reste exploitable par tout outil
  externe. À reconsidérer au moment de la transmission. En
  attendant, une page admin minimaliste suffit.
