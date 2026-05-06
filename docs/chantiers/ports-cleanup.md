# Chantier — Nettoyage des ports `domain/ports/`

## État : à exécuter

Audit fait, règle actée dans `docs/architecture.md`. Reste à corriger
deux ports qui ne respectent pas cette règle. Plus une décision
pragmatique à confirmer sur un troisième.

## Pour l'instance Claude qui exécute ce chantier

Tu n'as pas le contexte de la session qui a produit ce chantier.
Lis cette fiche en entier avant de commencer. Lis aussi la section
"Règle de placement des ports" dans `docs/architecture.md` qui a été
ajoutée dans la même session : c'est la règle que ce chantier
applique.

Tu peux faire les 3 issues dans n'importe quel ordre — elles sont
indépendantes. Commit séparé par issue (rollback granulaire).

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

## Issue 2 (DÉCISION À CONFIRMER) — `config_repository` mélange Config + Perimeter

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

### Décision retenue : **option β — garder le mélange, le documenter**

Raisonnement : les deux concepts sont étroitement liés en pratique
(les valeurs de config référencent souvent un perimeter par son
`code`), et scinder créerait deux ports utilisés systématiquement
ensemble. Coût/bénéfice défavorable.

### Action (option β retenue)

1. **Mettre à jour le docstring du fichier**
   `domain/ports/config_repository.py` pour expliciter le mélange :

   ```python
   """Port AsyncConfigRepository — contrat d'accès à l'agrégat
   Perimeter et à la table config (clé/valeur applicative).

   Mélange pragmatique assumé : la table `config` n'est pas un
   agrégat au sens DDD strict (c'est de la configuration en
   clé/valeur), mais ses entrées référencent souvent un perimeter
   par code, et les deux sont manipulés ensemble par les routers
   admin `/api/config` et `/api/perimeters`. Scinder créerait deux
   ports systématiquement utilisés conjointement.

   Voir `docs/architecture.md` (section "Règle de placement des
   ports", paragraphe "Exceptions assumées") pour le contexte
   complet.

   Implémenté par infrastructure/repositories/async_config_repository.py.
   """
   ```

2. **Aucune modification de code** au-delà du docstring.

### Option alternative non retenue : α — scinder

Si plus tard la décision est reprise, l'option α consisterait à :
- Créer `domain/ports/perimeter_repository.py` avec les méthodes
  Perimeter
- Garder `config_repository.py` ou le déplacer en
  `application/ports/config_queries.py` (selon vue)
- Créer `infrastructure/repositories/perimeter_repository.py`
- Adapter `application/config.py` pour utiliser deux ports
- Adapter les routers `/api/config` et `/api/perimeters`

C'est ~1h-2h de travail au lieu de 5 min pour β. **Ne pas faire α**
sauf demande explicite ultérieure.

### Validation

- Le docstring doit refléter le contenu réel du port et pointer
  vers `docs/architecture.md`.
- Aucun test ne doit casser (pas de modification de code).

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
