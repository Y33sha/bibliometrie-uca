# Chantier — Normalisation du schéma `person_name_forms`

Commencé le 2026-05-13.

## Contexte

Schéma actuel : `person_name_forms(name_form, person_ids integer[], sources text[])`
— deux arrays parallèles non-corrélés. Pour une forme liée à plusieurs
personnes via plusieurs sources, on ne sait pas quel `(person_id, source)`
est responsable de quoi.

Exemple problématique : forme `"j dupont"` reliée à person 1 (Jérôme
Dupont) via `persons` et à person 2 (Jeanne Dupont-Martin) via `openalex`
— finit avec `person_ids=[1,2], sources=['persons','openalex']`, zéro
moyen de tracer `1↔persons` et `2↔openalex` sans recalculer depuis les
sources.

C'est cette faiblesse qui justifie la **recalculation systématique batch**
dans `populate_person_name_forms` : on ne peut pas faire d'update
incrémental (`source_authorships` modifié → mise à jour ciblée de la
contribution correspondante) parce qu'on ne sait pas quelles contributions
viennent de qui.

### Mesures du volume actuel (2026-05-13)

| Métrique | Valeur |
|---|---|
| Lignes totales | 54 679 |
| Taille (heap + index) | 18 MB |
| % de formes mono-person (`array_length(person_ids,1) = 1`) | 97.63 % |
| % de formes poly-person (2-5 person_ids) | 2.37 % |
| Distribution des sources par forme | 1 à 6, moyenne 1.78 |

Le couplage `(person_id, source)` n'est ambigu que sur ~1 300 formes ;
pour 53 381 formes (97.6 %), le couplage est trivial (1 seul person_id).

### Options structurelles considérées

- **Table de liaison** `(name_form, person_id, sources text[])`,
  FK sur `person_id`, UNIQUE composite. +1 table, ~56k rows, queries SQL
  standards, FK possible. La colonne `source` reste un array car il n'y
  a pas de table `sources` qui justifierait de la sortir en row-per-source
  (la valeur est juste un libellé, pas un agrégat FK).
