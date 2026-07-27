# Recentrer `infrastructure/sources` sur le dialogue avec les API

## Contexte

`infrastructure/sources` doit contenir le code qui dialogue avec les API HTTP tierces (extraction, cross-import, refresh, enrichissements) et lui seul. Le dossier mélange aujourd'hui ce rôle avec de la persistance base, du code mort, des helpers transverses dupliqués et une structure inégale.

- **Persistance DB logée dans `common.py`.** `common.py` est surtout de la persistance : UPSERT staging (`upsert_staging`, `upsert_not_found_stub`), pool de DOI cross-import (`get_cross_import_dois`), sélection des rows périmées (`get_stale_rows`, `set_disappeared_by_source_id`), mémorisation des DOI introuvables (`record_doi_not_found`), lecture des identifiants déjà en staging (`get_existing_ids`). Ces requêtes SQL relèvent de `infrastructure/queries/pipeline`, pas du dialogue API.
- **Double support SA / psycopg.** `get_cross_import_dois` et `get_existing_ids` branchent sur `isinstance(conn, Connection)` : chemin SQLAlchemy ou chemin psycopg brut (`conn.cursor()`, `row_factory=dict_row`). Ce sont les seules traces psycopg du dossier. Le chemin de production connu de `get_cross_import_dois` passe une `Connection` SQLAlchemy (`run_async`), mais un test de régression `dict_row` couvre explicitement le chemin psycopg, et `get_existing_ids` n'a aucun appelant de production.
- **Helpers HTTP dupliqués et divergents.** `http_retry.py` (sync, `requests`) et `http_retry_async.py` (async, `httpx`) réimplémentent le même retry/backoff/circuit-breaker, et leur comportement a dérivé : le sync retente les 5xx (jusqu'à `max_retries`), l'async lève immédiatement sur toute `HTTPStatusError`, 5xx compris.
- **Structure inégale.** Chaque source d'extraction est un sous-package (`hal/`, `openalex/`, …), mais `unpaywall.py` est un fichier plat à la racine et `doaj/` un package réduit à son `__init__`. `doi_prefixes/` porte un nom de phase pipeline, pas de source, et regroupe trois clients de sources distinctes (Crossref, DataCite, doi.org).
- **Paramètres d'API éclatés.** Les URLs de base (`_API_BASE_URLS`) vivent dans `config.py` (lecture de la table `config`), alors que ce sont des invariants codés en dur, de même nature que les délais de `api_limits.py`. `config.py` avale par ailleurs des `except Exception` larges qui masquent les vraies erreurs.
- **Port implémenté en duck typing.** `circuit_breaker.SourceCircuitBreaker` satisfait le port `CircuitBreaker` structurellement, sans l'hériter, à rebours de la convention d'héritage explicite des adapters.

## Décisions

- **Périmètre.** `infrastructure/sources` ne garde que le dialogue avec les API HTTP. La persistance base (staging, cross-import, stale, `doi_lookups`) descend dans `infrastructure/queries/pipeline`. Après extraction de la DB, `common.py` n'a plus de raison d'être et disparaît.
- **`http_retry`.** Sync et async sont regroupés dans un même module, logique de décision factorisée. Comportement unifié : 429 et 5xx sont retentés jusqu'à `max_retries` puis le circuit breaker trippe ; les autres 4xx (404…) ne sont pas retentés (échec immédiat, déterministe).
- **Branches SA / psycopg.** Le pipeline tourne en SQLAlchemy : `application/` ne porte aucune trace psycopg, et `upsert_staging`, appelé par tous les adapters d'extraction et de cross-import, est SA-only. Les branches psycopg de `get_cross_import_dois` et `get_existing_ids` étaient des fossiles maintenus en vie par des fixtures de test : retirées. `get_existing_ids` n'ayant aucun appelant de production (fonction morte), la fonction et ses tests disparaissent. Les tests fonctionnels de `get_cross_import_dois` passent en SQLAlchemy pour garder leur couverture.
- **Un package par source.** `unpaywall/` ; le code de `doaj` sort de son `__init__` vers un fichier dédié ; `doi_prefixes` est dissous et réparti par source réelle : client préfixe Crossref → `crossref/`, client préfixe DataCite → `datacite/`, résolution de Registration Agency `doi.org/ra` → `doi_org/` (doi.org est de facto une source).
- **Paramètres d'API regroupés.** Les URLs sortent de `config.py` (ce sont des invariants, pas de la config) et rejoignent les limites dans un module de paramètres d'API. `config.py` se limite aux paramètres réellement lus en base (années, périmètres, clés API, credentials).
- **Exceptions.** Les `except Exception` larges de `config.py` sont resserrés. Le choix entre exception ciblée générique et exception métier se fait au cas par cas, avec une préférence pour l'exception métier quand elle porte un sens.
- **`circuit_breaker`.** `SourceCircuitBreaker` hérite explicitement du port `CircuitBreaker`.
- **`refresh_stale_base`.** L'orchestration `refresh_stale` vit déjà dans `application/pipeline/extract/refresh_stale.py`. `BaseRefreshStaleAdapter` reste une base fine côté `infrastructure/sources` (contrat de fetch HTTP + délégation), ses méthodes de persistance pointant vers les requêtes déplacées.

## Phasage

### A — Quick-wins indépendants

- [x] Branches psycopg fossiles de `get_cross_import_dois` retirées, fonction morte `get_existing_ids` supprimée avec ses tests ; tests fonctionnels de `get_cross_import_dois` convertis en SQLAlchemy.
- [x] `SourceCircuitBreaker` : héritage explicite du port `CircuitBreaker`.
- [x] `config.py` : docstring corrigée (les URLs d'API ne sont pas de la config).

### B — `http_retry` unifié

- [x] Regrouper sync et async dans un module unique ; factoriser la logique de décision (barème de backoff, classification des codes HTTP, interaction avec le circuit breaker).
- [x] Converger le comportement 5xx : retry de 429 et 5xx jusqu'à `max_retries` puis trip du breaker, échec immédiat sur les autres 4xx.
- [x] Tests couvrant, pour les deux variantes, le retry des 5xx et le non-retry des 4xx.

### C — Paramètres d'API regroupés

- [x] Sortir `_API_BASE_URLS` et `get_api_base_urls` de `config.py`.
- [x] Regrouper URLs et limites dans un module de paramètres d'API (`api_params`). Les URLs, invariants, passent en constante `API_BASE_URLS` ; le getter et sa copie défensive disparaissent.

### D — Un package par source

- [x] `unpaywall.py` → package `unpaywall/` (code dans `client.py`, `__init__` vide).
- [x] Code de `doaj/__init__.py` déplacé vers `doaj/client.py` (`__init__` vide), consommateurs repointés sans façade de ré-export.
- [x] Dissoudre `doi_prefixes` : client Crossref → `crossref/prefixes`, DataCite → `datacite/prefixes`, résolution RA doi.org → `doi_org/registration_agency`. Appelants adaptés (`resolve_ra`, `publishers_journals`). Le User-Agent polite pool, dupliqué dans cinq clients, est unifié dans `polite_pool.build_user_agent` ; `doi.org` rejoint `API_BASE_URLS`.

### E — Dissolution de `common.py`

La persistance d'extraction descend dans `infrastructure/pipeline/` (chantier `CODE_couches-acces-donnees`, phase D), pas dans `queries/pipeline`.

- [x] Déplacer les fonctions de persistance (`upsert_staging`, `upsert_not_found_stub`, `record_doi_not_found`, `get_stale_rows`, `set_disappeared_by_source_id`, `get_cross_import_dois`), leur SQL et leurs constantes (`DOI_LOOKUP_RETRY_DAYS`, `STALE_REFRESH_AFTER_DAYS`, `_TARGET_RA`) vers le package `infrastructure/pipeline/extract/` (`staging.py`, `cross_import.py`, `stale.py`). `get_existing_ids`, morte, a disparu en phase A.
- [x] Replacer le calcul du hash de détection (`canonical_json_bytes`, `compute_hash`, `change_detection_hash`, `_HASH_NORMALIZERS`) dans l'utilitaire neutre `infrastructure/pipeline/change_detection.py`.
- [x] `BaseRefreshStaleAdapter` : ses méthodes de persistance appellent les requêtes déplacées.
- [x] Retirer `common.py`.
- [ ] Resserrer les `except Exception` de `config.py` sur des exceptions ciblées.

## Questions ouvertes

- **Exceptions.** Au cas par cas, fichier par fichier : une exception métier (par exemple une erreur « paramètre de config absent/invalide ») quand elle porte un sens exploitable par l'appelant, une exception ciblée générique (erreur base, HTTP) sinon.
