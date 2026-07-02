# Refresh stale par identifiants natifs

## Contexte

La phase `refresh_stale` refetche les rows `staging` dont `last_seen_at` a dépassé `STALE_REFRESH_AFTER_DAYS`, pour rafraîchir leur `raw_data` ou constater leur disparition.

Elle réutilise la machinerie de cross-import `fetch_missing_doi` : chaque source est interrogée **par DOI**. Deux limites en découlent.

- Les rows **sans DOI** ne peuvent pas être refetchées. Elles sont marquées `disappeared_at` sur une simple heuristique de staleness (« re-moissonnée par le bulk, donc rester stale = disparu »), qui confond une absence réelle avec un run restreint à d'autres années.
- Interroger par DOI est un *lookup* (« trouver ce DOI dans la source »), pas un refresh de la row exacte déjà connue. La row possède pourtant son identifiant natif dans `staging.source_id` (`NOT NULL`, `UNIQUE (source, source_id)`).

Le refetch propre interroge chaque source par `source_id` : hal-id, id OpenAlex, UT WoS, id ScanR, NNT (ou id theses.fr), et le DOI lui-même pour crossref/datacite (source native du DOI).

## Décisions

- Refetch par identifiant natif pour toutes les sources, `theses` incluse (absente de `refresh_stale` aujourd'hui, faute d'API par DOI).
- Trois issues par row : record trouvé → refresh `raw_data` + bump `last_seen_at` ; absence confirmée (réponse valide, zéro record) → `disappeared_at` ; échec transitoire (réseau, 429, réponse malformée) → no-op, retry au run suivant.
- Suppression de l'heuristique « stale sans DOI → disparu » : `disappeared_at` ne se pose plus que sur une absence confirmée par la source.
- `wos` reste opt-in (`--include-wos`), comme pour `extract` et `cross_imports`.

## Phasage

### Phase 1 — Socle générique

- [x] Port `application/ports/pipeline/extract/refresh_stale.py` : Protocol `RefreshStaleAdapter` (`fetch_by_native_id`), sentinelle d'absence confirmée, `StaleRow`.
- [x] Orchestrateur `application/pipeline/extract/refresh_stale.py` (modelé sur `refetch_truncated.refetch`) : boucle async, pool de workers, circuit-breaker, commits périodiques.
- [x] Classe de base infra `infrastructure/sources/refresh_stale_base.py` : opérations DB génériques (find/save/mark), une seule fois pour toutes les sources.
- [x] Helpers SQL `infrastructure/sources/common.py` : `get_stale_rows(source)`, `set_disappeared_by_source_id(source, source_id)`.
- [x] Retrait des helpers obsolètes : `get_stale_dois`, `set_disappeared_by_doi`, `mark_undiscoverable_stale_disappeared` et leurs requêtes.

### Phase 2 — Adapters par source

- [x] hal (requête Solr `halId_s`), openalex (`GET /works/{id}`), wos (`UT=(…)`), scanr (ES `term` sur `id.keyword`), theses (recherche theses.fr filtrée par `id`), crossref (`GET /works/{doi}`), datacite (`GET /dois/{doi}`).

### Phase 3 — Câblage

- [x] `phase_refresh_stale` / `_run_refresh_stale` sur le mécanisme par id natif ; cible = toutes les sources (wos opt-in).

### Phase 4 — Tests et documentation

- [x] Tests d'unité orchestrateur (routage des trois issues) + sélection des cibles ; tests d'intégration `get_stale_rows` / `set_disappeared_by_source_id`.
- [x] Mise à jour docstrings.

## Questions ouvertes

- Item lié du TODO : « stocker l'année requêtée dans une colonne du staging pour coupler `refresh_stale` à l'année de départ du run ». À reprendre après cet item.
