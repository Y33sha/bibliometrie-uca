# Chantier — Simplification des tables sources

Commencé le 2026-05-11.

## Contexte

Les tables sources (`source_publications`, `source_authorships`,
`source_persons`, `source_structures`) reproduisent par mimétisme le
schéma des tables canoniques (entités publication, personne,
structure + pivot authorship). Cette symétrie est délibérée côté
canonique mais largement superflue côté source : la dimension
canonique est portée directement par `source_authorships.person_id`
et `source_authorships.structure_ids`, et la résolution des liens
canoniques se fait via les adresses, pas via les tables `source_persons`
et `source_structures`.

Audit (cf. discussion architecturale 2026-05-11) :
- `source_persons` : 4 usages réels, tous résolubles autrement (cf
  plan ci-dessous).
- `source_structures` : 1 usage réel (propagation pays HAL), facile
  à déplacer.

→ Suppression des deux tables, migration des données utiles vers
`person_identifiers` (côté persons) et nouvelles colonnes
`source_authorships.source_structures` et
`source_authorships.countries` (côté structures).

## Décisions

1. **`source_persons` supprimée**. Identifiants fiables (`idhal`,
   `idref`) migrés vers `person_identifiers` (id_types déjà
   existants). `hal_person_id` **non migré** : assume la perte du
   matching par hal_person_id pour les comptes HAL sans idhal, le
   fallback nom-match prendra le relais.
2. **`source_structures` supprimée**. Pour HAL, le `country` côté
   structure est migré sur `source_authorships.countries` (ARRAY de
   codes pays par sa). Pour les autres sources, l'info `country` du
   normalizer était inscrite dans `source_structures.country` mais
   **jamais lue** (filtre `WHERE source='hal'` côté pipeline pays) ;
   suppression pure, l'info `country` reste accessible via
   `addresses.countries` pour OA/WoS/ScanR.
3. **`source_authorships.source_struct_ids` → `source_structures`** :
   renommage et changement de type (ARRAY[INTEGER] vers les PK de
   `source_structures` → ARRAY[TEXT] avec les IDs internes des
   sources : numérique HAL, "I****" OpenAlex, etc.). Traçabilité
   source préservée.
4. **`source_authorships.source_person_id` supprimée**. Tous les
   usages (dual-write, propagation fusion) disparaissent avec
   `source_persons`.

## Hors scope

- **Harmonisation cross-source du flux pays**. Le pattern actuel
  est asymétrique : HAL pose le pays au niveau structure, OA/WoS/ScanR
  au niveau adresse. Une vraie harmonisation impliquerait soit de
  créer des « adresses virtuelles » HAL, soit de tout passer par
  `source_authorships.countries`. À réfléchir séparément.

## Phasage

### Phase 1 — Préalable schéma

- [ ] Migration Alembic : `ADD COLUMN source_structures ARRAY[TEXT]`
  et `ADD COLUMN countries ARRAY[CHAR(2)]` sur `source_authorships`
  (nullable, sans default).

### Phase 2 — Scripts one-shot de peuplement

- [ ] `interfaces/cli/maintenance/migrate_source_structures.py` :
  - peuple `source_authorships.source_structures` en faisant
    `array_agg(ss.source_id ORDER BY ss.source_id)` via la jointure
    `source_struct_ids → source_structures.id`.
  - peuple `source_authorships.countries` (sa HAL uniquement) en
    faisant `array_agg(DISTINCT ss.country ORDER BY ss.country)` via
    la même jointure.
  - idempotent (skip si déjà rempli).
- [ ] `interfaces/cli/maintenance/migrate_source_persons_identifiers.py` :
  - `INSERT INTO person_identifiers (person_id, id_type, id_value, status)`
    pour chaque `(sp.person_id, 'idhal', sp.source_ids->>'idhal')`
    et `(sp.person_id, 'idref', sp.idref)` non-NULL.
  - `ON CONFLICT DO NOTHING` (skip si déjà connu).
  - Lancement via `python -m interfaces.cli.maintenance.migrate_source_persons_identifiers`.

