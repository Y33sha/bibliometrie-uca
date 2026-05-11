# Chantier — Async des extractions HTTP pipeline

## Contexte

Le pipeline fait beaucoup d'appels HTTP à des APIs sources
(OpenAlex, HAL, WoS, ScanR, CrossRef, theses.fr, Unpaywall) et à
des APIs d'enrichissement (Unpaywall, DOAJ pour les APC). Tant que
ces appels sont synchrones (`requests`), chaque round-trip bloque ;
on plafonne au QPS du client, pas du serveur.

Une migration partielle est déjà engagée : `fetch_missing_doi`
(les 5 adapters) et `fetch_missing_hal_id` ont basculé sur
`httpx.AsyncClient` + `asyncio.Semaphore` par source. Gain mesuré
sur OpenAlex pour `fetch_missing_doi` : **18 req/s vs ~5 req/s
plafond sync, soit ×3.6**.

Il reste les scripts d'enrichissement, le refetch ciblé OpenAlex,
et les 5 extracteurs principaux (~1400 LOC). Ce chantier les
termine.

## État actuel

| Module | État | Pattern |
|---|---|---|
| `infrastructure/sources/openalex/fetch_missing_doi.py` | ✅ async | `httpx.AsyncClient`, `max_concurrent=3` |
| `infrastructure/sources/hal/fetch_missing_doi.py` | ✅ async | `httpx.AsyncClient`, `max_concurrent=5` |
| `infrastructure/sources/wos/fetch_missing_doi.py` | ✅ async | `httpx.AsyncClient`, `max_concurrent=3` |
| `infrastructure/sources/scanr/fetch_missing_doi.py` | ✅ async | `httpx.AsyncClient`, `max_concurrent=5` |
| `infrastructure/sources/crossref/fetch_missing_doi.py` | ✅ async | `httpx.AsyncClient`, `max_concurrent=3` (polite pool) |
| `infrastructure/sources/hal/fetch_missing_hal_id.py` | ✅ async | `httpx.AsyncClient` + `Semaphore` + inserts sync via `Lock` + `to_thread` |
| `application/pipeline/enrich/enrich_oa_status.py` | ❌ `requests` | Unpaywall, 10 req/s recommandé |
| `application/pipeline/enrich/enrich_journal_apc.py` | ❌ `requests` | DOAJ |
| `infrastructure/sources/openalex/refetch_truncated.py` | ❌ `requests` | OpenAlex, re-fetch individuel des works tronqués à 100 auteurs |
| `infrastructure/sources/base.py` (et 5 extracteurs `extract_*.py`) | ❌ `requests` | ~1400 LOC, pagination cursor/offset/firstRecord selon source |

Cette table reflète l'état au démarrage du chantier ; ne pas la
maintenir à jour pendant le chantier (utiliser git pour ça). À
réviser uniquement si le chantier est interrompu et repris.

## Approche établie

Pattern utilisé par les adapters déjà migrés, à reproduire :

1. `httpx.AsyncClient` partagé pour la durée d'un run.
2. `asyncio.Semaphore(max_concurrent)` par source, dimensionné
   **sous** le rate-limit documenté.
3. `infrastructure/api_retry_async.http_request_with_retry_async`
   pour le retry/backoff (déjà en place).
4. Îlot async encapsulé par un `asyncio.run()` en début de phase ;
   le reste du pipeline reste sync. Pas de propagation d'async dans
   l'orchestrateur.
5. Inserts DB sérialisés via `Lock` + `to_thread` (modèle
   `fetch_missing_hal_id`) si la phase écrit en base depuis la
   boucle async ; sinon batch sync hors de l'îlot.
6. Sur Windows : `WindowsSelectorEventLoopPolicy` (cf. mémoire
   psycopg async).

## Décisions

1. **Pas de refonte des extracteurs** : on remplace `requests` par
   `httpx.AsyncClient`, on parallélise la pagination quand elle
   est parallélisable, point. Pas de refactor architectural.
2. **Pagination cursor-based intra-année séquentielle, parallélisme
   inter-années** pour OpenAlex (parallélisme limité à ×2-×3).
3. **Pagination offset-based parallélisable** pour HAL et
   theses.fr (gain attendu supérieur).
4. **`infrastructure/sources/base.py` adapté avant** les
   extracteurs : c'est le point central qui contient `requests`
   et la gestion d'exception commune. Une fois async, les 5
   extracteurs migrent un par un.
5. **`enrich_*` indépendants** : pas de blocker, ROI élevé (boucle
   par DOI, embarrassingly parallel). À faire en premier comme
   warm-up.

## Phasage

Ordre par ROI décroissant et complexité croissante :

### Étape 1 — Scripts d'enrichissement (ROI élevé, simple)

- [ ] `enrich_oa_status.py` → async (Unpaywall, ~10 req/s).
  Pattern identique aux `fetch_missing_doi` (1 requête par DOI).
- [ ] `enrich_journal_apc.py` → async (DOAJ).

### Étape 2 — Refetch ciblé (ROI moyen, simple)

- [ ] `refetch_truncated.py` → async. Boucle individuelle par
  work tronqué, embarrassingly parallel. Même pattern OpenAlex
  que `fetch_missing_doi.py::openalex` (max_concurrent=3).

### Étape 3 — Extracteurs (ROI variable, plus volumineux)

- [ ] `infrastructure/sources/base.py` : migrer le boilerplate
  (gestion d'exceptions, cycle connexion, header User-Agent…) vers
  un `AsyncExtractorBase`. Garder le sync en parallèle ou
  basculer net selon ce qu'on trouve à l'implémentation.
- [ ] HAL (pagination offset, parallélisme page par page)
- [ ] theses.fr (pagination offset, parallélisme page par page)
- [ ] OpenAlex (pagination cursor intra-année, parallélisme
  inter-années limité)
- [ ] ScanR
- [ ] WoS (rate-limit contractuel strict, parallélisme limité)

Chaque migration d'extracteur = 1 commit ; benchmark avant/après
mentionné dans le message de commit si non-trivial.

## Questions ouvertes

- **`base.py` : sync ET async cohabitent, ou bascule nette ?**
  Cohabitation = on garde le sync pour ce qui n'est pas encore
  migré ; bascule nette = on bascule tout d'un coup. Probablement
  bascule nette (tous les extracteurs adoptent le pattern async
  au même moment), mais à confirmer au moment d'attaquer
  l'étape 3.
- **Parallélisme inter-années OpenAlex** : faisable par
  `asyncio.gather` sur N tâches « extraire année Y », chacune
  séquentielle intra-année. À benchmarker — gain potentiel
  ×2-×3 selon la doc OpenAlex, à confirmer.
- **Rate-limit WoS** : crédit contractuel 50 000 records/an,
  vérifier que la parallélisation ne risque pas de tirer plus de
  records que le sync (volume identique = ok, juste plus vite).
