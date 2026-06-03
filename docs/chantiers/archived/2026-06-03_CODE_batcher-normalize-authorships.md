# Chantier — Normalize : batcher l'insertion des authorships

Commencé le 2026-06-02 - Terminé le 2026-06-03

## Contexte

`normalize` est la phase la plus lente du pipeline (HAL en tête, mais pas uniquement). Le coût par work est **dominé par `process_authors`**, qui fait un **N+1 par auteur** : `upsert_source_authorship` (1 round-trip) + `address_linker.link` (~2 round-trips : get-or-create adresse + insert lien) par auteur. Un work à N auteurs ≈ `5 fixes + N×3` round-trips Python↔PG **séquentiels**.

### Diagnostic (run prod 2026-06-02)

- HAL : **~2,5 works/s** (300 works en ~122 s). Les `SLOW` logs montrent `authors:` ≈ tout le temps du work (ex. `authors:6.008s` sur 6.222s).
- Distribution du nombre d'auteurs par source :

  | source | n_pubs | avg | p95 | max |
  |---|--:|--:|--:|--:|
  | wos | 19069 | 129.4 | 1005 | 15866 |
  | crossref | 20093 | 79.2 | 141 | 13561 |
  | hal | 101025 | 32.0 | 25 | 5273 |
  | openalex | 66016 | 25.1 | 39 | 3411 |
  | scanr | 142256 | 6.7 | 24 | 51 |
  | theses | 2537 | 5.7 | 9 | 11 |

  **WoS a les plus grosses listes (4× HAL) et est pourtant rapide** — parce qu'il est **déjà batché** (O(1) round-trips/work). HAL (milieu de tableau) est lent **parce qu'il ne l'est pas**. La cause est le batching, pas la taille des listes.

- **Seul WoS est batché** (`upsert_addresses_batch`, `upsert_wos_source_authorships_batch`, `insert_source_authorship_addresses_batch`). HAL, OpenAlex, ScanR, theses, crossref font tous le N+1.

À ~2,5 works/s, les ~78 600 works HAL restants ≈ **9 h** rien que pour HAL.

## Décisions

1. **Abstraire le *writing*, garder le *parsing* source-spécifique.** Ce qui diffère entre sources est uniquement la lecture du payload (HAL : TEI + composites Solr ; OpenAlex : tableau authorships ; crossref : `author[]` ; etc.) — irréductible. Les 4 étapes d'écriture sont communes (les tables `source_authorships` / `addresses` / `source_authorship_addresses` sont partagées).
2. **DTO auteur partagé** : `{position, raw_name, is_corresponding, roles, source_structures, person_identifiers, addresses: [{text, country?, suggested_country?}]}`.
3. **Writer batch partagé** `write_source_authorships(conn, source, spid, records)` enchaînant : clear → bulk upsert `source_authorships` (RETURNING id par position) → bulk upsert `addresses` + fetch ids → bulk insert `source_authorship_addresses`.
4. **Queries batch remontées de WoS** vers un module partagé, paramétrées par `source` (les colonnes de `source_authorships` sont identiques pour toutes les sources).
5. **Valider sur HAL d'abord** (preuve, mesure avant/après), puis dérouler OpenAlex / ScanR / theses / crossref. WoS devient consommateur du writer commun (retire ses queries dédiées).

## Phasage

