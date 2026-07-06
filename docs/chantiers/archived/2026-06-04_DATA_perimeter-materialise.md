# Chantier — Matérialiser le périmètre : table `perimeter_structures` + suppression `in_perimeter`

Terminé le 2026-06-04

> **Phase 1 activée comme sous-chantier de [`DATA_donnees-derivees`](DATA_donnees-derivees.md).** La matérialisation de `perimeter_structures` (Phase 1) se justifie en soi par le déblocage de la matview `source_authorship_structures` (cf. Contexte), indépendamment de `in_perimeter`. Les Phases 2-3 (suppression de `in_perimeter`) restent conditionnées aux benchmarks de lecture.

## Contexte

Aujourd'hui, l'appartenance d'une authorship au périmètre UCA est portée par une colonne booléenne dérivée :

- `authorships.in_perimeter boolean` et `source_authorships.in_perimeter boolean`
- Calculée par `build_authorships.propagate_perimeter_from` (OR depuis `source_authorships.in_perimeter`). Les structures rattachées sont, elles, dans la matview `authorship_structures` (dérivée de `source_authorship_structures`), distincte de la question `in_perimeter`.
- Le périmètre lui-même : `perimeters.structure_ids integer[]` (racines), et la résolution récursive descend dans `structure_relations` via une CTE — cf. `infrastructure/perimeter.py:get_perimeter_structure_ids`.

`in_perimeter` est donc un **cache dérivable** :
- Source = structures rattachées (via FK une fois le chantier M2M abouti) + structures du périmètre (clôture transitive sur `structure_relations`).
- Stale possible : un changement de `perimeters.structure_ids` ou de `structure_relations` invalide la colonne sur des millions de rows sans qu'aucun mécanisme automatique ne le détecte. La cohérence repose sur `build_authorships` re-run.