- **JSONB sur la table existante** : remplacer `person_ids[] + sources[]`
  par une seule colonne `persons jsonb` au format `{ "<person_id>":
  ["src1", "src2"], ... }`. Pas de table ajoutée, suppression d'une
  colonne, 1 row par name_form (54k inchangé). Pas de FK (mais pas de
  perte vs aujourd'hui : impossible sur arrays).

## Décisions

1. **Option JSONB retenue**. Pour ce besoin précis (volume modeste,
   queries d'écriture peu fréquentes, 97.6 % de cas singleton), la
   simplicité du schéma l'emporte sur l'orthodoxie relationnelle. Si à
   l'usage la table de liaison devient préférable (queries `formes pour
   personne X` fréquentes, besoin de FK, etc.), le coût de transition
   sera limité — les deux schémas portent la même information.

2. **Format de la colonne `persons jsonb`** :
   ```json
   { "<person_id>": ["<source1>", "<source2>", ...], ... }
   ```
   Clés = `person_id` sérialisé en string (contrainte JSON). Valeurs =
   array de noms de sources distinctes et triées (pour stabilité des
   diffs et des hashes). NOT NULL ; objet vide `{}` interdit (cleanup
   automatique des rows orphelines, comme aujourd'hui pour
   `person_ids = '{}'`).

3. **Pas de FK sur `person_id`**. Statu quo vs aujourd'hui. La cohérence
   est garantie par le code applicatif (refresh_name_forms à la
   création/renommage d'une personne, propagation explicite des merges).

4. **Index GIN sur `persons`** (`USING gin (persons jsonb_path_ops)`)
   pour supporter les queries `WHERE persons ? '<person_id>'` (lookup
   admin "formes pour personne X").

5. **Comportement à conserver** : la phase `populate_person_name_forms`
   reste **batch full-recompute** dans le cadre de ce chantier. Le passage
   à un mode incrémental (delete authorship → suppression ciblée de sa
   contribution) est un suivi possible une fois la nouvelle structure
   en place. Ce qui est *déverrouillé* par le chantier, c'est la
   *possibilité* de l'incrémental ; ce qui est *fait*, c'est la
   normalisation du modèle.

6. **Helpers domaine pour manipuler la colonne**. Centraliser dans
   `domain/persons/name_forms.py` les fonctions pures de manipulation
   du dict `persons` (ex. `add_person_source`, `remove_person_source`,
   `merge`, `is_ambiguous`) — pour éviter que la connaissance du format
   se répande en SQL inline et en jsonb_set partout. Le SQL ne fait que
   l'aller-retour avec ces structures pures.

## Phasage

### Phase 1 — Préalable schéma

- [x] Migration Alembic 1 : `ADD COLUMN persons jsonb` sur
  `person_name_forms` (nullable, sans default).

### Phase 2 — Backfill (oneshots additifs)

Le backfill ne copie pas naïvement les deux arrays parallèles (qui ne
donneraient pas la corrélation `(person_id, source)`) : il reconstruit
`persons` depuis les sources de vérité, étape par étape. À chaque étape
on **ajoute** des sources aux entrées `person_id`, sans jamais écraser
ce qui a déjà été posé.

Implémentation possible : un script unique
`interfaces/cli/oneshot/backfill_name_forms_persons.py` avec
sous-commandes (`--step keys|persons|authorships|cleanup`), ou
plusieurs scripts dédiés. Chaque étape doit être idempotente.

- [x] **Étape `keys`** : pour chaque row existante de `person_name_forms`,
  initialiser `persons` à `{ "<pid>": [] }` pour chaque `pid` du tableau
  `person_ids`. Aucune source posée à ce stade — c'est juste l'armature
  des clés.
- [x] **Étape `persons`** : pour chaque personne (table `persons`,
  inclut `rejected = TRUE` — cf. justification dans
  `fetch_persons_names`), calculer les `compute_person_name_forms(ln, fn)`
  et ajouter `"persons"` au tableau `sources` de chaque entrée
  `(name_form, person_id)` correspondante dans `persons`. Si la clé
  `person_id` n'existe pas encore dans `persons` pour cette form,
  l'ajouter avec `sources = ["persons"]`.
- [x] **Étape `authorships`** : pour chaque `source_authorships` non
  exclus avec `person_id IS NOT NULL` et `author_name_normalized
  IS NOT NULL`, ajouter `sa.source` au tableau `sources` de l'entrée
  `(author_name_normalized, sa.person_id)` dans `persons`. Même règle
  que l'étape précédente pour les clés inexistantes.
- [x] **Étape `cleanup`** : pour chaque row, retirer les clés
  `person_id` dont le tableau `sources` est resté vide après les
  étapes précédentes (orphelins du modèle ancien — ces person_ids
  étaient dans `person_ids[]` mais n'ont aucune justification dans les
  sources actuelles). Si après ce nettoyage `persons = '{}'`, supprimer
  la row. *Run sur la base : 0 clé retirée, 0 row supprimée.*

### Phase 3 — Helpers domaine

- [x] `domain/persons/name_forms.py` : fonctions pures sur le dict
  `dict[str, list[str]]` représentant `persons`.
  - `add_person_source(persons, person_id, source) -> dict`
  - `remove_person_source(persons, person_id, source) -> dict`
  - `remove_person(persons, person_id) -> dict`
  - `merge(persons_a, persons_b) -> dict` (union par clé, sources
    triées et dédupliquées)
  - `is_ambiguous(persons) -> bool` (>1 clé)
  - `person_ids(persons) -> list[int]`, `all_sources(persons) -> list[str]`
- [x] Tests unit pour ces helpers (cas singleton, multi-person,
  conflit de sources, ordre).

### Phase 4 — Refactor producteurs

NOT NULL sur `person_ids` levé par migration 0006 (pour que les
nouveaux writers puissent ne pas la renseigner). Phases 4 et 5 faites
dans le même commit : sans Phase 5, les readers anciens verraient
`person_ids` NULL sur les rows écrites par les nouveaux writers.

- [x] Migration Alembic 0006 : `ALTER COLUMN person_ids DROP NOT NULL`.
- [x] `infrastructure/db/queries/name_forms.py` :
  - `fetch_existing_name_forms` retourne `persons jsonb`.
  - `update_name_form(form_id, persons)` et `insert_name_form(name_form,
    persons)` (renommé depuis `_with_merge`) prennent un
    `dict[str, list[str]]` ; la fusion est faite côté Python par
    l'orchestrateur (qui a déjà la donnée en mémoire), pas en SQL.
  - `fetch_normalized_forms_from_temp` retourne des triplets
    `(name_form, person_id, source)` distincts (au lieu d'agréger en
    arrays parallèles) ; l'agrégation par forme en dict `persons` se
    fait en Python via les helpers domaine.
  - `delete_name_form` inchangé.
- [x] `application/ports/name_forms.py` : signatures alignées.
- [x] `application/pipeline/persons/populate_person_name_forms.py` :
  agrégation des triplets via `add_person_source` en dict `persons`,
  diff insert/update/delete inchangé structurellement.
- [x] `infrastructure/repositories/person_repository/_name_forms.py` :
  - `refresh_name_forms` : retire la source `'persons'` du couple
    `(pid, "persons")` dans chaque row où elle apparaît (drop de clé
    si plus aucune source, drop de row si plus aucune clé), puis pose
    les nouvelles formes via `add_name_form`.
  - `add_name_form` : INSERT … ON CONFLICT DO UPDATE avec `jsonb_set`
    qui unionne les sources de la clé `pid` côté SQL (caller hors
    orchestrateur, pas de pré-chargement en mémoire).
  - `detach_name_form` : `persons - pid` puis DELETE si vide.
- [x] `infrastructure/repositories/person_repository/_core.py:merge_into`
  : remplacement de l'UPDATE sur `person_ids` par un select-update
  Python qui transfère les sources de `source_id` vers `target_id` via
  le helper domaine `merge`.

### Phase 5 — Refactor consommateurs

- [x] `infrastructure/db/queries/persons/create.py:fetch_name_form_map` :
  person_id extraits via `jsonb_object_keys(persons)::int`.
- [x] `infrastructure/db/queries/persons/admin.py:name_form_authorships`
  (lookup "autres personnes attachées à cette forme") : `LATERAL
  jsonb_object_keys(pnf.persons) AS pid_text` + cast `pid_text::int`.
- [x] `infrastructure/db/queries/persons/list.py` (agrégat `name_forms`
  par personne) :
  - `ambiguous` = `COUNT(*) > 1` sur `jsonb_object_keys(pnf.persons)`.
  - Source des person_id : `LATERAL jsonb_object_keys(pnf.persons)`.
  - `sources` exposé au frontend = union triée des sources de toutes
    les clés (form-level, compat avec `NameFormSummaryOut`).
  - Filtre d'exposition : forme exposée ssi au moins une clé a une
    source ≠ 'persons' (sous-requête `jsonb_each` +
    `jsonb_array_elements_text`).

### Phase 6 — Migration finale + tests

À ce stade, tous les writers posent `persons` (Phase 4) et tous les
readers lisent `persons` (Phase 5). On peut verrouiller la colonne et
supprimer les anciennes.

- [x] Migration Alembic 0007 : NOT NULL + CHECK persons_not_empty +
  GIN `idx_pnf_persons_gin` (`jsonb_path_ops`) + DROP `person_ids` +
  DROP `sources`.
- [x] `alembic upgrade head` (par l'utilisatrice).
- [x] `python -m infrastructure.db.dump_schema` — `schema.sql`
  rafraîchi.
- [x] `tests/integration/interfaces/test_persons_api.py:_seed_name_form`
  passé sur `INSERT INTO person_name_forms (name_form, persons)`.
- [x] Fix `detach_name_form` : DELETE-puis-UPDATE (et pas l'inverse)
  pour ne pas violer le CHECK `persons_not_empty` sur l'état
  intermédiaire `{}`.
- [x] Suite complète `tests/integration/` verte (813 tests).
- [x] `docs/donnees.md` : description de `person_name_forms` mise à
  jour, lien chantier retiré de la section « Évolutions prévues ».

## Lien avec les autres chantiers

- `2026-05-13_DATA_simplify-source-tables.md` : a établi le pattern
  d'ajout de colonne JSONB sur table existante
  (`source_authorships.person_identifiers`) avec migration en deux
  temps (add column → backfill → refactor producteurs/consommateurs →
  contraintes/drop). Même approche ici.
- `METIER_decide-person-match.md` : ré-introduira un matching par
  idhal / hal_person_id côté pipeline persons ; il consommera
  potentiellement `person_name_forms` mais sans connaissance du format
  interne grâce aux helpers domaine.
- **Suivi possible** : passage à un mode incrémental
  (`source_authorships` modifié/excluded → mise à jour ciblée de la
  contribution dans `persons`). Hors scope de ce chantier ; possible
  une fois la structure jsonb en place.
