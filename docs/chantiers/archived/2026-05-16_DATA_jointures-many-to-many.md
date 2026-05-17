# Normaliser les relations many-to-many cachées (arrays + JSONB de jointure)

Commencé et terminé le 2026-05-16

## Contexte

Le schéma actuel encode plusieurs relations many-to-many dans des colonnes non-relationnelles (arrays `integer[]` ou JSONB), au lieu de tables de jointure normales. Ce choix a été fait pour le confort de l'écriture (un seul UPDATE au lieu de DELETE + INSERT multiples) et pour éviter de multiplier les tables. Mais le coût est réel :

- **Pas de FK natives** : un id orphelin peut subsister silencieusement après suppression de la cible. Pas de cascade automatique.
- **Requêtes plus lourdes** : `WHERE :sid = ANY(structure_ids)` au lieu d'un `JOIN`. Lisibilité dégradée, indexation moins naturelle (GIN au lieu de btree multicolonne).
- **Pas d'introspection** : un outil BI (Metabase, Superset…) ne sait pas explorer un JSONB libre comme une relation, et `unnest()` sur un array reste du SQL avancé.

Trois cas concernés à des degrés divers, sur des volumes maintenant chiffrés :

| Colonne | Type | Rows totales | Rows non vides | Liens (table de jointure équivalente) | Cas |
|---|---|---|---|---|---|
| `source_authorships.structure_ids` | `integer[]` | 8.1 M | 173 K (2.1 %) | **338 K** | À normaliser |
| `authorships.structure_ids` | `integer[]` | 151 K | 94 K (62 %) | **196 K** | À normaliser |
| `person_name_forms.persons` | `jsonb` | 49.5 K | 49.5 K | **50.6 K** | À normaliser |
| `perimeters.structure_ids` | `integer[]` | 2 | 2 | ~10 | **À garder en array** (volume trivial, id mort inoffensif puisqu'on JOIN sur `structures(id)` ensuite) |

Total estimé des tables de jointure à créer : ~580 K rows répartis sur 3 tables — c'est 1/15 du volume de `source_authorships` brut. Indexation et requêtes restent peu coûteuses à ce niveau.

## Décisions

### Sortir des arrays / JSONB pour 3 colonnes

| Avant | Après |
|---|---|
| `source_authorships.structure_ids integer[]` | Table `source_authorship_structures (source_authorship_id, structure_id)` avec FK `ON DELETE CASCADE` des deux côtés |
| `authorships.structure_ids integer[]` | Table `authorship_structures (authorship_id, structure_id)` avec FK `ON DELETE CASCADE` des deux côtés |
| `person_name_forms.persons jsonb` (`{"<person_id>": ["<source>", ...]}`) | Dénormalisation de la table existante : `person_name_forms (name_form, person_id, sources text[])` avec PK composite `(name_form, person_id)` et FK `person_id → persons(id) ON DELETE CASCADE`. Pas de table de jointure dédiée — la table n'a plus de propriétés propres (les `id`/`created_at`/`updated_at` disparaissent), elle devient elle-même la relation many-to-many. C'est la contrainte historique `UNIQUE (name_form)` qui forçait le JSONB ; sans elle, le modèle simple "une row par (name_form, person_id)" est l'évidence. |

Le `sources text[]` reste justifié : la liste des sources où la forme a été observée pour cette personne est une donnée de la relation, sans cardinalité forte (1-6 valeurs dans un enum fixe). C'est l'élément JSONB clé/valeur (`person_id → list[source]`) qui posait problème, pas le détail "sources observées".

### Garder l'array sur `perimeters`

Volume trivial (2 perimeters, < 10 ids au total). La complexité d'une table de jointure ne se justifie pas. Un id mort y est inoffensif (on JOIN sur `structures(id)` dans les requêtes, les ids morts sont silencieusement filtrés).

### Suppression complète des colonnes après migration

Pas de conservation d'un "cache dénormalisé" (colonne `structure_ids` qui resterait à côté de la table de jointure). Sinon on retombe sur le problème de divergence qu'on essaie de résoudre. Toutes les queries qui consomment ces colonnes doivent être adaptées pour utiliser la table de jointure.

## Phasage

### Phase 1 — Dénormaliser `person_name_forms` (le plus simple)

- Volume le plus petit (50 K liens).
- Moins de call-sites à adapter (alimentation : `populate_person_name_forms.py` ; consommation : matching de personnes dans `create_persons_from_source_authorships.py` et requêtes admin).
- Sert de POC pour valider l'approche avant d'attaquer les deux tables plus lourdes.

Décisions tranchées au démarrage : `sources text[]` (pas de 3 colonnes), pas de contrainte DB sur l'invariant "row supprimée si sources vide" (logique applicative pure côté repo).

- [x] Migration Alembic `0016_person_name_forms_denormalize` : décompose JSONB → triplets en table temp, DROP TABLE, recrée la table dénormalisée, repopuler (cascade CHECK / UNIQUE / index GIN / sequence supprimés au passage).
- [x] `infrastructure/db/tables.py` : nouvelle déclaration `(name_form, person_id, sources[])` + PK composite + index sur `person_id`.
- [x] `domain/persons/name_forms.py` : ne garde que le VO `PersonNameForm` et la factory `compute_person_name_forms`. Helpers JSONB (`add_person_source`, `remove_person_source`, `remove_person`, `merge`, `is_ambiguous`, `person_ids`, `all_sources`, type `PersonsDict`) supprimés.
- [x] `infrastructure/repositories/person_repository/_name_forms.py` : réécriture en SQL direct. Conserve `refresh_name_forms` / `add_name_form` / `detach_name_form` (API publique du repo) et expose `add_person_source` / `remove_person_source` / `is_ambiguous` comme opérations SQL (sémantique préservée, implémentation DB).
- [x] `infrastructure/repositories/person_repository/_core.py` : adapter `merge_into` (cross-person UPSERT + DELETE) et `find_by_id` (`WHERE person_id = :pid` au lieu de `WHERE persons ? :pid`).
- [x] Port `application/ports/pipeline/name_forms.py` + adapter `infrastructure/queries/name_forms.py` : nouvelle signature de synchronisation (sync depuis table temp en bulk au lieu de boucle update/insert/delete par row).
- [x] Orchestrateur `application/pipeline/persons/populate_person_name_forms.py` : agrégation SQL `GROUP BY name_form, person_id` + sync bulk.
- [x] Queries lecture (`infrastructure/queries/persons/admin.py`, `list.py`, `create.py`) : `LATERAL jsonb_object_keys(pnf.persons)` → JOIN naturel sur `person_name_forms`.
- [x] Supprimer `interfaces/cli/oneshot/backfill_name_forms_persons.py` (one-shot historique du chantier précédent, sans objet maintenant).
- [x] Tests : adapter `tests/integration/infrastructure/queries/test_name_forms_queries.py`, retirer les tests unitaires des helpers JSONB disparus dans `tests/unit/domain/persons/test_name_forms.py`.
- [x] `alembic upgrade head` (Laura) + run pytest ciblé sur le périmètre — 248/248 passent.

### Phase 2 + 3 fusionnées — `authorship_structures` + `source_authorship_structures`

Décision prise au démarrage : les deux migrations sont fusionnées en une seule passe. Raison : `build_authorships.propagate_perimeter_and_structures_from` lit `source_authorships.structure_ids[]` et écrit `authorships.structure_ids[]` ; les séparer impose une transition asymétrique (lecture array / écriture jointure) qui sera réécrite dans Phase 3. De plus, les queries de lecture qui touchent les deux tables ensemble (`hal_problems`, `affiliations`, `laboratories`, `stats/labs`) imposeraient un double passage sur les mêmes fichiers.

Volumes cumulés :
- `authorship_structures` : 196 K liens, 151 K rows source.
- `source_authorship_structures` : 338 K liens, 8.1 M rows source (2 % seulement avec structure_ids).

Call-sites cartographiés (cf. cartographie au démarrage 2026-05-16) :
- ~41 occurrences `authorships.structure_ids` sur ~16 fichiers.
- ~20 occurrences `source_authorships.structure_ids` sur ~11 fichiers.
- Forte intersection : `authorships_build.py`, `affiliations.py`, `laboratories.py`, `stats/labs.py`, `hal_problems.py`.

Adaptations principales :
- **Pipeline alimentation** : `populate_affiliations.py` (écrit dans `source_authorships.structure_ids[]`), `build_authorships.py` (propage vers `authorships.structure_ids[]`). Les deux passent à INSERT dans les tables de jointure.
- **Lecture filtres** : `:sid = ANY(structure_ids)` → `JOIN authorship_structures USING (authorship_id)` (ou `source_authorship_structures`).
- **Drop colonnes** après migration.
- **`in_perimeter`** : conservé en l'état (la propagation `build_authorships` reste, on déplace juste les `structure_ids[]`). La question de supprimer cette colonne et matérialiser le périmètre fait l'objet d'une fiche séparée [`DATA_perimeter-materialise.md`](DATA_perimeter-materialise.md), à traiter après ce chantier.

Étapes :

- [x] Cartographier les call-sites `authorships.structure_ids` et `source_authorships.structure_ids`.
- [x] Migration Alembic `0017_authorship_structures_normalize` : crée `authorship_structures` + `source_authorship_structures` (FK ON DELETE CASCADE, PK composite, index sur `structure_id`), backfill via `unnest` croisé avec `structures` (filtre les ids morts), DROP des colonnes array.
- [x] `infrastructure/db/tables.py` : ajout des deux tables de jointure.
- [x] `application/structures.py` : retrait de l'appel à `purge_structure_id_from_arrays` (cascade DB la remplace) et docstring mise à jour.
- [x] Pipeline : `application/pipeline/affiliations/populate_affiliations.py` + `infrastructure/queries/affiliations.py` : INSERT dans `source_authorship_structures`.
- [x] Pipeline : `application/pipeline/authorships/build_authorships.py` + `infrastructure/queries/authorships_build.py` : INSERT dans `authorship_structures` depuis `source_authorship_structures` (propagation union des sources).
- [x] Repo : `infrastructure/repositories/authorship_repository.py` (`find_by_publication_id`, `recompute_in_perimeter_on_source_authorships`, `propagate_in_perimeter_to_authorships`) et `infrastructure/repositories/person_repository/_authorships.py`.
- [x] Queries : `infrastructure/queries/filters.py` (`lab_clause`, `no_lab_clause`).
- [x] Queries : `infrastructure/queries/laboratories.py`.
- [x] Queries : `infrastructure/queries/hal_problems.py`.
- [x] Queries : `infrastructure/queries/persons/detail.py`.
- [x] Queries : `infrastructure/queries/person_duplicates.py`.
- [x] Queries : `infrastructure/queries/publications/list.py`, `detail.py`, `facets.py`.
- [x] Queries : `infrastructure/queries/stats/labs.py`, `summary.py`.
- [x] CLI : `interfaces/cli/maintenance/merge_person_duplicates_by_lab.py`.
- [x] Tests intégration (laboratories, publications_list, publications_detail, hal_problems, authorships_service, idempotence/test_authorships, idempotence/test_affiliations).
- [x] Docs : `docs/architecture.md`, `docs/donnees.md`.
- [x] `alembic upgrade head` (Laura) + `python -m infrastructure.db.dump_schema` (Laura).
- [x] Run pytest ciblé sur le périmètre touché.

## Bénéfices attendus

- **FK natives** sur les 3 relations → la cascade `delete_structure` ou `delete_person` devient automatique. Plus de risque d'id mort, plus besoin du purge applicatif actuel.
- **Requêtes plus naturelles** : `JOIN authorship_structures USING (authorship_id)` au lieu de `WHERE :sid = ANY(structure_ids)`. Plans Postgres plus lisibles.
- **Introspection BI possible** : Metabase/Superset peuvent suivre les relations comme des FK normales.
- **Cohérence avec le reste du schéma** : tu as déjà `source_authorship_addresses`, `structure_relations`, `address_structures` — toutes des tables de jointure normales. Sortir les 3 cas restants harmonise.

## Court terme (déjà fait)

En attendant ce chantier, le service `application/structures.py:delete_structure` purge déjà manuellement les `structure_ids[]` via `repo.purge_structure_id_from_arrays(structure_id)` (commit où cette fiche a été créée). Cela ferme la fenêtre de bug immédiate. Une fois ce chantier abouti et les FK en place, la méthode `purge_structure_id_from_arrays` disparaîtra (la cascade DB fait le job).
