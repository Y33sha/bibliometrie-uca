# Chantier — Extraction HAL : requête unique multi-collections

Issu de l'investigation 2026-06-20 sur le non-respect de `raw_hash=null` au réimport HAL (« 0 mis à jour » alors que les hash avaient été nullés).

## Contexte

HAL est interrogé **par collection** : la configuration associe chaque laboratoire à sa (ou ses) collection(s) HAL (`collCode_s`). L'extraction boucle sur les ~42 collections. Les autres sources (OpenAlex, WoS, ScanR, theses.fr) sont interrogées par **identifiant de structure racine** : une seule requête couvre toutes les sous-structures et l'API renvoie une liste dédoublonnée. Seul HAL, par son système de collections, force l'interrogation par sous-ensemble — d'où un recouvrement entre collections (un document appartient à plusieurs collections, et le même document est rencontré dans plusieurs requêtes).

Pour éviter de récupérer N fois un document présent dans N collections, l'extraction HAL a un **aiguillage adaptatif** par collection ([extract_hal.py orchestration](../../application/pipeline/extract/extract_hal.py)) : preview des `halId_s` de la collection (payload léger), diff contre `existing_ids` (documents déjà en staging) → `mode=full` (toutes les pages) si beaucoup d'orphelins, `mode=incremental` (fetch individuel des orphelins + tag SQL des connus) sinon. La décision est dans [`choose_extraction_mode`](../../application/pipeline/extract/hal_helpers.py).

**Le bug.** En mode incrémental, les documents « connus » (déjà en staging) sont seulement **tagués** avec la collection (`tag_existing_with_collection`), **jamais re-fetchés**. Or `existing_ids` est chargé depuis **tout le staging** ([base.py](../../application/pipeline/extract/base.py), `run_as_phase`) : un document vu une fois est « connu » à jamais → ses données ne sont plus rafraîchies et son `raw_hash` n'est jamais recalculé. Conséquence : **nuller `raw_hash` n'a aucun effet** sur les documents connus (ils ne sont pas re-fetchés), ce qui casse le contrat « `raw_hash=null` = réimport » pour HAL. Les autres sources n'ont pas ce bug : elles re-fetchent tout par requête année et n'utilisent `existing_ids` que comme indice de classification `is_new`.

Le rôle réel de `existing_ids` dans l'aiguillage HAL est en fait le **dédoublonnage intra-run** (un document dans N collections-labos ne doit être récupéré qu'une fois par run). Le pré-charger avec l'intégralité du staging détourne ce rôle en « déjà-vu-une-fois donc figé pour toujours ».

Capacités de l'API de recherche HAL (Solr) **validées par appel réel** le 2026-06-20 (`q=*:*`) :

- `fq=collCode_s:(C1 OR C2)` renvoie l'**union dédoublonnée** (Solr filtre, ne joint pas) : `PRES_CLERMONT`=93717, `LIMOS`=5632, OR=93717 (et non 99349) — `LIMOS` est inclus dans l'umbrella établissement.
- `collCode_s` est **multivalué** : chaque record porte la liste de ses collections.
- **`cursorMark` supporté** (`nextCursorMark` présent dans la réponse) — pagination robuste pour une union de plusieurs dizaines de milliers de records.
- `start=20000` répond HTTP 200 (fenêtre de résultats large), mais `cursorMark` reste le choix propre au-delà de 10 000.

Audit du périmètre (API, 2026-06-20, sur les **42 collections configurées**) : l'union fait 96 728 records, dont **3 011 (3 %) hors `PRES_CLERMONT`** (notamment `CHU-CLERMONTFERRAND`, établissement hospitalier distinct de l'université). `PRES_CLERMONT` n'est donc **pas** un sur-ensemble : interroger la seule collection établissement perdrait ~3 % du périmètre. L'OR sur les 42 collections est nécessaire.

