# Chantier — Nettoyage des ports `domain/ports/`
Commencé et terminé le 2026-05-06

## État : terminé

Issues 1 et 2 exécutées. Issue 3 confirmée sans action (exception
documentée dans `docs/architecture.md`). Voir l'historique git pour
les commits de mise en œuvre.

## Contexte

Le projet suit DDD-lite avec ports/adapters. Les ports sont répartis
entre `domain/ports/` (agrégats métier) et `application/ports/`
(orchestration). Une règle des 3 critères a été figée dans
`docs/architecture.md` :

1. Le port représente la persistance d'un **agrégat** du domaine.
2. **Signature ne référence que des types domain/stdlib/primitifs**.
3. Méthodes nommées en termes **métier**, pas techniques.

Audit complet effectué :

| Port | Critère 1 | Critère 2 | Critère 3 | Verdict |
|---|---|---|---|---|
| `person_repository` | ✓ | ✓ | ✓ | **OK** |
| `publication_repository` | ✓ | ✓ (importe `PubByDoi` etc.) | ✓ | **OK** |
| `authorship_repository` | ✓ | ✓ | ✓ | **OK** |
| `journal_repository` | ✓ | ✓ (`fields: dict`) | ✓ | **OK** |
| `publisher_repository` | ✓ | ✓ (`fields: dict`) | ✓ | **OK** |
| `address_repository` | ✓ | ✓ | ✓ | **OK** (avec exception cross-aggregate assumée) |
| `structure_repository` | ✓ | **✗** | partiel | **À CORRIGER (Issue 1)** |
| `config_repository` | ⚠ mélange Config + Perimeter | ✓ | ⚠ partie config = clé/valeur | **Décision pragmatique (Issue 2)** |

`address_repository` a des méthodes de propagation cross-aggregate
(touchent `publications.countries`) — pattern accepté, exception
documentée dans `docs/architecture.md`. Pas d'action.

---

## Issue 1 (OBLIGATOIRE) — `structure_repository` expose des fragments SQL

### Problème

Dans `domain/ports/structure_repository.py`, deux méthodes ont une
signature qui viole le critère 2 :

```python
async def update_structure_fields(
    self,
    structure_id: int,
    sql_fragments: list[str],
    params: list,
) -> dict: ...

async def update_name_form_fields(
    self,
    form_id: int,
    sql_fragments: list[str],
    params: list,
) -> dict: ...
```

`sql_fragments` et `params` exposent des fragments SQL bruts dans le
contrat du port. Conséquence : l'appelant (couche `application/`)
doit savoir construire des morceaux de SQL pour invoquer le port,
ce qui contredit l'isolation DDD.

Pour comparer : `journal_repository.update_journal_fields` et
`publisher_repository.update_publisher_fields` utilisent un dict
typé (`fields: dict`) — c'est le pattern propre à reproduire.

### Action

Refactorer les deux méthodes pour qu'elles prennent `fields: dict`
au lieu de `(sql_fragments, params)`. La construction SQL passe côté
implémentation, dans `infrastructure/repositories/`.

Étapes précises :

1. **Modifier `domain/ports/structure_repository.py`** :
   - Remplacer la signature de `update_structure_fields` (sync) par :
     ```python
     def update_structure_fields(
         self,
         structure_id: int,
         fields: dict,
     ) -> dict: ...
     ```
   - Idem pour `update_structure_fields` async (`AsyncStructureRepository`).
   - Idem pour `update_name_form_fields` (sync et async).

2. **Modifier `infrastructure/repositories/structure_repository.py`**
   (sync) et `infrastructure/repositories/async_structure_repository.py`
   (async) : adapter les implémentations pour accepter `fields: dict`.
   Construire le SQL en interne (à la manière de
   `update_journal_fields` dans `journal_repository.py` qu'on peut
   prendre comme modèle).

3. **Mettre à jour les call sites dans `application/structures.py`** :
   ces sites construisaient probablement aujourd'hui les
   `sql_fragments` et `params` à passer au repo. Maintenant ils
   passent juste un `dict` des champs à mettre à jour.
   - Localiser : `grep -rn "sql_fragments" application/`
   - Adapter chaque appel pour passer un `dict` au lieu des deux
     listes.

4. **Vérifier les autres call sites possibles** :
   - `grep -rn "update_structure_fields\|update_name_form_fields" .`
   - Adapter si nécessaire (routers, scripts CLI).

5. **Lancer les tests** :
   - `python -m pytest tests/ -v` (tous, pour vérifier non-régression)
   - Particulièrement
     `tests/integration/application/test_structures_service.py`
     et `tests/integration/interfaces/test_structures_api.py`

6. **Commit** avec message du genre :
   `domain/ports/structure_repository : refactor update_*_fields pour accepter dict (suppression fuite SQL dans le contrat)`

### Validation

Après la modification :
- `grep -n "sql_fragments" domain/ports/structure_repository.py` doit
  ne rien retourner.
- Les tests `test_structures_*` doivent passer.
- Le linter import-linter doit passer (`lint-imports`).
- `mypy` doit passer.

---

## Issue 2 (OBLIGATOIRE) — `config_repository` mélange Config + Perimeter

### Problème

`domain/ports/config_repository.py` couvre deux choses distinctes :

- Méthodes **config** (clé/valeur applicative, n'est pas un
  agrégat métier au sens strict) :
  - `config_key_exists`
  - `update_config_value`
  - `config_keys_referencing_perimeter`