- [x] Module partagé `application/pipeline/normalize/_authorships_batch.py` : DTO `AuthorRecord`/`AddressRecord` + writer + port `AuthorshipsBatchQueries` + impl `PgAuthorshipsBatchQueries`.
- [x] HAL : `build_hal_author_records` (parsing pur) + `process_authors` qui appelle le writer ; `address_linker` retiré de HAL.
- [x] OpenAlex : `build_openalex_author_records` (parsing pur) + writer ; `address_linker` retiré, `upsert_openalex_source_authorship` + clear morts supprimés. `roles=['author']` posé explicitement (reproduit l'ancien défaut DB).
- [x] ScanR : `build_scanr_author_records` + writer ; `detected_countries` → `countries` (autorité). Code mort supprimé.
- [x] crossref : `build_crossref_author_records` + writer ; `sequence` → `source_data`, `roles=['author']`. Code mort supprimé.
- **theses : exclu.** `aggregate_thesis_persons` pose `author_position = NULL` pour les non-auteurs (directeurs/jury) ; or le writer est **clé = position** (la dédup `setdefault(position)` collapse tous les NULL en un seul, et `fetch_…_by_position` ne remappe pas NULL pour lier leurs adresses). theses garde donc son upsert per-auteur — c'est la plus petite source (2537 pubs, ~5,7 personnes/pub), gain négligeable.
- [x] WoS : `build_wos_author_records` + writer ; queries dédiées (`upsert_wos_source_authorships_batch`, `_resolve_addresses_batch`, etc.) + 3 TypedDicts supprimés. **Étude cross-work : WoS n'était PAS cross-work** — il traitait un record à la fois (base `run()` per-row), batchait seulement les auteurs d'un record, sans cache cross-record (les mentions « préchargements de caches » des docstrings étaient périmées). Bonus : son upsert dédié était un `executemany` (O(N) requêtes) ; le writer partagé (`jsonb_to_recordset`, O(1)) le rend donc **plus rapide**, pas seulement harmonisé.
- **Cache cross-work : à étudier séparément** (orthogonal au batch par-work). Le seul vrai cache cross-work existant était `address_linker._cache` (texte→id d'adresse, vidé au rollback), perdu pour les 5 sources migrées. Cibles si on le veut : cache d'adresses dans le writer (regérer l'invalidation rollback) et/ou cache journal/publisher (find_or_create tape la base à chaque work — couplé au bloat `enrich_journal` déjà corrigé).
- [x] Tests : caractérisation par source = unit `build_<source>_author_records` (5 sources, parsing pur) + intégration idempotence par source (`tests/integration/pipeline/idempotence/test_normalize_*`), qui lancent le **vrai writer** (`PgAuthorshipsBatchQueries`) via `process_work` et vérifient `source_authorships` (contenu + dédup, ex. scanr idref), les **liens adresses** (`source_authorship_addresses`, ex. crossref) et l'idempotence double-run. Writer couvert end-to-end pour les 5 sources.

## Mesures (corrigent le diagnostic initial)

Profilé sur la base de prod (RTT local = 0,4 ms), work HAL à 5244 auteurs :

- **Le diagnostic « N+1 round-trips » était incomplet.** Le vrai problème : `conn.execute(text(...), liste_de_dicts)` (executemany) part en **N requêtes séquentielles** côté psycopg, pas en un INSERT multi-lignes. Mon premier jet (batch façon WoS) gardait donc O(N) requêtes → gain marginal (ce que Laura a observé). WoS lui-même n'est pas O(1) : son gain venait de retirer les allers-retours du `address_linker` (get-or-create par adresse), pas de l'insert.
- **Correctif retenu : une seule requête par opération** via `jsonb_to_recordset` (lot transmis en JSONB, étendu côté serveur) / `unnest` (pivot). Insert des authorships : **1,78s → 0,40s** (~4,5×).
- **Pas d'`ON CONFLICT`** sur `source_authorships` ni le pivot : le clear (DELETE, qui cascade sur le pivot via FK `ON DELETE CASCADE`) + dédup par position garantissent l'absence de collision. Conservé sur `addresses` (table partagée non vidée).
- **Planchers irréductibles** sur les gros works : parsing TEI (~0,4s pour 5244 auteurs) + maintenance des index `pkey` + `pub_pos_key` (2 × ~280 Mo) à l'insert (~0,4s) et au clear (~0,2s, re-process uniquement). Les works typiques (moy. 32 auteurs) sont en millisecondes.
- **Index mort supprimé** (`idx_sa_nonhal_outscope` : 0 scan, 178 Mo) via migration `d5e8b3a1f6c4` — allège la maintenance des inserts non-HAL. Le clear/cascade reste, mesuré non réductible (retirer le CASCADE ne gagne que ~7 %, la cascade ≈ vrai travail de suppression des lignes enfants).
- **Clear de masse en amont écarté** : un DELETE unique des authorships de tous les spids à normaliser est plus *lent* (500 docs : `= ANY` 9,1s, jointure `unnest` 10,7s en Hash Join/seq scan, vs boucle index-scan par-document 3,1s) — le `pub_pos_key` rend déjà chaque clear par-document très efficace, et le bulk perdrait l'atomicité par-document (crash = authorships supprimées avant re-normalisation).

## Décisions complémentaires (questions tranchées)

- **`address_linker.link`** : vérifié appelé uniquement dans `normalize` (hal, openalex, scanr, theses, crossref), aucun appelant admin/externe → retirable une fois les 5 sources migrées (la classe `PgAddressLinker` reste pour `recompute_pub_count` / `clear_cache`).
- **DELETE+reINSERT** : on **garde** le `clear` actuel (simple, en place, rend le bulk INSERT trivial sans conflit).
- **Granularité** : **par work** pour commencer (comme WoS). On mesurera le gain avant de décider s'il faut accumuler cross-work.
- **Normalisation du nom** : unifiée sur Python `normalize_name_form` dans le writer (HAL le faisait en SQL).
