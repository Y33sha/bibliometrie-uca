# Performance du pipeline (phase par phase)

Commencé le 2026-06-13 - Terminé le 2026-06-14

## Contexte

Temps observés sur un rapport (daily + full). On attaque les phases par impact décroissant.

**Daily**
- extract : 129 s
- cross_imports : 3598 s — gros lot non traité des jours précédents (one-shot, pas inquiétant en soi ; parallélisable entre cross-imports comme les extracteurs)
- refresh_stale : 1,3 s
- normalize : 383 s (normal vu le gros cross-import)

**Full**
- publishers_journals : 779 s (interrompu en plein milieu de l'API DOAJ — inacceptable)
- affiliations : 149 s
- zenodo_doi : 32 s
- publications : 181 s
- persons : 53 s
- authorships : 46 s
- countries : 50 s
- subjects : 1991 s — inacceptable, à rendre incrémental
- oa_status : 6642 s (interrompu) — >100k interrogations DOI par DOI via Unpaywall, catastrophiquement lent

## Ordre d'attaque (par impact)

1. **oa_status** (6642 s) — le monstre.
2. **subjects** (1991 s) — rendre incrémental.
3. **publishers_journals** (779 s) — l'API DOAJ.
4. **cross_imports** (3598 s, daily) — backlog ponctuel, parallélisation (moindre priorité).

## Phasage

### 1. oa_status — staleness + règles métier (fait, sauf suivi refresh)

État initial : `fetch_publications_with_doi` renvoyait **tous** les ~107k DOI à chaque run via Unpaywall (async `Semaphore(5)`, débit plafonné par la politesse Unpaywall ~10 req/s → cranker la concurrence est inutile/risqué). **Audit** : 97 % des publis ont OpenAlex comme source (dont l'`oa_status` dérive déjà d'Unpaywall), et les corrections sont **déjà appliquées** par les full précédents (0,36 % de changements/run) — mais Unpaywall apporte bien ~2-4 % de corrections réelles vs OpenAlex brut (à ne pas perdre). → pas supprimer, **incrémentaliser** (réduire le volume).

- [x] Colonne `publications.unpaywall_checked_at` (migration `e3f7b2d9c5a8`) + index partiel pour le fetch
- [x] `STABLE_OA_STATUSES` (gold/diamond/hybrid) dans `domain/publications/metadata` (+ forme SQL) — règle métier
- [x] Constantes opérationnelles `MAX_PER_RUN=10000` + `STALENESS_DAYS=30` dans le module de phase (pas domain)
- [x] `fetch_publications_with_doi` : jamais-vérifiés (1× même gold/diamond/hybrid) OU statut changeable périmé ; tri `NULLS FIRST` + cap
- [x] `unpaywall_checked_at = now()` posé à **chaque** vérif (changée, inchangée, non trouvée, diamond préservé)
- [x] `run_oa_status = True` en **daily + weekly** (le cap lisse, le backlog s'écoule run après run)

Effet attendu : ~6642 s (one-shot, backlog écoulé sur ~11 runs à 10k) → quelques dizaines de secondes en régime permanent.

- [x] **Préservation au refresh** : `aggregation.recompute` ne ré-agrège plus `oa_status` quand `unpaywall_checked_at` est posé (Unpaywall fait autorité). Sans ça, un réimport (publi stale → `refresh_from_sources`) écraserait la correction Unpaywall et, la date étant posée, elle ne serait jamais re-vérifiée → perte permanente sur un statut stable-open. L'entité `Publication` porte désormais `unpaywall_checked_at` (chargé par `find_by_id`).

### 2. subjects — périmètre, purge amont, incrémental (fait)

**Audit** : `recompute_usage_counts` et la matview `subject_cooccurrences` comptaient sur **toutes** les publications, dont 58 % hors-périmètre (2,45M liens `publication_subjects`, seulement 42 % in-perimeter). D'où l'écart « 10 occurrences annoncées vs 2 publications affichées ». Comptages déjà par publication (`COUNT(DISTINCT publication_id)`), pas par `source_publication` — le souci était bien le périmètre, pas la granularité.

**Cause racine** : le modèle création⇒fusion promeut une publication par `source_publication` orphelin sans gate ; 116k restent à **zéro authorship** (hors-périmètre, sans auteur en base, inatteignables dans l'UI). Mesure des catégories portant des sujets : in-perimeter 64 074 pubs / hors-périmètre-avec-auteur 11 pubs / orphelines 116 102 pubs.

**Fix retenu** : purge des publications zéro authorship en **fin de phase authorships** (`purge_orphan_publications`), pas de filtre dans subjects. `publication_subjects` (FK CASCADE) reste alors scopé périmètre → `usage_count` + matview en héritent. Le résidu hors-périmètre conservé (11 pubs / 146 liens) garde ses sujets sur les fiches → « les vues par personne montrent tout » préservé. Un gate au `create` a été écarté : non équivalent (25 571 sources sans auteur matché contribuent des métadonnées à 17 863 pubs in-perimeter via fusion par identifiant — un gate les perdrait ; la purge a posteriori tourne après toutes les passes de fusion, donc les garde).

- [x] Purge `purge_orphan_publications` en fin d'authorships : DELETE batché (commit par chunk de 5000 → WAL étalé, progression durable) + `VACUUM ANALYZE` simple (réutilisation de l'espace, pas de FULL). La cascade des 1,4M `publication_subjects` est un coût **unique** (liens legacy) : la purge tournant avant subjects, les orphelines re-promues n'en reçoivent plus jamais — `234abaf6`
- [x] Effet mesuré : publications 183k → 65k ; `publication_subjects` 2,45M → 1,04M (−58 %) ; ingest subjects 1991s → 577s

**Incrémental (fait)** : après la purge, l'ingest tournait encore en full (clear-all + ré-ingestion des ~178k source_publications = 577s mesurées). Rendu **incrémental et publication-centré**, sans nouvelle colonne :

- Signal de changement = `publications.updated_at` (vérifié propre : 358/65020 bumpées par run ; les UPDATE in_perimeter/countries/oa_status sont conditionnels `IS DISTINCT FROM`). Référence « dernière ingestion » = `max(publication_subjects.created_at)` par publication (`created_at` a `default now()`). On ne ré-ingère que les pubs où `publications.updated_at > max(publication_subjects.created_at)` (ou jamais ingérées, ~1 %). Le `created_at` est celui des **liens** : ré-ingérer une pub repousse son `max(created_at)` au-delà de `updated_at`, donc le critère se désarme jusqu'au prochain changement (une ré-ingestion par changement, pas à chaque run).
- Lecture des `source_publications` (pas `publications_detail`) : la provenance par-source des keywords n'existe qu'à la source (`publications_detail.keywords` est fusionné sans source) ; coût nul puisqu'on ne lit que les pubs changées. Clear par publication (toutes sources) → gère le cas ~7 % de 2+ source_pubs même source.
- `purge_orphan_subjects` en fin de phase : supprime les sujets sans aucun lien (les `subjects` ne sont plus « jamais purgés »). Nettoie en one-time les 172k orphelins laissés par la purge des pubs + le filet ongoing, et allège cooccurrences.

Effet attendu : daily 577s → quelques secondes (seul le delta).

**Qualité des sujets (fiche `DATA_*` séparée)** : 303k des 311k sujets sont des keywords libres (sans ontologie), dont 100k singletons — bruit qui gonfle aussi cooccurrences. Question de fond : faut-il ingérer les keywords libres comme sujets, fusionner les variantes (trigram/édition/phonétique) ? Hors périmètre perf.

**Tapis roulant (chantier séparé)** : `create_publications` re-promeut les 116k orphelins à chaque run (re-fusion → re-purge). Le `VACUUM` simple évite le bloat, mais la phase publications (~181s) re-crée ces 116k pour rien. Tuer le tapis roulant (gate au create attachant les sources sœurs, ou flag `do_not_promote` avec invalidation) dépasse subjects et touche le cœur création⇒fusion → chantier dédié, à froid.

### 3. publishers_journals

L'enrichissement interrogeait des API entité par entité (DOAJ par revue : 779s interrompu ; OpenAlex Sources : milliers de revues/run). Trois sous-leviers, par source.

**DOAJ — dump CSV au lieu de l'API (fait)** : l'API par ISSN (779s) est remplacée par l'import du dump CSV public (`https://doaj.org/csv`), téléchargé dans `data/doaj/` au plus tous les 30 jours (staleness sur `max(doaj_imported_at)`). Le payload était déjà au format CSV — le dump est la source d'origine, l'API un détour. DOAJ devient seul maître de `is_in_doaj` (reset global + re-pose), import bulk O(1) par ISSN.

- [x] `fetch_doaj_dump` + `read_doaj_dump_rows` + `run_import_doaj_dump` (mutualisé CLI/pipeline) ; retrait franc du chemin API — `78bdca4e`
- [x] Retrait du `is_in_doaj` posé par OpenAlex Sources (redondant, DOAJ fait autorité) — `60e9980d`

**OpenAlex Sources — incrémental sur le type (fait)** : la requête était gatée sur `apc_amount IS NULL`, jamais rempli (le « 0/550 » ne porte que sur le résidu jamais trouvé par OpenAlex ; la gate excluait déjà les revues à APC) → re-interrogeait ~tout le catalogue à chaque full run pour rien. Le `journal_type` étant **stable**, on ajoute la valeur d'enum `unknown` (nouveau défaut DB = « inconnu » UI, **pas de colonne dédiée**) et on gate sur `journal_type = 'unknown' AND openalex_id IS NOT NULL` : un journal naît `unknown`, est typé une fois, sort de la file. APC **gardé** (extrait opportunistement dans la même réponse ; déjà non rafraîchi pour les revues qui en ont → aucune régression). `reset_journal_apc` + flag `--reset` supprimés (incohérents avec la gate type). Pas de backfill des `journal` existants → chantier qualité rétrospectif distinct.

- [x] Enum `unknown` + défaut + gate `fetch_journals_of_unknown_type` ; sync enum domaine/tables.py/DB durcie — `81401b42`

**resolve_doi_prefixes — ne plus retenter les échecs (fait)** : les préfixes DOI tentés sans succès (RA non résolue, samples KO) n'étaient pas insérés → absents de `doi_prefixes`, retentés à chaque run (26, croissant). Fallback direct sur les endpoints prefix Crossref puis DataCite ; si rien nulle part, insertion avec RA sentinelle `'unknown'` (+ `fetched_at` défaut) → sortis de la file.

- [x] Fallback Crossref/DataCite + sentinelle `'unknown'` à l'échec — `9618879d`

**Crossref Members + ROR — appels séquentiels lents (fait)** : `enrich_publishers_from_crossref_members` (~1080s) et `enrich_publishers_from_ror` (~770s) enchaînaient des appels API dont la latence (~4s et ~3,4s/appel) dominait. Fetches parallélisés (`ThreadPoolExecutor`, `max_workers=8`) ; traitement + écriture séquentiels (connexion sync non thread-safe).

- [x] Parallélisation des fetches (`rate_delay` → `max_workers`) — `4bae5b70`

- [ ] **Marqueurs « tenté » sur publishers (reporté)** : crossref_members (gate `country IS NULL`) et ror (gate `publisher_type='unknown'`) réinterrogent l'irrésoluble à chaque run (63 country, 127 type restent vides → retentés). Stopper ça demande un marqueur « tenté » par source (pas de colonne actuelle). Reporté — suppression complète de ces appels API à envisager.

### 4. cross_imports — parallélisation

Les 5 targets DOI (hal, openalex, wos, scanr, crossref) s'enchaînaient séquentiellement (~3600s sur un gros backlog). Parallélisés via `ThreadPoolExecutor` (comme les extracteurs) : chacun ouvre sa propre connexion, frappe une API distincte, écrit dans son staging — aucun état partagé. La propagation cross-source d'un DOI fraîchement importé peut glisser au run suivant (rattrapage idempotent et auto-borné).

- [x] Parallélisation des targets DOI par `ThreadPoolExecutor` — `ab3f1240`

### 5. Circuit-breaker 429/5xx — skip une source à bout de budget (fait)

Le budget API peut être dépassé en plein run (OpenAlex : budget quotidien, souvent crevé pendant le cross-import après un full extract ; WoS : budget annuel quasi épuisé ; Zenodo down → backoff + retry sur **chaque** DOI). Rien n'enrayait ça — il fallait couper le pipeline à la main.

**Design** : `SourceCircuitBreaker` (`infrastructure.sources.circuit_breaker`), compteur d'échecs **consécutifs** par source partagé via une `ContextVar`, `+1` sur requête échouée (429 / 5xx / réseau après retries — pas les 4xx), **remis à 0 au premier succès**. Les deux helpers HTTP (`http_retry` sync + `http_retry_async`) lui comptent les échecs, court-circuitent quand il a tripé, et les boucles consultent l'état pour sauter le reste de la source (retry au prochain run, phases idempotentes). Seuils : **10** en cross-import (async, requêtes concurrentes → ne pas tripper sur un batch ponctuel) ; **5** en extract (séquentiel). Découpage DDD : protocole `CircuitBreaker` dans `application.ports`, impl + ContextVar en `infrastructure`, câblage dans `run_pipeline` (root).

- [x] Breaker + intégration `http_retry_async`, cross-import (`run_async`, seuil 10) — `c7066e94`
- [x] Intégration `http_retry` sync + extracteurs (seuil 5, `_breaker_tripped()` dans la base) ; `max_retries` 5 → 3 (2,4,8s ; 16/32s inutiles) — `198ea7a7`

## Questions ouvertes

- oa_status : seuil de staleness (N jours) ; le mode `full` force-t-il tout ?