- Méthodes **Perimeter** (agrégat métier) :
  - `add_structure_to_perimeter`, `remove_structure_from_perimeter`
  - `perimeter_exists`, `perimeter_code_exists`
  - `create_perimeter`, `update_perimeter_fields`
  - `get_perimeter_code`, `delete_perimeter`

Le mélange est historique : les deux sont manipulés ensemble par les
routers admin `/api/config` et `/api/perimeters`.

### Décision retenue : **option α — scinder**

Raisonnement : `Perimeter` est un agrégat métier au sens strict
(entité racine identifiable, invariants propres) ; il a sa place dans
`domain/ports/`. La table `config` est de la configuration applicative
clé/valeur — pas un agrégat — et a sa place dans `application/ports/`
(query service, `cur: Any` accepté). Le mélange historique brouille
la frontière de placement énoncée dans `docs/architecture.md`.
Scinder clarifie la sémantique : les deux ports peuvent être injectés
en parallèle dans les call sites qui en ont besoin.

### Action (option α retenue)

1. **Créer `domain/ports/perimeter_repository.py`** avec les méthodes
   Perimeter (version async, suivre le pattern des autres ports
   `domain/ports/`). Aucune référence à `cur`, signatures uniquement
   en types domaine/stdlib/primitifs.

2. **Créer `application/ports/config.py`** (query service) avec les
   méthodes config restantes : `config_key_exists`,
   `update_config_value`, `config_keys_referencing_perimeter`.
   `cur: Any` accepté ici puisqu'on est côté `application/ports/`.

3. **Supprimer `domain/ports/config_repository.py`** une fois les
   call sites migrés.

4. **Créer `infrastructure/repositories/async_perimeter_repository.py`**
   qui implémente le nouveau port Perimeter.

5. **Adapter `infrastructure/repositories/async_config_repository.py`**
   pour ne garder que la partie config (ou la déplacer en
   `infrastructure/db/queries/config.py` selon le pattern habituel
   des adapters de `application/ports/`).

6. **Adapter `application/config.py`** : injecter les deux ports
   (`AsyncPerimeterRepository` + query service `Config`).

7. **Adapter les routers `/api/config` et `/api/perimeters`** :
   factories de dépendances FastAPI pour les deux ports.

8. **Mettre à jour `docs/architecture.md`** : retirer
   `config_repository` de la liste des "Exceptions assumées" (la
   règle des 3 critères s'applique sans exception après ce
   chantier).

9. **Lancer les tests** : `pytest tests/integration/application/test_config_service.py` + tests des routers admin/config et admin/perimeters.

### Validation

- `domain/ports/config_repository.py` n'existe plus.
- `domain/ports/perimeter_repository.py` ne contient que des
  méthodes Perimeter (pas de `config_*`).
- `application/ports/config.py` ne contient que des méthodes config.
- `lint-imports`, `mypy`, et la suite de tests passent.

---

## Issue 3 (DÉJÀ ASSUMÉE) — `address_repository` propagation cross-aggregate

### Status

**Pas d'action requise.** L'exception est documentée dans
`docs/architecture.md` (section "Règle de placement des ports",
paragraphe "Exceptions assumées").

### Contexte (pour mémoire)

`address_repository` expose des méthodes qui touchent
`publications.countries` (ex.
`refresh_publications_countries_for_addresses(address_ids)`). Strictement
parlant, c'est l'agrégat Publication qui est modifié, mais la
modification est déclenchée par un changement sur Address.

Pattern DDD acceptable quand les agrégats sont étroitement liés et
que la propagation fait partie de la cohérence métier. Ne pas
"corriger" cette exception sans discussion préalable.

---

## Hors scope de ce chantier

- **Ne pas toucher** au layout `application/ports/*`. L'audit a
  vérifié que tous les ports `application/ports/` sont bien placés
  (query services orchestrationnels, `cur: Any` dans signatures,
  méthodes liées à des phases pipeline). Particulièrement :
  - `perimeter` (application/ports/) : query service de lecture,
    cohabite légitimement avec la partie Perimeter du repo
    `domain/ports/config_repository.py`.
  - `subjects` (application/ports/) : dominante orchestration
    (bulk operations, recompute), reste OK.
- **Ne pas démarrer le chantier sync/async** (autre fiche :
  `docs/chantiers/sync-async-deduplication.md`). Ce chantier-ci
  garde les deux variantes sync et async des ports.
- **Ne pas réécrire `domain/ports/*`** au-delà des deux corrections
  listées. Tous les autres ports sont OK.
- **Ne pas déplacer de fichiers** entre `domain/ports/` et
  `application/ports/`. L'audit a montré qu'aucun déplacement n'est
  nécessaire.

---

## Sequencing recommandé

1. Issue 1 (refactoring `structure_repository`) — chantier réel,
   ~30 min, tests à faire tourner.
2. Issue 2 (docstring `config_repository`) — quelques minutes.
3. Mettre à jour la checklist Phase 1 dans
   `docs/chantiers/audit-cto.md` (item "Position des ports" → cocher
   avec pointeur vers ce chantier comme exécuté).

Commits séparés.

---

## Lien avec les autres chantiers

- `docs/chantiers/audit-cto.md` : ce chantier clôt l'item Phase 1
  "Position des ports".
- `docs/chantiers/sync-async-deduplication.md` : indépendant. Si ce
  chantier-là est exécuté APRÈS celui-ci, les ports async seront
  supprimés mais la règle des 3 critères reste valide pour les ports
  sync restants.
