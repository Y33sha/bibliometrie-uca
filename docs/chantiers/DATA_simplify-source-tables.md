# Chantier — Simplification des tables sources

Commencé le 2026-05-12.

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

1. **`source_persons` supprimée**. Distinction sémantique fondatrice
   à respecter :
   - **`source_authorships.person_identifiers`** (JSONB, à renommer
     depuis `identifiers`) = observation par-authorship des
     identifiants vus sur cette signature spécifique. Cible naturelle
     du transfert depuis `source_persons` (tables à supprimer).
   - **`person_identifiers`** (table) = référentiel canonique
     personne, alimenté par promotion via le pipeline personnes
     (`add_identifiers_from_authorships`). **Pas la cible du transfert
     depuis source_persons** — ce serait court-circuiter la voie
     canonique.
   - Types d'identifiants côté `person_identifiers` : 4 au total
     (`orcid`, `idhal`, `idref`, `hal_person_id`), avec
     `hal_person_id` interne (jamais visible UI). Deux constantes
     dans `domain/persons/identifiers.py` :
     - `PERSON_IDENTIFIER_TYPES = ("orcid", "idhal", "idref", "hal_person_id")` :
       liste complète, utilisée par `add_identifiers_from_authorships`
       pour la promotion canonique.
     - `PUBLIC_PERSON_IDENTIFIER_TYPES = ("orcid", "idhal", "idref")` :
       sous-ensemble visible UI, utilisée par les filtres SQL côté
       `detail.py`/`list.py` et la validation API d'ajout.
   - Pas de risque qu'un utilisateur crée un `hal_person_id` à la
     main : la route d'ajout (`application/persons.py:237` +
     `interfaces/api/routers/persons.py:313`) valide contre
     `PUBLIC_PERSON_IDENTIFIER_TYPES`.
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

## Phasage

### Phase 1 — Préalable schéma

- [x] Migration Alembic : `ADD COLUMN source_structures ARRAY[TEXT]`
  et `ADD COLUMN countries ARRAY[CHAR(2)]` sur `source_authorships`
  (nullable, sans default).

### Phase 2 — Scripts one-shot de peuplement

- [x] `interfaces/cli/maintenance/migrate_source_structures.py` :
  - peuple `source_authorships.source_structures` en faisant
    `array_agg(ss.source_id ORDER BY ss.source_id)` via la jointure
    `source_struct_ids → source_structures.id`.
  - peuple `source_authorships.countries` (sa HAL uniquement) en
    faisant `array_agg(DISTINCT ss.country ORDER BY ss.country)` via
    la même jointure.
  - idempotent (skip si déjà rempli).
- [x] `interfaces/cli/maintenance/migrate_source_persons_to_authorships.py`
  *(à écrire seulement si l'audit confirme que des
  `source_authorships` manquent l'info présente dans
  `source_persons`)* :
  - `UPDATE source_authorships sa SET person_identifiers = jsonb_strip_nulls(coalesce(sa.person_identifiers, '{}') || jsonb_build_object(...))
     FROM source_persons sp WHERE sa.source_person_id = sp.id`
  - Champs à merger : `idhal` (depuis `sp.source_ids->>'idhal'`),
    `idref` (depuis `sp.idref`), `hal_person_id` (depuis
    `sp.source_ids->>'hal_person_id'`, filtré `> 0`), `orcid`
    (depuis `sp.orcid`).
  - Idempotent par construction (`||` JSONB ne crée pas de doublon ;
    `jsonb_strip_nulls` éclate les `null` introduits par
    `jsonb_build_object` quand la valeur source est absente).
  - **Audit préalable obligatoire** : compter les
    `source_authorships` qui ont une `source_persons` rattachée mais
    auxquelles il manque l'info dans `person_identifiers` JSONB.

### Phase 3 — Refactor code

#### Lectures : passer de `source_persons` à `sa.person_identifiers` / `person_identifiers`

- [x] `infrastructure/db/queries/persons/create.py:fetch_unlinked_authorships` :
  JOIN sur `source_persons` retiré ; lecture orcid/idref/idhal/hal_person_id
  depuis `sa.person_identifiers` JSONB directement.
- [x] `infrastructure/db/queries/persons/create.py:fetch_hal_account_to_person_map` :
  **supprimé** (avec la phase `step0_hal_accounts` du pipeline persons).
  Un matching par idhal / hal_person_id sera réintroduit dans le chantier
  `METIER_decide-person-match`.
- [x] `infrastructure/db/queries/countries.py:refresh_hal_source_countries` :
  **supprimé** (circuit vestige passant par `source_structures.country`,
  devenu redondant maintenant que HAL alimente `source_authorship_addresses`
  comme les autres sources). Remplacé par
  `refresh_sa_countries_for_source(source)` batché par source.
