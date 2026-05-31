# Moissonnage

Récupère les données brutes depuis les API et les stocke en JSONB dans le *staging*.

```mermaid
flowchart LR
  A[API HAL]-->|extract_hal|B[staging]
  C[API OpenAlex]-->|extract_openalex|B
  E[API WOS]-->|extract_wos|B
  G[API ScanR]-->|extract_scanr|B
  H[API theses.fr]-->|extract_theses|B
  classDef new  fill:#bbf
  class B new;
```

## Moissonnage initial {#extract}

**Critères de requête**:
- **années** de publication ([configurables](../guide-utilisateur/03-workflow-admin.md#years) dans `admin/config` : *weekly* couvre une fenêtre récente glissante (offset `pipeline_years_weekly`, par défaut n et n-1), *full* re-moissonne tout l'historique depuis une année d'ancre fixe (`pipeline_start_year_full`, 2017 = fusion UCA) → rétention cumulative, pas de fenêtre glissante);
- **affiliation** des publications ([périmètre configurable](../guide-utilisateur/03-workflow-admin.md#perimeters) dans `admin/config`). Il s'agit des affiliations *telles qu'elles sont renseignées dans chaque source*. Elles peuvent varier d'une source à l'autre et être incomplètes ou erronées. Ce point est géré dans les étapes ultérieures.

**Gestion des changements**:
- Chaque *record* est hashé (MD5) pour détecter les changements lors des réexécutions. Une publication dont les métadonnées ont changé sera ré-importée et re-traitée.
- Même sans changement, la colonne `last_seen_at` documente la dernière date où une publication a été détectée par le script d'import.
> En cas de disparition d'une publication dans les sources (par ex. dédoublonnage dans HAL), cette colonne permettra de détecter les suppressions et de nettoyer la base. Rien n'est en place pour l'instant. Chantier en cours: `DATA_cycle-vie-staging.md`

**Cas particulier**:

L'[API OpenAlex](../sources/03-openalex.md) limite les authorships à 100 par publication dans les requêtes paginées. Un *refetch* individuel des publications avec 100 authorships est nécessaire.

**`refetch_truncated.py`** — re-télécharge un par un les works OpenAlex tronqués à 100 auteurs. Pour éviter d'écraser la liste complète lors d'un bulk ultérieur, le refetch met à jour `raw_data` mais conserve `raw_hash` (hash du payload bulk initial) ; tant que le bulk renvoie le même payload, l'UPSERT bulk ne touche pas `raw_data`.


## Imports croisés {#cross-imports}

Phase `cross_imports`: deux étapes enchaînées, chacune adressant un cas distinct de "doc visible dans une source mais absent d'une autre".

**Étape 1 — `fetch_missing_hal_id` : HAL ids manquants.**
Télécharge depuis HAL les documents référencés (par hal-id ou NNT) dans d'autres sources mais absents de notre staging HAL. Code dans `infrastructure/sources/hal/fetch_missing_hal_id.py`. Auto-borné, tourne dans tous les modes : les hal-ids/NNT introuvables sont marqués `not_found_at` dans staging et ne sont jamais re-interrogés (HAL = source native pour les hal-ids, un 404 est définitif).

**Étape 2 — `fetch_missing_doi` : DOI manquants par source.**
Pour chaque source cible (OpenAlex, HAL, WoS, ScanR, Crossref), recherche par DOI les records trouvés dans les autres sources mais absents de celle-ci. La plupart sont effectivement absents ; certains sont repêchés (cause : affiliations différentes selon source). Dispatcher dans `interfaces/cli/pipeline/fetch_missing_doi.py`, adapter par source dans `infrastructure/sources/<source>/fetch_missing_doi.py`. Sources cibles déterminées par la policy du mode (`application/pipeline/modes.py`) ; le pool de DOI est auto-borné par le backoff `doi_lookups`.
<!--TODO: nommage incohérent: fetch_missing_hal_id cherche nnt-->

**Les deux étapes sont auto-bornées et convergentes.** Le pool de hal-ids/NNT à re-tenter est fini par construction (un hal-id 404 sort définitivement via `not_found_at`, HAL étant source native). Le pool de DOI l'est aussi grâce au backoff : un DOI absent d'une source *non native* (HAL/OpenAlex/WoS/ScanR) est enregistré dans `doi_lookups` avec `next_retry = now() + 30 jours` ; `get_cross_import_dois` ne le ressort qu'une fois ce délai écoulé. Le 1er pass tente tout, les passes suivantes ne reprennent que les nouveaux DOI et ceux dont le backoff a expiré.
