# Refresh stale par identifiants natifs

Commencé et terminé le 2026-07-02

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
- Couplage du refresh à la fenêtre d'années du run, **sans colonne dédiée** : l'année de publication vit déjà dans `source_publications.pub_year` (déjà présente pour toute row stale, normalisée à un run antérieur). `get_stale_rows` joint `staging → source_publications` et borne sur cette année, plutôt que de matérialiser et maintenir une année dans `staging` (duplication, parsing par source, ou backfill différé). `theses` suit sa sémantique d'extraction : tout l'historique par défaut (aucune borne), `--year` mis à part.

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

### Phase 4 — Couplage à la fenêtre d'années du run

- [x] `get_stale_rows(source, years)` : LEFT JOIN `source_publications.pub_year`, borne optionnelle sur les années du run (NULL conservé).
- [x] `find_stale` / orchestrateur `refresh` / `_run_refresh_stale` propagent `years` ; `phase_refresh_stale` calcule la fenêtre via le même `get_years()` que l'extraction (theses exemptée de la borne large).

### Phase 5 — Tests et documentation

- [x] Tests d'unité orchestrateur (routage des trois issues) + sélection des cibles + couplage année par source ; tests d'intégration `get_stale_rows` (avec/sans borne année) / `set_disappeared_by_source_id`.
- [x] Mise à jour docstrings.