- [x] `infrastructure/db/queries/persons/detail.py` :
  filtre `id_type = ANY(:public_id_types)` ajouté sur les 2 agrégats JSONB
  exposés (via la constante `PUBLIC_PERSON_IDENTIFIER_TYPES` dans
  `domain/persons/identifiers.py`).
- [x] `infrastructure/db/queries/hal_problems.py:hal_duplicate_accounts` :
  groupe désormais par `(sa.person_id, sa.person_identifiers->>'hal_person_id')`
  via une CTE 2-niveaux (1ʳᵉ : 1 row par compte HAL avec
  `MIN(raw_author_name/orcid/idhal/idref)` agrégé + `pub_count` ;
  2ᵉ : `HAVING COUNT(*) >= 2` pour filtrer les personnes à comptes
  multiples). `source_persons` n'est plus interrogé. Modèle Pydantic
  `HalAccountSummary` enrichi avec `idref` ; affichage Svelte
  correspondant ajouté ; types TS régénérés via `npm run types:gen`.
- [x] `infrastructure/db/queries/persons/detail.py:hal_rows` :
  reconstruction de la vue « comptes HAL » depuis `source_authorships`
  agrégés par `hal_person_id` (`MIN()` arbitraire mais déterministe
  sur les champs descriptifs, même justification que `hal_problems`).
  `source_persons` n'est plus joint. Champ `id` retourné devient
  `MIN(sa.id)` (au lieu de `source_persons.id`) — sans impact UI,
  l'onglet « Identités » qui exploitait ce champ est désactivé (cf.
  TODO `interfaces/frontend/src/routes/persons/[id]/+page.svelte:420`).
- [x] `interfaces/cli/maintenance/merge_person_duplicates_by_lab.py` :
  comptage `hal_authors` via `COUNT(DISTINCT sa.person_identifiers->>'hal_person_id')`
  (et plus `COUNT(DISTINCT source_person_id)`). Filtre `IS NOT NULL`
  ajouté pour rester aligné sur les comptes HAL effectifs.

#### Dual-writes vers `source_persons` à supprimer

- [x] `infrastructure/repositories/person_repository/_authorships.py:link_authorship` :
  dual-write `source_persons` supprimé. Paramètres `source_person_id`
  et `has_hal_person_id` retirés de la signature (cascade :
  `_authorships.py` → adapter `PgPersonRepository.link_authorship` →
  port `domain/ports/person_repository.py:link_authorship` →
  service `application/persons.py:link_authorship` + `link_authorships`).
- [x] `infrastructure/repositories/person_repository/_identifiers.py:add_identifier` :
  dual-write `UPDATE source_persons SET person_id = :pid WHERE
  source_ids->>'idhal' = :iv` supprimé (déclenchait quand un idHAL
  était ajouté à une personne). Docstring nettoyée du side-effect.
- [x] `infrastructure/repositories/person_repository/_core.py:merge_into` :
  propagation `UPDATE source_persons SET person_id = :t WHERE
  person_id = :s` supprimée de la séquence de fusion (étape 1 du
  merge). Docstring mise à jour (passe de 7 à 6 tables touchées par
  la fusion).

#### Normalizers : arrêter UPSERT `source_persons` + `source_structures`

- [x] `application/pipeline/normalize/normalize_hal.py` :
  - Écriture de `sa.source_structures` (TEXT[]) avec les `halId_s`
    natifs (parsés depuis `authIdHasPrimaryStructure_fs` /
    `authIdHasStructure_fs`).
  - Plus d'UPSERT vers `source_structures` ni `source_persons`. Plus
    de cache structures préchargé (les noms sont parsés localement
    au document pour alimenter les adresses).
  - `source_person_id` toujours NULL pour HAL (comme OA/WoS/CrossRef
    depuis le chantier source_persons précédent). Identifiants
    personne sur `sa.person_identifiers` JSONB via `compact_identifiers`.
  - Fonctions supprimées côté query service : `upsert_hal_source_person`,
    `upsert_hal_source_structure`, `fetch_hal_source_structure_ids`,
    `fetch_hal_source_structures_for_cache`. Signature de
    `upsert_hal_source_authorship` mise à jour (kwarg `source_structures`
    au lieu de `source_struct_ids`, plus de `source_person_id`).
  - Tests adaptés : unit `parse_author_structures` (set[int] →
    set[str]), suppression test intégration sur fonction supprimée.
