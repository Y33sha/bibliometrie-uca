# Chantier — Parallélisation des extractions HTTP pipeline

## Contexte

Le pipeline fait beaucoup d'appels HTTP à des APIs sources (OpenAlex, HAL, WoS, ScanR, theses.fr) et à des APIs d'enrichissement (Unpaywall, DOAJ). Tant que ces appels sont synchrones et exécutés en série, on plafonne au QPS du client, pas du serveur.

Une migration partielle est déjà engagée : `fetch_missing_doi` (les 5 adapters) et `fetch_missing_hal_id` ont basculé sur `httpx.AsyncClient` + `asyncio.Semaphore` par source. Gain mesuré sur OpenAlex pour `fetch_missing_doi` : **18 req/s vs ~5 req/s plafond sync, soit ×3.6**.

Le reste à traiter se divise en deux familles aux ROI très différents :

- **Boucles par-document** (1 round-trip par DOI/work, embarrassingly parallel) → gros gain potentiel via async.
- **Extracteurs avec pagination cursor/offset** → gain modéré (pagination intrinsèquement séquentielle), mais on peut paralléliser les sources entre elles avec un simple `ThreadPoolExecutor` sans toucher au code des extracteurs.

## État actuel

| Module | État | Pattern |
|---|---|---|
| `infrastructure/sources/openalex/fetch_missing_doi.py` | ✅ async | `httpx.AsyncClient`, `max_concurrent=3` |
| `infrastructure/sources/hal/fetch_missing_doi.py` | ✅ async | `httpx.AsyncClient`, `max_concurrent=5` |
| `infrastructure/sources/wos/fetch_missing_doi.py` | ✅ async | `httpx.AsyncClient`, `max_concurrent=3` |
| `infrastructure/sources/scanr/fetch_missing_doi.py` | ✅ async | `httpx.AsyncClient`, `max_concurrent=5` |
| `infrastructure/sources/crossref/fetch_missing_doi.py` | ✅ async | `httpx.AsyncClient`, `max_concurrent=3` (polite pool) |
| `infrastructure/sources/hal/fetch_missing_hal_id.py` | ✅ async | `httpx.AsyncClient` + `Semaphore` + inserts sync via `Lock` + `to_thread` |
| `application/pipeline/enrich/enrich_oa_status.py` | ❌ `requests` | Unpaywall, 1 query par DOI |
| `application/pipeline/enrich/enrich_journal_apc.py` | ❌ `requests` | DOAJ, 1 query par journal |
| `infrastructure/sources/openalex/refetch_truncated.py` | ❌ `requests` | OpenAlex, 1 query par work tronqué |
| `infrastructure/sources/base.py` + 5 extracteurs `extract_*.py` | ❌ `requests` sync série | ~1400 LOC, pagination cursor/offset selon source |

Snapshot au démarrage du chantier. Ne pas maintenir pendant le chantier (utiliser git pour ça) ; à réviser si interruption et reprise.

## Phasage

Ordre par ROI décroissant **et** complexité croissante.

### Phase 1 — Paralléliser les 5 extracteurs (ThreadPoolExecutor)

Sans toucher au code interne des extracteurs : lancer les 5 en parallèle dans `phase_extract` (run_pipeline.py:79).