Question soulevée le 2026-05-16 : avec les FK natives du chantier M2M, le recalcul à la volée devient un JOIN trivial. Faut-il **supprimer `in_perimeter`** et résoudre l'appartenance au périmètre à la lecture, via une table matérialisée `perimeter_structures (perimeter_id, structure_id)` qui sert aussi d'autres usages (UI listant les structures d'un périmètre, analyses cross-périmètre) ? "D'une pierre deux coups."

**Volume des call-sites** : 233 occurrences de `in_perimeter` sur 61 fichiers. Toutes les queries de listing publications, facettes, agrégats stats, filtrage admin passent par cette colonne. Refactoring d'ampleur significative.

### Deuxième motivation, indépendante de `in_perimeter` : débloquer la matview `source_authorship_structures`

`source_authorship_structures` (SAS) est aujourd'hui une table de jointure maintenue impérativement en phase `affiliations` : `set_structure_ids_from_addresses` y INSERT `source_authorship_addresses ⋈ address_structures` filtré par `ast.structure_id = ANY(:affiliation_structure_ids)`, où `affiliation_structure_ids` est la **clôture récursive du périmètre calculée en Python** (`get_perimeter_structure_ids`) et passée en paramètre. Ce paramètre runtime est précisément ce qui interdit d'en faire une matview (déclarative, sans paramètre) : il faut que la clôture soit une **relation joignable**. Matérialiser `perimeter_structures` la fournit. SAS ne porte aucun état natif (feuille pure) — pas d'obstacle de faisabilité une fois la clôture disponible.

Une fois SAS en matview, on retire toute sa maintenance impérative — l'INSERT `ON CONFLICT` d'`affiliations`, le purge full-mode `reset_source_authorships_for`, et la cascade `ON DELETE` depuis `source_authorships` en normalize — au profit d'un `REFRESH` toujours exact. Le sens du troc est bon : la clôture périmètre change rarement (édition admin de `perimeters.structure_ids` / `structure_relations`), SAS churne à chaque run sur des millions de rows — on matérialise le petit-rare pour rendre le gros-fréquent déclaratif. Réserve : SAS alimente déjà la matview `authorship_structures`, d'où une chaîne `perimeter_structures → SAS → authorship_structures` à rafraîchir dans l'ordre. Le bénéfice est architectural (déclaratif, exact, moins de code de rebuild), pas une perf de normalize — la cascade retirée n'est que du cleanup peu coûteux.

Cette motivation ne justifie que la **Phase 1** (table `perimeter_structures` matérialisée + conversion SAS), sans toucher aux 233 call-sites de `in_perimeter`. Elle suffit à activer la Phase 1 comme sous-chantier de [`DATA_donnees-derivees`](DATA_donnees-derivees.md) — qui subordonnait justement le verdict matview de SAS à la matérialisation du périmètre.

## Décisions (à trancher au démarrage)

### Approche `perimeter_structures` matérialisée

Créer une table dénormalisée qui matérialise la clôture transitive du périmètre :

```sql
CREATE TABLE perimeter_structures (
    perimeter_id integer NOT NULL REFERENCES perimeters(id) ON DELETE CASCADE,
    structure_id integer NOT NULL REFERENCES structures(id) ON DELETE CASCADE,
    PRIMARY KEY (perimeter_id, structure_id)
);
CREATE INDEX idx_ps_structure_id ON perimeter_structures (structure_id);
```

Le refresh est explicite (pas de trigger récursif). Deux options :
- **Job idempotent** dans le pipeline (phase `affiliations` ou nouvelle phase `perimeter`).
- **Méthode du repo perimeter** appelée à chaque modification de `perimeters.structure_ids` ou `structure_relations` (côté API admin).

### Tradeoff filtrage

Avec la table matérialisée, le filtre devient :

```sql
WHERE EXISTS (
    SELECT 1 FROM authorship_structures aus
    JOIN perimeter_structures ps USING (structure_id)
    WHERE aus.authorship_id = a.id AND ps.perimeter_id = :pid
)
```

Vs aujourd'hui `WHERE a.in_perimeter = TRUE` (index lookup direct).

À mesurer avant de trancher : sur les queries chaudes (listing publications, facettes), le coût en lecture pourrait être prohibitif. Option intermédiaire : matérialiser `perimeter_structures` **sans** supprimer `in_perimeter` — les deux pour des usages différents.

## Phasage

### Phase 1 — Table `perimeter_structures` matérialisée (autonome)

- [x] Migration Alembic : créer la table avec FK CASCADE des deux côtés. (83a1fae9)
- [x] Job de remplissage : `refresh_perimeter_structures` (CTE récursive `est_tutelle_de`, idempotent). (83a1fae9)
- [x] Hook dans le pipeline (tête de phase `affiliations`) pour refresh à chaque run. (83a1fae9)
- [ ] Hook côté API admin : refresh quand `perimeters.structure_ids` ou `structure_relations` change. **Reporté** : le refresh pipeline couvre fonctionnellement (staleness bornée à un run entre deux éditions admin du périmètre, très rares) ; à câbler si gênant.
- [x] Tests : invariants de cohérence (clôture `est_tutelle_de`, pas `est_partenaire_de` ; idempotence). (83a1fae9)
- [x] Convertir `source_authorship_structures` en matview (`source_authorship_addresses ⋈ address_structures ⋈ perimeter_structures`, filtre `is_confirmed` embarqué). Maintenance impérative retirée (`set_structure_ids_from_addresses`, purge SAS de `reset_source_authorships_for`, resync chirurgical admin, FK `ON DELETE CASCADE`). Refresh réordonné `perimeter_structures → source_authorship_structures → authorship_structures` (pipeline + chemin admin). (176bae4f)

À ce stade, `in_perimeter` reste en base. `perimeter_structures` sert d'index supplémentaire (projections UI « structures d'un périmètre », audits) **et** de relation joignable qui déclarativise `source_authorship_structures`.

### Phase 2 — Évaluation : supprimer `in_perimeter` ou pas ? — VERDICT : conserver