Deux systèmes d'upsert staging coexistent : HAL, OpenAlex et WoS utilisent `INSERT … ON CONFLICT DO UPDATE` piloté par `raw_hash` (la base tranche new-vs-existing, `existing_ids` inutile au routage) ; theses.fr et ScanR utilisent un routage `is_new` (INSERT-ou-UPDATE explicite, sans `ON CONFLICT`) qui, lui, **dépend** de `existing_ids`. C'est pourquoi `existing_ids` ne peut pas être retiré du `base.py` (il sert à theses/ScanR), même si HAL ne s'en servira plus.

## Décisions

*(Proposées, à valider — seul le Contexte ci-dessus est factuel.)*

1. **Requête unique multi-collections.** Remplacer la boucle par collection par une seule requête `q=<années/since>` + `fq=collCode_s:(C1 OR … OR C42)`. Solr dédoublonne l'union côté serveur → plus de double-fetch, plus de dédoublonnage applicatif.
2. **Pagination `cursorMark`** (au lieu de `start`/`rows`) : `cursorMark=*` → `nextCursorMark`, boucle jusqu'à stabilisation du marqueur, avec `sort=docid asc` (champ unique, déjà utilisé).
3. **`hal_collections` dérivées du record** : `collCode_s ∩ {collections configurées}`, au lieu du tag par collection-de-requête. Plus complet — un document récupéré via l'umbrella porte aussi ses collections-laboratoires.
4. **Classification par `raw_hash`** : `new`/`updated`/`unchanged` viennent du `(inserted, changed)` de l'upsert staging existant. `raw_hash=null` est honoré (re-fetch → hash recalculé → re-import + `processed=FALSE`).
5. **Suppression de l'aiguillage** : `choose_extraction_mode`, `count_full_fetch_pages`, `_extract_full`, `_extract_incremental`, `fetch_collection_ids`, `tag_existing_with_collection`, et l'usage de `existing_ids` côté HAL. Le pré-chargement de `existing_ids` dans `base.py` reste pour les autres sources (il leur sert d'indice `is_new`, correct).
6. **`--since` conservé** : il vit dans `q` (filtre date), orthogonal au `fq` collections. Runs réguliers avec `--since` (peu de records) ; rattrapage `raw_hash=null` sans `--since` (union complète re-fetchée).

## Phasage

### 1. Adapter HAL (infrastructure)
- [x] Construire le `fq` multi-collections + méthode de fetch paginée `cursorMark`
- [x] Dériver `hal_collections` depuis `collCode_s ∩ {configurées}`
- [x] Conserver l'upsert staging (raw_hash) inchangé

### 2. Orchestration (application)
- [x] Remplacer `extract_all` (boucle collection + aiguillage) par une boucle `cursorMark` unique
- [x] Retirer `existing_ids` du flux HAL

### 3. Nettoyage
- [x] Supprimer le code mort (`choose_extraction_mode`, `count_full_fetch_pages`, `_extract_full`/`_extract_incremental`, `fetch_collection_ids`, `tag_existing_with_collection`)
- [x] Nettoyer les ports correspondants

### 4. Tests
- [x] Réécrire `test_extract_hal_adaptive` : cursorMark, dédoublonnage de l'union, `hal_collections` issues de `collCode_s`

### 5. Rattrapage du stock
- [ ] Réimport HAL `raw_hash=null` **sans** `--since` → re-fetch complet honorant les hash nullés (débloque la phase 6 du chantier embargo)

## Hors scope / suites

- **Unification des upsert staging.** theses.fr et ScanR pourraient passer à `INSERT … ON CONFLICT DO UPDATE` (comme HAL/OpenAlex/WoS), ce qui retirerait leur dépendance à `existing_ids` et permettrait de le supprimer entièrement du `base.py`. Cleanup distinct de ce chantier.

## Liens

- [METIER_embargo-oa-status](METIER_embargo-oa-status.md) — phase 6 (rattrapage HAL `raw_hash=null`) débloquée par ce chantier.
