# Chantier — Matérialiser le périmètre : table `perimeter_structures` + suppression `in_perimeter`

## Contexte

Aujourd'hui, l'appartenance d'une authorship au périmètre UCA est portée par une colonne booléenne dérivée :

- `authorships.in_perimeter boolean` et `source_authorships.in_perimeter boolean`
- Calculée par `build_authorships.propagate_perimeter_and_structures_from` à partir des `structure_ids[]` (Phase 2/3 du chantier M2M : passera en table de jointure `authorship_structures` / `source_authorship_structures`).
- Le périmètre lui-même : `perimeters.structure_ids integer[]` (racines), et la résolution récursive descend dans `structure_relations` via une CTE — cf. `infrastructure/perimeter.py:get_perimeter_structure_ids`.

`in_perimeter` est donc un **cache dérivable** :
- Source = structures rattachées (via FK une fois le chantier M2M abouti) + structures du périmètre (clôture transitive sur `structure_relations`).
- Stale possible : un changement de `perimeters.structure_ids` ou de `structure_relations` invalide la colonne sur des millions de rows sans qu'aucun mécanisme automatique ne le détecte. La cohérence repose sur `build_authorships` re-run.

Question soulevée le 2026-05-16 : avec les FK natives du chantier M2M, le recalcul à la volée devient un JOIN trivial. Faut-il **supprimer `in_perimeter`** et résoudre l'appartenance au périmètre à la lecture, via une table matérialisée `perimeter_structures (perimeter_id, structure_id)` qui sert aussi d'autres usages (UI listant les structures d'un périmètre, analyses cross-périmètre) ? "D'une pierre deux coups."

**Volume des call-sites** : 233 occurrences de `in_perimeter` sur 61 fichiers. Toutes les queries de listing publications, facettes, agrégats stats, filtrage admin passent par cette colonne. Refactoring d'ampleur significative.

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

- [ ] Migration Alembic : créer la table avec FK CASCADE des deux côtés.
- [ ] Job de remplissage : adapter `infrastructure/perimeter.py:get_perimeter_structure_ids` pour aussi écrire dans `perimeter_structures` (ou via un script CLI dédié).
- [ ] Hook dans le pipeline (phase `affiliations` ou dédiée) pour refresh à chaque run.
- [ ] Hook côté API admin : refresh quand `perimeters.structure_ids` ou `structure_relations` change.
- [ ] Tests : invariants de cohérence (cardinalité, clôture transitive correcte).

À ce stade, `in_perimeter` reste en base. La nouvelle table est juste un index supplémentaire utilisable pour des projections UI ou des audits.

### Phase 2 — Évaluation : supprimer `in_perimeter` ou pas ?

Décision conditionnée à des mesures :

- [ ] Benchmarker les queries chaudes (listing publications, facettes, stats) avec le filtre par `perimeter_structures` vs `in_perimeter`. Cible : différence < ~30 % en p95.
- [ ] Identifier les queries non remplaçables (ex. agrégats par périmètre cross-perimetres ?) qui rendraient `in_perimeter` indispensable.
- [ ] Si le benchmark passe → Phase 3. Sinon → on conserve `in_perimeter` comme cache de lecture, et `perimeter_structures` reste utile pour les autres usages (UI, analyses).

### Phase 3 — Suppression `in_perimeter` (conditionnelle)

Seulement si Phase 2 valide.

- [ ] Migration Alembic : DROP `authorships.in_perimeter` + `source_authorships.in_perimeter`.
- [ ] Adapter les 233 call-sites pour passer par le JOIN `perimeter_structures`.
- [ ] Simplifier `build_authorships` : retirer la propagation de `in_perimeter` (la cohérence est garantie par la table matérialisée à la lecture).
- [ ] Adapter les tests qui utilisent `in_perimeter=TRUE` dans des fixtures.

## Bénéfices attendus

- **Cohérence** : plus de stale possible sur l'appartenance au périmètre — la source unique est la table matérialisée, mise à jour explicitement.
- **Simplification pipeline** : `build_authorships` n'a plus à propager `in_perimeter` à chaque run.
- **Nouvel usage** : `perimeter_structures` est utilisable directement par l'UI admin (lister les structures du périmètre courant), les analyses (combien de structures dans le périmètre UCA ?), etc.
- **Découplage data/cache** : aujourd'hui `in_perimeter` mélange "appartenance dérivée" et "filtre rapide". Séparer matérialisation et cache rend le modèle plus lisible.

## Questions ouvertes

- **Trigger ou refresh explicite ?** Trigger sur `perimeters` + `structure_relations` = automatique mais ajoute une couche d'invisible (debug compliqué). Refresh explicite = plus prévisible mais expose à l'oubli côté admin. **Reco initiale : refresh explicite côté repo perimeter (à chaque écriture sur les tables concernées) + sanity check en début de pipeline.**
- **Plusieurs périmètres ?** Aujourd'hui le projet a 2 périmètres (`uca`, `apc`). La table matérialisée prévoit le multi-perimeter dès le départ.
- **Quand attaquer ?** Pas avant la fin du chantier M2M (`DATA_jointures-many-to-many.md`) — `perimeter_structures` matérialisée s'intègre mieux quand `authorship_structures` est en place (JOIN naturel via FK). Donc post-Phase 2+3 du M2M.