- [x] Wrapper les appels `_run_extract_*` dans un `ThreadPoolExecutor` (max_workers = nombre d'extracteurs sélectionnés).
- [x] Récupérer chaque `PhaseMetrics` via `future.result()` puis merger séquentiellement dans le thread principal (la merge n'est pas thread-safe).
- [x] Vérifier qu'aucun extracteur ne dépend de l'état d'un autre (chacun cible une table `staging.*` distincte ; chaque helper ouvre/ferme sa propre connexion).
- [ ] Bench avant/après sur un run `--mode full --sources hal,openalex,wos,scanr,theses` → mentionner dans le commit.

Gain attendu : `max(temps_par_source)` au lieu de `sum(temps_par_source)`. Sur un full où OpenAlex domine, gain dépendant du poids relatif des autres sources.

Risques :
- Logs orchestrateur (`pipeline.log`) entrelacés — acceptable, les logs par-source restent propres.
- Pression sur la connexion DB SA : chaque extracteur ouvre sa propre connexion via `engine.begin()`, vérifier que le pool tolère 5 connexions concurrentes (par défaut `pool_size=5`, OK).
- Pression sur la mémoire si un extracteur garde en buffer toutes ses pages : a priori non, chaque extracteur insère au fil de l'eau.

### Phase 2 — Async sur les boucles par-document

ROI élevé : chaque appel est un round-trip indépendant, idéal pour `asyncio.gather` + `Semaphore`.

- [ ] `enrich_oa_status.py` → async (Unpaywall, ~10 req/s recommandé). Pattern identique aux `fetch_missing_doi`.
- [ ] `enrich_journal_apc.py` → async (DOAJ).
- [ ] `refetch_truncated.py` → async (OpenAlex, `max_concurrent=3` polite pool).

Pattern à reproduire :

1. `httpx.AsyncClient` partagé pour la durée du run.
2. `asyncio.Semaphore(max_concurrent)` dimensionné **sous** le rate-limit documenté.
3. `infrastructure/api_retry_async.http_request_with_retry_async` pour retry/backoff.
4. Îlot async encapsulé par `asyncio.run()` en début de phase ; reste du pipeline sync.
5. Inserts DB sérialisés via `Lock` + `to_thread` (modèle `fetch_missing_hal_id`) si écriture depuis la boucle ; sinon batch sync hors îlot.
6. Sur Windows : `WindowsSelectorEventLoopPolicy`.

### Phase 3 — Async sur les extracteurs (optionnel, ROI faible)

Hypothèse à réviser : la pagination cursor (OpenAlex) est intrinsèquement séquentielle (cursor[N+1] dépend de la réponse N). HAL et theses.fr en offset sont parallélisables page par page, mais le gain après Phase 1 est marginal.

À ouvrir uniquement si Phase 1 + 2 ne suffisent pas en pratique, ou si on doit retoucher `base.py` pour autre chose.

Si on s'y attaque :
- `base.py` : migrer le boilerplate (exceptions, cycle connexion, User-Agent) vers un `AsyncExtractorBase`.
- HAL, theses.fr : parallélisme inter-pages.
- OpenAlex : parallélisme inter-années (`asyncio.gather` sur N tâches « extraire année Y »).
- ScanR, WoS : rate-limit contractuel strict, parallélisme limité.

### Phase 4 — HTTP/2 sur les clients async (optionnel, à valider avant lancement)

**Pré-requis : Phase 2 terminée.** HTTP/2 sans parallélisme côté client = aucun gain (le multiplexing ne sert qu'avec des requêtes concurrentes). Sur les extracteurs ThreadPool (Phase 1, 1 thread par source), HTTP/2 ne change rien — hors scope.

Hypothèse : sur les clients async (`fetch_missing_doi/*`, `fetch_missing_hal_id`, et les enrichissements Phase 2), HTTP/2 économise des connexions TCP+TLS. Gain attendu : 5-15% sur le throughput au premier batch, dilué ensuite par le keep-alive HTTP/1.1 qui amortit déjà le setup.

Sur la plupart des APIs cibles, le bottleneck est le rate-limit serveur (OpenAlex 10 req/s, WoS, Crossref polite), pas le client. Donc le gain réel peut être nul.

**Approche : mesurer avant d'activer largement.**

- [ ] Ajouter `h2` aux dépendances (`pyproject.toml`, ~5 sous-paquets) et vérifier que ça n'introduit pas de souci de wheels sur Windows.
- [ ] Activer `http2=True` sur **un seul** client async — candidat : Unpaywall via `enrich_oa_status` après Phase 2 (volume élevé, max_concurrent ~10, serveur sur Cloudflare donc HTTP/2 quasi-certain).
- [ ] Vérifier que le serveur négocie effectivement HTTP/2 (logger la version protocole via `response.http_version`).
- [ ] Bench A/B sur un run réel : HTTP/1.1 vs HTTP/2, ≥5 000 requêtes. Comparer throughput, latence p50/p95, nombre de connexions TCP ouvertes.
- [ ] **Seuil de décision : si gain throughput < 10 %, fermer Phase 4 sans généraliser** (le coût de maintenance — dépendance `h2`, branche fallback, debug binaire — ne se justifie pas).
- [ ] Si gain ≥ 10 % : généraliser aux 5 `fetch_missing_doi/*`, `fetch_missing_hal_id`, `enrich_journal_apc`, `refetch_truncated`. Documenter le `http_version` observé par API dans la fiche pour suivi.

Risques :
- Une API serveur sans HTTP/2 fait fallback silencieux en HTTP/1.1 (httpx gère) — pas de régression, mais le gain attendu disparaît pour cette API.
- `h2` package introduit du code binaire (HPACK). Sur Windows, vérifier le pip install.
- Debug réseau plus dur (HTTP/2 binaire vs HTTP/1.1 textuel) — Wireshark / curl `--http2` requis pour inspection.

## Implications observabilité

Avec Phase 1 (ThreadPool sur extracteurs) :
- ✅ `logs/infrastructure/sources/<source>/*.log` : non affectés, chaque extracteur écrit dans son propre fichier.
- ✅ Compteurs `PhaseMetrics` (new/updated/total) : exacts à condition de merger séquentiellement après `future.result()`.
- ⚠️ `pipeline.log` orchestrateur : messages des 5 extracteurs entrelacés. Lisible (préfixe logger), mais désordonné chronologiquement.
- ⚠️ Rapport markdown (`logs/reports/`) : `capture_log_offsets()` / `read_new_logs()` continuent de marcher (offset par fichier), pas d'impact.
