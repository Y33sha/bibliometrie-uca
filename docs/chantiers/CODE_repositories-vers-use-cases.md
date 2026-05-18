# Chantier — Repositories → use cases (orchestration en application)

Commencé le 2026-05-11

## Contexte

Audit fait le 2026-05-11 sur les 10 repositories de
`infrastructure/repositories/`. Plusieurs exposent des méthodes qui
font de l'orchestration applicative : règles métier encodées en SQL,
synchronisation cross-agrégat, scoring, fusion. Ces méthodes ont leur
place dans `application/`, pas en infra.

Audit transactionnel en parallèle : aucun `.commit()` dans les
repositories (✓ Cosmic Python compatible). Les commits vivent dans
`application/pipeline/*` avec rollback dans les `except`. Le
`_savepoint.py` (`begin_nested()` SA) est idiomatique. Quelques
nuances mineures à nettoyer.

Ce chantier couvre les deux volets : **(A) extraction de l'orchestration
hors des repositories** et **(B) polish de la discipline transactionnelle**.

## Audit — Volet A : orchestration applicative dans les repositories

Sains (rien à faire) :
- `audit_repository.py`
- `journal_repository.py` — `merge_journal_into` est de la chorégraphie
  SQL bien orchestrée par `application/journals.py`
- `publisher_repository.py` — idem
- `perimeter_repository.py`
- `structure_repository.py`

Contaminés, par sévérité :

| Repository | Sévérité | Méthodes problématiques |
|---|---|---|
| `person_repository/_authorships.py` | 🔴 critique | `batch_assign_orphans`, `ensure_truth_authorship` |
| `authorship_repository.py` | 🔴 critique | `delete_orphan_authorships_for_person`, `recompute_in_perimeter_on_source_authorships`, `propagate_in_perimeter_to_truth_authorships` |
| `publication_repository.py::merge_into` | 🟠 majeur | règle métier OA mélangée au SQL |
| `address_repository.py` | 🟠 majeur | 4 méthodes de propagation cross-agrégat (déjà documentées comme exception) |

Pattern récurrent : plusieurs UPDATE/SELECT séquentiels qui touchent
≥2 agrégats, avec une règle métier encodée dans le SQL (priorité de
source, règle OA, règle d'orphelinat, propagation cross-agrégat).
Placées « près des données » par commodité, mais le test, l'audit et
la traçabilité y perdent.

## Audit — Volet B : discipline transactionnelle

Acquis :
- Zéro commit dans `infrastructure/repositories/` ✓
- Rollback dans les `except` des use cases pipeline ✓
- `_savepoint.py` idiomatique ✓

Exceptions à expliciter (pas à supprimer) :
- **Batch commits dans pipelines** (`if (i+1) % N == 0: conn.commit()`)
  dans `create_publications.py`, `enrich_journal_apc.py`, `normalize/base.py`,
  `resolve_addresses.py`, `refetch_truncated.py`. Justifiés par la
  taille des batchs (100k+ items) — un crash ne doit pas tout perdre.
- **Commits dans `infrastructure/sources/*`** (extracteurs API,
  `fetch_missing_doi.py`). Ce sont des adapters batch, pas des
  repositories : commit page-par-page = checkpoint pour préserver les
  appels API coûteux. Cosmic Python parle des repositories, ces
  adapters ont une logique différente. Défendable, à documenter.

À corriger (mineurs) :
- **Double commit dans `normalize/base.py:194-196`** : `commit()` →
  `post_process()` → `commit()`. À investiguer : si `post_process` doit
  voir la batch commitée, légitime ; sinon artefact à nettoyer.
- **Commit après reset isolé dans `enrich_journal_apc.py:118`** :
  casse l'atomicité du use case (si l'enrichissement plante après, le
  reset reste appliqué). Pourrait devenir un savepoint englobant.
- **Commits sur `KeyboardInterrupt`** dans `enrich_journal_apc.py:187`
  et `normalize/base.py:208` : avec les batch commits déjà tous les N
  items, le commit final sur Ctrl+C n'apporte que la dernière fenêtre
  incomplète. À vérifier qu'on en a vraiment besoin.

## Décisions

