# Chantier — Parallélisation des extractions HTTP pipeline

Commencé le 2026-05-18

Terminé le 2026-05-21

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

Gain attendu : `max(temps_par_source)` au lieu de `sum(temps_par_source)`. Sur un full où OpenAlex domine, gain dépendant du poids relatif des autres sources.

Risques :
- Logs orchestrateur (`pipeline.log`) entrelacés — acceptable, les logs par-source restent propres.
- Pression sur la connexion DB SA : chaque extracteur ouvre sa propre connexion via `engine.begin()`, vérifier que le pool tolère 5 connexions concurrentes (par défaut `pool_size=5`, OK).
- Pression sur la mémoire si un extracteur garde en buffer toutes ses pages : a priori non, chaque extracteur insère au fil de l'eau.

### Phase 2 — Async sur les boucles par-document

ROI élevé : chaque appel est un round-trip indépendant, idéal pour `asyncio.gather` + `Semaphore`.

- [x] `enrich_oa_status.py` → async (Unpaywall, ~10 req/s recommandé). Pattern identique aux `fetch_missing_doi`. (commit f357786f)
- [x] `enrich_journal_apc.py` : laissé sync — déjà batch de 50 IDs par requête via filtre `openalex:A|B|C` (API OpenAlex Sources), volume de revues bien inférieur aux publications. Alignement auth seulement : `api_key` prioritaire, fallback `mailto` (comme les autres modules OpenAlex).
- [x] `refetch_truncated.py` → async (OpenAlex, `max_concurrent=3` polite pool). (commit faa5e486)

Pattern à reproduire :

1. `httpx.AsyncClient` partagé pour la durée du run.
2. `asyncio.Semaphore(max_concurrent)` dimensionné **sous** le rate-limit documenté.
3. `infrastructure/api_retry_async.http_request_with_retry_async` pour retry/backoff.
4. Îlot async encapsulé par `asyncio.run()` en début de phase ; reste du pipeline sync.
5. Inserts DB sérialisés via `Lock` + `to_thread` (modèle `fetch_missing_hal_id`) si écriture depuis la boucle ; sinon batch sync hors îlot.
6. Sur Windows : `WindowsSelectorEventLoopPolicy`.

### Phase 3 — Async sur les extracteurs — **abandonnée**

Décision 2026-05-21 : pas d'async sur les extracteurs paginés, ni WoS (seul candidat envisagé sérieusement) ni les autres.

Raisons :
- **HAL, theses.fr, ScanR, OpenAlex** : gain marginal après Phase 1 (les 5 sources tournent déjà en parallèle entre elles via ThreadPoolExecutor). Pagination cursor (OpenAlex) intrinsèquement séquentielle ; gain inter-pages sur les autres dominé par le wall-time de la source la plus lente, déjà parallélisée par Phase 1.
- **WoS** : seul candidat avec pages de 10 records (`WOS_PER_PAGE=10`), donc plus de pages à charger. Mais [`fetch_missing_doi.py:56-60`](../../infrastructure/sources/wos/fetch_missing_doi.py#L56) acte déjà un plafond prudent à ≈2 req/s (« API Clarivate instable historiquement, rate-limit serré »). Le quota annuel `X-REC-AmtPerYear-Remaining` est la contrainte structurelle, pas le wall-time. Et l'extracteur a un design « breather » (pause 15s toutes les 10 pages, 30s entre années) qui perd son sens en parallèle.

Alternative légère si besoin futur : abaisser `WOS_DELAY` ([api_limits.py:37](../../infrastructure/sources/api_limits.py#L37)) en restant sur l'extracteur séquentiel. Zéro effort d'implémentation, réversible.

### Phase 4 — HTTP/2 sur les clients async — **abandonnée sans bench**

Décision 2026-05-21 : NO-GO, et pas de bench préalable.

Raisons :
- Gain attendu marginal (5-15 % au premier batch, dilué par le keep-alive HTTP/1.1 qui amortit déjà le setup TCP+TLS).
- Sur la plupart des APIs cibles, le bottleneck est le rate-limit serveur (OpenAlex 10 req/s, WoS ≈2 req/s, Crossref polite pool), pas le client → gain réel probablement nul.
- Le seul candidat sérieux (Unpaywall sur Cloudflare) est déjà async depuis Phase 2 — le gain facile est pris.
- Coût de transmissibilité : dépendance binaire `h2` (HPACK), debug réseau binaire vs textuel, risque wheels Windows. Pas justifié pour un gain incertain ≤ 15 %.

À rouvrir uniquement si une API cible précise s'avère bottleneckée client et tourne sur un serveur HTTP/2 documenté.

## Implications observabilité

Avec Phase 1 (ThreadPool sur extracteurs) :
- ✅ `logs/infrastructure/sources/<source>/*.log` : non affectés, chaque extracteur écrit dans son propre fichier.
- ✅ Compteurs `PhaseMetrics` (new/updated/total) : exacts à condition de merger séquentiellement après `future.result()`.
- ⚠️ `pipeline.log` orchestrateur : messages des 5 extracteurs entrelacés. Lisible (préfixe logger), mais désordonné chronologiquement.
- ⚠️ Rapport markdown (`logs/reports/`) : `capture_log_offsets()` / `read_new_logs()` continuent de marcher (offset par fichier), pas d'impact.
