# Normaliser les relations many-to-many cachées (arrays + JSONB de jointure)

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
| `person_name_forms.persons jsonb` (`{"<person_id>": ["<source>", ...]}`) | Table `person_name_form_persons (name_form_id, person_id, sources text[])` avec FK `ON DELETE CASCADE` |

Pour `person_name_form_persons`, le `sources text[]` reste justifié : la liste des sources où la forme a été observée pour cette personne est une donnée de la relation, sans cardinalité forte (1-6 valeurs dans un enum fixe). C'est l'élément JSONB clé/valeur (`person_id → list[source]`) qui pose problème, pas le détail "sources observées".

### Garder l'array sur `perimeters`

Volume trivial (2 perimeters, < 10 ids au total). La complexité d'une table de jointure ne se justifie pas. Un id mort y est inoffensif (on JOIN sur `structures(id)` dans les requêtes, les ids morts sont silencieusement filtrés).

### Suppression complète des colonnes après migration

Pas de conservation d'un "cache dénormalisé" (colonne `structure_ids` qui resterait à côté de la table de jointure). Sinon on retombe sur le problème de divergence qu'on essaie de résoudre. Toutes les queries qui consomment ces colonnes doivent être adaptées pour utiliser la table de jointure.

## Phasage

### Phase 1 — `person_name_form_persons` (le plus simple)

- Volume le plus petit (50 K liens).
- Moins de call-sites à adapter (alimentation : `populate_person_name_forms.py` ; consommation : matching de personnes dans `create_persons_from_source_authorships.py` et requêtes admin).
- Sert de POC pour valider l'approche avant d'attaquer les deux tables plus lourdes.

Migration :
- Créer `person_name_form_persons` avec FK `ON DELETE CASCADE` des deux côtés.
- Backfill : `INSERT INTO person_name_form_persons SELECT id, (k)::int, COALESCE(persons->>k, '[]'::jsonb)::jsonb::... FROM person_name_forms, jsonb_object_keys(persons) k`.
- Adapter le code (queries + populate + matching).
- Drop `person_name_forms.persons`.
- Le CHECK `persons_not_empty` disparaît (remplacé par une contrainte applicative ou un trigger qui supprime la name_form si plus aucun lien — à décider).

### Phase 2 — `authorship_structures` (volume modéré)

- 196 K liens, 151 K rows source.
- Adaptation des call-sites lecture (filtres `:sid = ANY(structure_ids)` → JOIN), écriture (`build_authorships` qui propage in_perimeter et structure_ids).
- Drop colonne après migration.

### Phase 3 — `source_authorship_structures` (le plus gros)

- 338 K liens, 8.1 M rows source (mais 2 % seulement avec structure_ids).
- Plus de call-sites adaptés : `populate_affiliations` (alimentation), tous les filtres affiliation côté API.
- Drop colonne après migration.

## Bénéfices attendus

- **FK natives** sur les 3 relations → la cascade `delete_structure` ou `delete_person` devient automatique. Plus de risque d'id mort, plus besoin du purge applicatif actuel.
- **Requêtes plus naturelles** : `JOIN authorship_structures USING (authorship_id)` au lieu de `WHERE :sid = ANY(structure_ids)`. Plans Postgres plus lisibles.
- **Introspection BI possible** : Metabase/Superset peuvent suivre les relations comme des FK normales.
- **Cohérence avec le reste du schéma** : tu as déjà `source_authorship_addresses`, `structure_relations`, `address_structures` — toutes des tables de jointure normales. Sortir les 3 cas restants harmonise.

## Questions ouvertes

- **`person_name_form_persons.sources`** : on garde en `text[]` ou on normalise en `(name_form_id, person_id, source)` à 3 colonnes ? Si la cardinalité reste bornée (1-6, valeurs dans un enum), `text[]` est OK. Si on veut suivre individuellement chaque observation (date, run pipeline…), 3 colonnes serait nécessaire. À trancher au démarrage de la Phase 1.
- **Stratégie de migration zéro-downtime** ? Probablement non nécessaire (mono-utilisateur), mais à confirmer si la DSI a une politique de fenêtres de maintenance.
- **Phase 2 et 3 fusionnables ?** Les deux tables `authorships` et `source_authorships` partagent une logique de propagation (`build_authorships.propagate_perimeter_and_structures_from`). Migrer les deux en même temps pourrait être plus simple que séquentiel — à voir au démarrage.
- **Coût d'adaptation** estimé à 1 semaine de travail concentré pour les 3 phases. À affiner après audit des call-sites au démarrage.

## Court terme (déjà fait)

En attendant ce chantier, le service `application/structures.py:delete_structure` purge déjà manuellement les `structure_ids[]` via `repo.purge_structure_id_from_arrays(structure_id)` (commit où cette fiche a été créée). Cela ferme la fenêtre de bug immédiate. Une fois ce chantier abouti et les FK en place, la méthode `purge_structure_id_from_arrays` disparaîtra (la cascade DB fait le job).