1. **Ordre d'attaque privilégié** : volet A avant volet B. L'extraction
   de l'orchestration est le gros chantier ; le polish transactionnel
   est rapide et peut être traité en queue de chantier ou en
   « nettoyage de fin ».

2. **Granularité des phases pour le volet A** : une phase = un
   repository (ou un sous-ensemble cohérent). Tests d'intégration
   ciblés à chaque phase, suite complète seulement à la fin.

3. **Placement cible du code extrait** :
   - Logique de `person_repository/_authorships.py` → étendre
     `application/persons.py` ou créer `application/authorships_truth.py`
     (à trancher au moment du chantier selon la taille).
   - Logique de perimeter dans `authorship_repository.py` → créer
     `application/perimeter_propagation.py` (ou intégrer à
     `application/addresses_structures.py`).
   - Règle OA de `merge_into` → fonction pure dans `domain/publication.py`
     (ex. `best_oa_status_on_merge`), appelée par
     `application/publications.merge_publications`.
   - Cascade countries de `address_repository.py` → use case
     `application/addresses_countries_propagation.py` (formalise
     l'« exception » documentée actuellement).

4. **Frontière conservée pour les repositories** : après extraction,
   chaque repo n'expose que des ports minces (CRUD, requêtes
   paramétrées, agrégations SQL simples). Aucune décision métier dans
   le SQL.

5. **Pas de chantier global sur les batch commits** : on garde le
   pattern, on le documente. Toucher à ce pattern impliquerait de
   changer la robustesse du pipeline en production.

## Phasage proposé

### Phase 1 — `person_repository/_authorships.py`

- [x] Restructurer `application/authorships.py` en sous-package
  `application/authorships/` (`__init__.py` vide + `core.py`)
- [x] Décomposer `batch_assign_orphans` du repo en 4 méthodes
  atomiques : `assign_orphan_source_authorships_to_person`,
  `create_authorships_from_sources`,
  `link_source_authorships_to_authorships`,
  `get_distinct_name_forms_from_source_authorships`. `SOURCE_PRIORITY`
  passée en paramètre par le use case.
- [x] Décomposer `ensure_truth_authorship` du repo en 5 méthodes
  atomiques : `find_publication_id_for_source_authorship`,
  `insert_authorship_if_missing`,
  `link_source_authorships_to_authorship_for_pair`,
  `recompute_authorship_author_position_and_corresponding`,
  `recompute_authorship_in_perimeter_and_structures`.
- [x] Créer le module `application/authorships/assign_orphans.py` avec
  les use cases `assign_orphan_authorship` (single, ex-persons.py) et
  `batch_assign_orphan_authorships` (batch, ex-persons.py), plus le
  helper privé `_refresh_authorship_from_sources` qui orchestre les 5
  étapes de recomposition. Suppression du jargon « truth » dans tout
  le code touché.
- [x] Adapter port `PersonRepository`, router API admin, tests.

### Phase 2 — `authorship_repository.py` perimeter