- [x] `application/pipeline/normalize/normalize_openalex.py` et
  `normalize_wos.py` : arrêt UPSERT `source_structures` ;
  écriture des `openalex_id` natifs (OA) ou des noms d'institutions
  (WoS) directement dans `sa.source_structures` (TEXT[]). Fonctions
  query supprimées : `find/upsert_openalex_source_structure`,
  `upsert_wos_source_structure`, `fetch_wos_source_structures`. Le
  cache module-level `_wos_institution_cache` n'a plus de raison
  d'exister.
- [x] `application/pipeline/normalize/normalize_scanr.py` /
  `normalize_theses.py` : arrêt UPSERT vers `source_persons` (les deux
  sources écrivaient via `upsert_*_source_person_by_idref/ppn`).
  `source_authorships.source_person_id` toujours NULL — les
  identifiants (idref, ppn, orcid) sont déjà portés par
  `sa.person_identifiers` JSONB. Fonctions query supprimées :
  `upsert_scanr_source_person_by_idref`,
  `upsert_theses_source_person_by_ppn`. La règle
  `domain/persons/creation.py:should_create_source_person` n'ayant
  plus de caller, supprimée également (avec ses tests unitaires).

#### Cleanup MetaData + SQL inline (Phase 3 finale, sans DDL)

Le pipeline n'étant pas relancé entre les commits, on peut casser
temporairement les normalizers — le SQL et la MetaData seront
réalignés avant que la migration finale touche la DB.

- [x] Cleanup tactique : docstring port `person_repository.py` +
  `_ORPHAN_BASE` (admin.py) — sous-requête morte sur
  `source_person_id` retirée.
- [x] `infrastructure/db/tables.py` : MetaData alignée sur l'état
  post-DROP. Colonnes `source_person_id` et `source_struct_ids`
  retirées de `source_authorships`, UNIQUE bascule de
  `(source_publication_id, source_person_id, author_position)`
  vers `(source_publication_id, author_position)` (nom
  `source_authorships_pub_pos_key`). Index `idx_sa_source_person`
  et `idx_sa_orphan_perimeter` supprimés. Tables `source_persons`
  et `source_structures` retirées.
- [x] Normalizers SQL — bascule des `ON CONFLICT (source_publication_id,
  source_person_id, author_position)` vers `(source_publication_id,
  author_position)` dans les 6 normalizers (HAL, OpenAlex, WoS, ScanR,
  theses, Crossref).
- [x] Normalizers SQL — retrait de `source_person_id` de la liste des
  colonnes insérées dans les 6 normalizers (la valeur était déjà NULL
  en dur).

### Phase 4 — Migration finale + tests

- [x] Migration Alembic autogenerated (un seul fichier) :
  - `DROP COLUMN source_authorships.source_person_id`
  - `DROP COLUMN source_authorships.source_struct_ids`
  - `DROP CONSTRAINT source_authorships_pub_person_pos_key`
  - `ADD CONSTRAINT source_authorships_pub_pos_key (source_publication_id, author_position)`
  - `DROP INDEX idx_sa_source_person`
  - `DROP INDEX idx_sa_orphan_perimeter`
  - `DROP TABLE source_persons`
  - `DROP TABLE source_structures`
- [x] `alembic upgrade head` (par l'utilisatrice).
- [x] `python -m infrastructure.db.dump_schema` pour rafraîchir
  `schema.sql`.
- [x] Whitelists `count_*_table` (normalize_openalex, normalize_theses)
  amputées de `source_persons` / `source_structures` + `summary_stats`
  des normalizers OA/Theses raccourcies en conséquence.
- [x] `tests/integration/infrastructure/db/queries/test_countries.py` :
  classe `TestRefreshHalSourceCountries` retirée (fonction supprimée
  Phase 3), helpers `_create_sp` / `_create_source_structure` retirés,
  `_create_sa` adapté (plus de `source_person_id` ni `source_struct_ids`).
- [x] Refactor des 13 fichiers de tests d'intégration restants qui
  référencent encore `source_persons` / `source_structures` /
  `source_person_id` / `source_struct_ids` (~75 occurrences) : fixtures,
  helpers et assertions à adapter.
- [x] Suite complète `tests/integration/` verte.
- [ ] Vérification volume : `source_authorships` ne doit pas
  exploser (la duplication `source_structures: ARRAY[TEXT]` +
  `countries: ARRAY[CHAR(2)]` est estimée < 2 % de la taille
  actuelle de la table). *À faire sur la vraie base.*

## Lien avec les autres chantiers

- `2026-04-28_source-persons.md` : a déjà allégé `source_persons`
  côté écritures (CrossRef/OA/WoS n'écrivent plus). Ce chantier-ci
  pousse la logique à son terme — suppression complète.
