# Chantier — Résolution de la RA en amont de cross_imports

Commencé et terminé le 2026-06-25.

## Contexte

Le cross-import par DOI route les fetches par Registration Agency : pour les cibles Crossref et DataCite, `get_cross_import_dois` ne tente que les DOI dont la `doi_prefixes.ra` correspond — **ou est NULL** (préfixe pas encore résolu, best-effort).

Or `resolve_doi_prefixes` tourne **après** cross_imports (phase `publishers_journals`). Donc au premier run (base vide) ou sur tout nouveau préfixe, toutes les RA sont NULL : chaque DOI est tenté contre Crossref **et** DataCite, qui sont des ensembles disjoints. Sur un full sur base vide, ça revient à lancer ~50 000 appels DataCite pour des DOI Crossref (tous des 404) — catastrophiquement inefficace, et inutilement violent pour l'API DataCite.

Deux causes structurelles :

1. **Ordre** : la RA n'est connue qu'au run suivant. Il faut la résoudre **avant** cross_imports.
2. **Couverture** : le pool de DOI dont `resolve` résout les préfixes (`staging.doi` + `source_publications.external_ids.related_dois`) a divergé de celui que cross_import interroge (idem + `publication_relations.target_doi` + DOI DataCite arXiv-dérivés). Les préfixes des DOI manquants restent RA NULL → best-effort → gaspillage maintenu.

## Décisions

1. **Vue SQL partagée `candidate_dois(doi, source)`** comme pool unique de DOI candidats, consommée par cross_import **et** par la résolution de RA. La liste des emplacements de DOI est définie une seule fois ; impossible de re-diverger. Choix d'une vue (DDL, sans paramètre) plutôt qu'un fragment SQL Python, parce que `get_cross_import_dois` s'exécute aussi bien via une `Connection` SQLAlchemy (`:param`) que via un curseur psycopg (`%(param)s`) : une vue référencée par les deux côtés évite ce double paramstyle.
2. **Scission de `resolve_doi_prefixes` selon ses deux concerns :**
   - `resolve_ra` : résolution de la RA seule (`doi.org/ra`), nouvelle phase **entre `extract` et `cross_imports`**. C'est tout ce dont cross_import a besoin.
   - volet publisher (API `/prefixes` Crossref/DataCite → nom → match/création du publisher) : **reste dans `publishers_journals`**, après normalize (les publishers issus des sources existent alors). Le nom de phase reste justifié.
3. **Cycle de vie d'une row `doi_prefixes`** : créée par `resolve_ra` avec `ra` seule (volet publisher NULL) → complétée par `publishers_journals` (nom + `publisher_id`).
4. **Comportement de routage inchangé sur le fond** : la vue reproduit exactement le pool actuel de cross_import (les `target_doi` de `publication_relations`, sans source, restent candidats pour toutes les cibles ; le `doi NOT IN (staging du target)` final empêche tout fetch redondant).
5. **Circuit-breaker** posé sur les appels API de `resolve_ra` (`doi.org/ra`) et, dans la foulée, sur les `/prefixes` Crossref/DataCite du volet publisher (mêmes raisons que le cross-import : couper une source à bout de budget au lieu de la marteler).

## Phasage

### Phase 1 — Vue `candidate_dois` + branchement des deux requêtes

- [x] Migration Alembic `e1c7a4f9b3d6` : `CREATE VIEW candidate_dois(doi, source)` (union staging + related_dois + publication_relations[source NULL] + arXiv-dérivés). `source` exposée en enum `source_type` pour que les comparaisons `source = <param>` restent enum=enum côté appelants.
- [x] Régénérer le snapshot `infrastructure/db/schema.sql` (après `alembic upgrade head`).
- [x] `get_cross_import_dois` : `FROM candidate_dois` + filtres existants (exclusion du target via `source IS DISTINCT FROM`, RA, backoff). Équivalence couverte par `TestGetCrossImportDois`.
- [x] Sélection des préfixes à résoudre (`get_unresolved_prefixes_with_samples`) : `FROM candidate_dois` (tous, sans exclusion de source) → préfixes distincts non encore résolus.
- [x] Test de couverture : préfixes vus seulement via relations / arXiv désormais résolus (`TestGetUnresolvedPrefixes`).

### Phase 2 — Scission `resolve_ra` / volet publisher

- [x] Migration Alembic `f2d9b6a4c1e8` : colonne `doi_prefixes.publisher_checked_at` (marqueur « `/prefixes` déjà tenté »), backfill `= fetched_at` sur le backlog (337 rows terminales → le volet les ignore). Colonne + index `idx_doi_prefixes_publisher_pending` ajoutés à `infrastructure/db/tables.py`.
- [x] Régénérer le snapshot `infrastructure/db/schema.sql` (après `alembic upgrade head`).
- [x] `run_resolve_ra` : résout la RA des préfixes non résolus du pool (`doi.org/ra`) et `insert_ra(prefix, ra)` (`unknown` si non classé). Sous circuit-breaker (s'arrête sur `breaker.tripped`).
- [x] `run_resolve_publishers` : rows `publisher_id IS NULL ∧ publisher_checked_at IS NULL ∧ ra gérée` → `/prefixes` routé par RA (`unknown` → les deux + correction RA) → match/crée/attache, `mark_publisher_checked` quoi qu'il arrive (garde anti-réinterrogation). Sous circuit-breaker.
- [x] Repo : `insert_ra`, `get_prefixes_pending_publisher`, `set_prefix_publisher_metadata`, `mark_publisher_checked` (remplacent `insert_doi_prefix` / `get_unmatched_prefixes`). Test unitaire réécrit (Fakes + passes séparées).
- [x] CLI `interfaces/cli/pipeline/resolve_doi_prefixes.py` : enchaîne les deux passes.

### Phase 3 — Câblage pipeline

- [x] `run_pipeline.py` : phase `resolve_ra` insérée dans `PHASES` entre `extract` et `cross_imports` (helper `_run_resolve_ra`) ; `publishers_journals` appelle `_run_resolve_publishers`. Circuit-breaker posé dans chaque helper (`set_current_breaker`).
- [x] Tests : ordre `resolve_ra` avant `cross_imports` (`test_resolve_ra_runs_after_extract_before_cross_imports`) ; routage par RA couvert par `test_crossref_target_filters_non_crossref_prefixes` ; volet publisher (match/crée/attache, garde `checked`) couvert par les tests unitaires.