Audit du 2026-06-04, EXPLAIN ANALYZE sur la base réelle (109 308 authorships, 9 472 136 source_authorships, 2 périmètres).

- [x] Équivalence sémantique vérifiée : `authorships.in_perimeter = TRUE` ⟺ `EXISTS(authorship_structures ⋈ perimeter_structures, perimeter_id = uca)` — diff symétrique nulle (106 842 = 106 842). Le remplacement par JOIN est correct (le périmètre restreint `uca`, pas `alliance_uca` qui sert aux affiliations).
- [x] Colonne générée : **impossible**. Une colonne `GENERATED` Postgres doit être immuable et ne référencer que des colonnes de la même row (ni sous-requête ni JOIN). `in_perimeter` dépend d'un JOIN vers `perimeter_structures` → exclu d'office.
- [x] Benchmarks (warm cache, médiane) :
  - Count plein du périmètre : `in_perimeter` ~60 ms vs JOIN ~115 ms (**+90 %**).
  - Listing paginé (LIMIT 25) : ~38 ms vs ~40-60 ms (comparable).
  - Orphelines au niveau `source_authorships` (9,4 M lignes) : `in_perimeter` ~770 ms vs JOIN `source_authorship_structures` ~5 700 ms (**×7,4**).
- [x] Queries non remplaçables proprement : `hal_affiliation_conflicts` (comparaison cross-source HAL vs WoS/OA), agrégats `COUNT(*) FILTER (in_perimeter)` par compte source (persons/detail).

Conclusion. Au niveau canonique (`authorships`, 109 k) le JOIN reste tenable. Au niveau `source_authorships` (9,4 M), l'index partiel sur le booléen est irremplaçable : ×7,4 sur les orphelines, très au-delà de la cible <30 %. On **conserve `in_perimeter`** comme cache de lecture. `perimeter_structures` garde toute sa valeur (déblocage des matviews — Phase 1 — et usages UI/analyses).

### Phase 3 — Suppression `in_perimeter` — ABANDONNÉE

Non justifiée : la Phase 2 conclut au maintien de `in_perimeter` (régression ×7,4 sur `source_authorships`). `perimeter_structures` et `in_perimeter` coexistent pour des usages distincts (matérialisation joignable vs cache de lecture rapide).

## Bénéfices attendus

- **Déclarativise `source_authorship_structures`** (Phase 1, court terme) : la clôture en relation joignable permet la matview SAS et retire l'INSERT/purge/cascade impératifs (cf. Contexte). Bénéfice acquis sans toucher à `in_perimeter`.
- **Cohérence** : plus de stale possible sur l'appartenance au périmètre — la source unique est la table matérialisée, mise à jour explicitement.
- **Simplification pipeline** : `build_authorships` n'a plus à propager `in_perimeter` à chaque run.
- **Nouvel usage** : `perimeter_structures` est utilisable directement par l'UI admin (lister les structures du périmètre courant), les analyses (combien de structures dans le périmètre UCA ?), etc.
- **Découplage data/cache** : aujourd'hui `in_perimeter` mélange "appartenance dérivée" et "filtre rapide". Séparer matérialisation et cache rend le modèle plus lisible.

## Questions ouvertes

- **Trigger ou refresh explicite ?** Trigger sur `perimeters` + `structure_relations` = automatique mais ajoute une couche d'invisible (debug compliqué). Refresh explicite = plus prévisible mais expose à l'oubli côté admin. **Reco initiale : refresh explicite côté repo perimeter (à chaque écriture sur les tables concernées) + sanity check en début de pipeline.**
- **Plusieurs périmètres ?** Aujourd'hui le projet a 2 périmètres (`uca`, `alliance_uca`). La table matérialisée prévoit le multi-perimeter dès le départ.
- **Quand attaquer ?** Le chantier M2M (`DATA_jointures-many-to-many.md`) est terminé (`authorship_structures` et `source_authorship_structures` en place) — le verrou de séquencement est levé, la Phase 1 est activable.