### Phase 3 — Refactor code

- [ ] `application/pipeline/normalize/normalize_hal.py` : écrire
  directement `source_authorships.countries` et
  `source_authorships.source_structures` (avec les `halId_s` des
  structures référencées) ; arrêter d'UPSERT dans `source_structures`
  et `source_persons`.
- [ ] `application/pipeline/normalize/normalize_openalex.py` /
  `normalize_wos.py` / `normalize_scanr.py` / `normalize_theses.py` :
  arrêter d'UPSERT dans `source_persons` et `source_structures`.
  Écrire le `source_id` de la structure côté
  `source_authorships.source_structures` (TEXT).
- [ ] `infrastructure/db/queries/countries.py:refresh_hal_source_countries` :
  refactor pour lire `source_authorships.countries` au lieu de la
  jointure via `source_structures`.
- [ ] `infrastructure/db/queries/hal_problems.py` : refactor des
  requêtes de doublons HAL pour grouper sur
  `source_authorships.identifiers->>'idhal'` (ou sur
  `(person_id, identifiers->>'hal_person_id')` si on conserve la
  capacité de détecter les doublons par hal_person_id pour les
  comptes sans idhal, à confirmer).
- [ ] `infrastructure/db/queries/persons/create.py:fetch_hal_account_to_person_map` :
  refactor pour interroger `person_identifiers` (id_type='idhal')
  au lieu de `source_persons`.
- [ ] `infrastructure/db/queries/persons/create.py:fetch_unlinked_authorships` :
  retirer le JOIN sur `source_persons` ; lire orcid/idref/idhal
  depuis `source_authorships.identifiers` JSONB directement.
- [ ] `infrastructure/repositories/person_repository/_authorships.py:link_authorship` :
  supprimer le dual-write `source_persons`.
- [ ] `infrastructure/repositories/person_repository/_identifiers.py:add_identifier` :
  supprimer le dual-write `source_persons`.
- [ ] `infrastructure/repositories/person_repository/_core.py:merge_into` :
  supprimer la propagation `UPDATE source_persons`.
- [ ] `infrastructure/db/queries/persons/detail.py:hal_rows` :
  refactor pour reconstruire la vue "comptes HAL" depuis
  `source_authorships` agrégés.
- [ ] `interfaces/cli/maintenance/merge_person_duplicates_by_lab.py` :
  remplacer `COUNT(DISTINCT source_person_id)` par
  `COUNT(DISTINCT identifiers->>'idhal')` ou similaire.
- [ ] Mettre à jour `infrastructure/db/tables.py` (MetaData SA).
- [ ] Mettre à jour les ports `domain/ports/person_repository.py`
  (méthodes éventuelles concernant `source_persons`).

### Phase 4 — Tests + suppression schéma

- [ ] Suite complète `pytest tests/ -v`.
- [ ] Migration Alembic finale : `DROP COLUMN source_struct_ids`,
  `DROP COLUMN source_person_id` sur `source_authorships` ;
  `DROP TABLE source_structures` ; `DROP TABLE source_persons`.
- [ ] `python -m infrastructure.db.dump_schema` pour rafraîchir
  `schema.sql`.
- [ ] Vérification volume : `source_authorships` ne doit pas
  exploser (la duplication `source_structures: ARRAY[TEXT]` +
  `countries: ARRAY[CHAR(2)]` est estimée < 2 % de la taille
  actuelle de la table).

## Lien avec les autres chantiers

- `2026-04-28_source-persons.md` : a déjà allégé `source_persons`
  côté écritures (CrossRef/OA/WoS n'écrivent plus). Ce chantier-ci
  pousse la logique à son terme — suppression complète.
- `2026-05-11_alembic-adoption.md` : ce chantier utilise Alembic
  pour les migrations (ADD/DROP COLUMN, DROP TABLE).