- [x] Vérification : l'orchestration `recompute_in_perimeter_*` +
  `propagate_in_perimeter_*` est **déjà** côté use case
  (`propagate_uca_for_addresses` dans `application/authorships/core.py`).
  Les méthodes du repo sont des agrégations SQL atomiques (CTE
  d'agrégation cross-row), pas de la logique métier déguisée.
  Rien à extraire.
- [x] `delete_orphan_authorships_for_person` : la « règle d'orphelinat »
  est un simple `NOT EXISTS` SQL, formulation la plus directe. Extraire
  vers Python = 2 round-trips au lieu d'1 pour gain marginal. Laissé
  tel quel.
- [x] Suppression du jargon « truth » dans `authorship_repository.py` :
  `get_source_authorship_truth_id` → `get_authorship_id_for_source`,
  `has_active_source_attestation(truth_id)` →
  `has_active_source_attestation(authorship_id)`,
  `propagate_in_perimeter_to_truth_authorships` →
  `propagate_in_perimeter_to_authorships`. Adaptations du port et
  des call sites dans `application/authorships/core.py`.

### Phase 3 — Règle OA dans `publication_repository.merge_into`

Petit refactoring isolé.

- Créer `domain.publication.best_oa_status_on_merge(a, b)` (fonction
  pure). La règle « diamond gagne toujours » devient testable
  unitairement.
- Modifier `application/publications.merge_publications` pour appeler
  cette fonction puis passer la valeur résolue à `repo.merge_into`.
- Simplifier le SQL de `merge_into` : `oa_status = :final_oa` au lieu
  du `CASE` actuel.

Tests : tests unitaires de la fonction de domaine + tests
d'intégration des merges existants.

### Phase 4 — Cascade countries de `address_repository.py`

- [ ] Créer `application/addresses_countries_propagation.py` (nom à
  confirmer). Y orchestrer la cascade
  `addresses.countries → source_publications.countries → publications.countries`.
- [ ] Le repo `address_repository.py` conserve les méthodes SQL atomiques
  (`update_address_countries`, `bulk_update_source_publications_countries`,
  etc.) sans logique de cascade.
- [ ] Mettre à jour `docs/architecture.md` : retirer (ou nuancer) la
  mention « exception cross-aggregate documentée » puisque la cascade
  devient explicite côté application.

Tests : tests d'intégration sur la cascade countries.

### Phase 5 — Volet B : polish transactionnel

À traiter en queue de chantier (ordre indifférent) :

- [ ] Investiguer le double commit `normalize/base.py:194-196`. Soit
  documenter pourquoi, soit nettoyer.
- [ ] Décider du sort du `commit()` après reset dans
  `enrich_journal_apc.py:118` : savepoint englobant ou statu quo
  documenté.
- [ ] Auditer les commits sur `KeyboardInterrupt` : nécessaires ou
  doublon des batch commits ?
- [ ] Ajouter à `docs/architecture.md` une section « Discipline
  transactionnelle » qui formalise : repositories sans commit, batch
  commits dans pipelines comme exception assumée, commits dans
  `infrastructure/sources/*` comme adapters batch.

## Hors scope

- [ ] **Pas de réécriture des merges sains** (`journal_repository`,
  `publisher_repository`). La chorégraphie SQL y est déjà bien
  orchestrée par les use cases.
- [ ] **Pas de migration des batch commits vers un autre pattern** :
  conserver, documenter.
- [ ] **Pas de migration des extracteurs `infrastructure/sources/*`**
  vers `application/`. Ce sont des adapters batch, leur place est
  défendable en infra.
- [ ] **Pas de refonte du `_savepoint.py`** : le pattern est correct.

## Questions ouvertes

- **Nommage des modules application/** : étendre les modules
  existants (`application/persons.py`, `application/publications.py`,
  `application/addresses_structures.py`) ou créer des modules
  dédiés (`application/authorships_truth.py`,
  `application/perimeter_propagation.py`,
  `application/addresses_countries_propagation.py`) ? À trancher au
  démarrage de chaque phase selon la taille du code extrait.
- **Granularité des ports résultants** : faut-il viser un port
  ultra-mince (une méthode = une requête SQL atomique) ou accepter
  des méthodes « moyennes » (1 méthode = 1 transaction SQL multi-statement
  sans logique métier) ? À discuter au démarrage de la Phase 1.
- **Ordre Phase 1/Phase 2** : person `batch_assign_orphans` appelle
  `_name_forms.add_name_form` (cross-module). À vérifier qu'il n'y a
  pas de dépendance avec les méthodes perimeter de
  `authorship_repository` qui rendrait Phase 2 prérequis de Phase 1.

## Lien avec d'autres chantiers

- `docs/chantiers/2026-05-06_ports-cleanup.md` : a déjà documenté la
  règle « port = persistance d'agrégat, signatures domain-only,
  méthodes en termes métier ». Ce chantier-ci en est la suite logique
  : appliquer la règle à l'orchestration interne des repos, pas
  seulement à leurs signatures publiques.
- `docs/chantiers/2026-05-08_regles-metier-domain.md` : si certaines
  règles extraites (OA merge, orphelinat) sont candidates au domaine,
  elles s'inscrivent dans cette logique de centralisation des règles
  métier.
- `docs/chantiers/sqlalchemy-core-adoption.md` : la migration SA Core
  étant terminée, ce chantier travaille sur du code SA stable (pas
  de mélange psycopg/SA à gérer).
