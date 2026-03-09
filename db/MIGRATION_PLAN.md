# Plan de migration — Schéma v1 → v2

## Vue d'ensemble

La migration se fait en 3 phases :

1. **Phase DDL** : créer les nouvelles tables, modifier les existantes, renommer
2. **Phase DATA** : peupler les nouvelles tables depuis le staging et les données existantes
3. **Phase CLEANUP** : supprimer les anciennes tables devenues inutiles

Les phases DDL et CLEANUP sont des migrations SQL. La phase DATA nécessite des
scripts Python (re-normalisation du staging, transfert de mappings).


## Phase 1 — DDL (migrations SQL)

### Migration 014a : Créer les nouvelles tables vides

Aucune dépendance complexe — toutes les tables référencées (structures, persons,
publications, staging_*) existent déjà.

Tables à créer :
- `person_identifiers`
- `hal_authors`
- `hal_documents`
- `hal_authorships`
- `openalex_institutions`
- `openalex_authors`
- `openalex_documents`
- `openalex_authorships`
- `authorships`
- `address_structures` (nouveau nom, nouveau schéma)
- `openalex_authorship_addresses`

### Migration 014b : Modifier les tables existantes

1. **hal_structures** : changement de PK
   - Ajouter colonne `id SERIAL`
   - Supprimer la contrainte PK sur `hal_struct_id`
   - Ajouter PK sur `id`
   - Ajouter UNIQUE sur `hal_struct_id`
   - Ajouter `NOT NULL` sur `hal_struct_id`
   - (Aucune FK externe ne pointe vers hal_structures, donc pas de cascade)

2. **structures** : nettoyer les reliquats
   - `DROP COLUMN laboratory_id` (FK vers l'ancienne table laboratories)

3. **structure_relations** : assouplir le type
   - `ALTER COLUMN relation_type TYPE TEXT` (l'ENUM relation_type est trop rigide)

4. **publications** : simplifier
   - `DROP COLUMN is_validated`

5. **addresses** : harmoniser avec le schéma cible
   - `RENAME COLUMN raw_text_normalized TO normalized_text`
   - `ADD COLUMN country TEXT`
   - (conserver `is_uca` et `resolved_at` temporairement — ils seront nettoyés en phase 3)

6. **authors** → **legacy_authors**
   - `ALTER TABLE authors RENAME TO legacy_authors`
   - Renommer les index et contraintes associés


## Phase 2 — DATA (scripts Python)

L'ordre est important : chaque script peut dépendre des résultats du précédent.

### Étape 2.1 : Re-normaliser HAL

Script : `migrate_hal.py`

Lit `staging_hal` et peuple :
- `hal_documents` (un par halid, avec `collections TEXT[]`, lien `staging_id`)
- `hal_authors` (un par `hal_person_id`, avec idhal et orcid observés)
- `hal_authorships` (un par document×auteur, avec `hal_struct_ids[]`)
- Résout `is_uca` et `structure_id` sur les authorships (via `hal_structures.structure_id`)

Pour le lien `hal_documents.publication_id` : au choix, on peut soit réutiliser
les publications existantes (matching par DOI ou halid via publication_sources),
soit les recréer. Réutiliser est préférable pour ne pas perdre les données
enrichies (journal_id, oa_status, etc.).

### Étape 2.2 : Re-normaliser OpenAlex

Script : `migrate_openalex.py`

Lit `staging_openalex` et peuple :
- `openalex_documents`
- `openalex_authors`
- `openalex_authorships`
- `openalex_institutions` (extraites des authorships)
- Résout `is_uca` et `structure_id` sur les authorships

Même logique que HAL pour le lien `publication_id`.

### Étape 2.3 : Transférer les mappings person_id

Script : `migrate_person_links.py`

Transfère les `person_id` de `legacy_authors` vers `hal_authors` et
`openalex_authors` en utilisant les identifiants communs :

```sql
-- HAL : via idhal
UPDATE hal_authors ha
SET person_id = la.person_id
FROM legacy_authors la
WHERE la.person_id IS NOT NULL
  AND la.idhal IS NOT NULL
  AND ha.idhal = la.idhal;

-- HAL : via orcid
UPDATE hal_authors ha
SET person_id = la.person_id
FROM legacy_authors la
WHERE ha.person_id IS NULL
  AND la.person_id IS NOT NULL
  AND la.orcid IS NOT NULL
  AND ha.orcid = la.orcid;

-- OpenAlex : via openalex_id
UPDATE openalex_authors oa
SET person_id = la.person_id
FROM legacy_authors la
WHERE la.person_id IS NOT NULL
  AND la.openalex_id IS NOT NULL
  AND oa.openalex_id = la.openalex_id;

-- OpenAlex : via orcid
UPDATE openalex_authors oa
SET person_id = la.person_id
FROM legacy_authors la
WHERE oa.person_id IS NULL
  AND la.person_id IS NOT NULL
  AND la.orcid IS NOT NULL
  AND oa.orcid = la.orcid;
```

Rapport : combien de mappings transférés, combien perdus (legacy_authors avec
person_id mais sans correspondance dans les nouvelles tables).

### Étape 2.4 : Peupler person_identifiers

Script : `migrate_person_identifiers.py`

Collecte les ORCID et idHAL depuis :
- `hal_authors` ayant un `person_id` résolu
- `openalex_authors` ayant un `person_id` résolu
- Tout ORCID/idHAL connu dans les exports RH

```sql
-- ORCID depuis hal_authors
INSERT INTO person_identifiers (person_id, id_type, id_value, source)
SELECT DISTINCT person_id, 'orcid', orcid, 'hal'
FROM hal_authors
WHERE person_id IS NOT NULL AND orcid IS NOT NULL
ON CONFLICT (id_type, id_value) DO NOTHING;

-- idHAL depuis hal_authors
INSERT INTO person_identifiers (person_id, id_type, id_value, source)
SELECT DISTINCT person_id, 'idhal', idhal, 'hal'
FROM hal_authors
WHERE person_id IS NOT NULL AND idhal IS NOT NULL
ON CONFLICT (id_type, id_value) DO NOTHING;

-- ORCID depuis openalex_authors
INSERT INTO person_identifiers (person_id, id_type, id_value, source)
SELECT DISTINCT person_id, 'orcid', orcid, 'openalex'
FROM openalex_authors
WHERE person_id IS NOT NULL AND orcid IS NOT NULL
ON CONFLICT (id_type, id_value) DO NOTHING;
```

### Étape 2.5 : Déduplication publications

Script : `migrate_deduplicate.py`

Relie `hal_documents` et `openalex_documents` aux `publications` existantes :

1. Par DOI :
   ```sql
   UPDATE hal_documents hd SET publication_id = p.id
   FROM publications p WHERE hd.doi = p.doi AND hd.doi IS NOT NULL;
   ```

2. Par source_id (via l'ancienne table publication_sources) :
   ```sql
   UPDATE hal_documents hd SET publication_id = ps.publication_id
   FROM publication_sources ps
   WHERE ps.source = 'hal' AND ps.source_id = hd.halid
     AND hd.publication_id IS NULL;
   ```

3. Idem pour openalex_documents.

Rapport : combien de documents reliés, combien orphelins.

### Étape 2.6 : Construire authorships (vérité)

Script : `migrate_authorships.py`

Combine les authorships source pour construire la table de vérité :

```sql
-- Depuis HAL
INSERT INTO authorships (publication_id, person_id, structure_id, author_position,
                         is_uca, source_hal)
SELECT hd.publication_id, ha_auth.person_id, has.structure_id, has.author_position,
       has.is_uca, TRUE
FROM hal_authorships has
JOIN hal_documents hd ON hd.id = has.hal_document_id
JOIN hal_authors ha_auth ON ha_auth.id = has.hal_author_id
WHERE hd.publication_id IS NOT NULL
  AND has.excluded = FALSE
ON CONFLICT (publication_id, person_id, structure_id) DO UPDATE
  SET source_hal = TRUE;

-- Depuis OpenAlex (même logique)
INSERT INTO authorships (publication_id, person_id, structure_id, author_position,
                         is_uca, source_openalex)
SELECT od.publication_id, oa_auth.person_id, oas.structure_id, oas.author_position,
       oas.is_uca, TRUE
FROM openalex_authorships oas
JOIN openalex_documents od ON od.id = oas.openalex_document_id
JOIN openalex_authors oa_auth ON oa_auth.id = oas.openalex_author_id
WHERE od.publication_id IS NOT NULL
  AND oas.excluded = FALSE
ON CONFLICT (publication_id, person_id, structure_id) DO UPDATE
  SET source_openalex = TRUE;
```

### Étape 2.7 : Migrer les tables d'adresses

Script : `migrate_addresses.py`

1. `address_laboratories` → `address_structures` :
   ```sql
   INSERT INTO address_structures (address_id, structure_id, matched_form_id, is_confirmed)
   SELECT al.address_id, al.structure_id, al.matched_form_id,
          al.is_valid
   FROM address_laboratories al
   WHERE al.structure_id IS NOT NULL;
   ```
   (Les anciens `laboratory_id` doivent être convertis en `structure_id` ;
   si `address_laboratories` a déjà un `structure_id` depuis migration_008, l'utiliser.)

2. `publication_author_addresses` → `openalex_authorship_addresses` :
   Nécessite de retrouver le `openalex_authorship_id` correspondant à chaque
   ancien `publication_author_id`. Jointure via l'auteur OpenAlex et le document.


## Phase 3 — CLEANUP (migration SQL)

### Migration 015 : Supprimer les anciennes tables et créer la vue

```sql
-- Supprimer les vues qui référencent les anciennes tables
DROP VIEW IF EXISTS v_publications_full;
DROP VIEW IF EXISTS v_stats_labo_publisher;
DROP VIEW IF EXISTS v_stats_labo_journal;

-- Supprimer les anciennes tables (ordre : respecter les FK)
DROP TABLE IF EXISTS publication_author_addresses;
DROP TABLE IF EXISTS address_laboratories;
DROP TABLE IF EXISTS publication_authors;
DROP TABLE IF EXISTS publication_sources;
DROP TABLE IF EXISTS legacy_authors;
DROP TABLE IF EXISTS confusing_forms;
DROP TABLE IF EXISTS laboratories;

-- Nettoyer les colonnes temporaires sur addresses
ALTER TABLE addresses DROP COLUMN IF EXISTS is_uca;
ALTER TABLE addresses DROP COLUMN IF EXISTS resolved_at;

-- Supprimer les types ENUM obsolètes
DROP TYPE IF EXISTS relation_type;

-- Créer la vue publication_sources
CREATE VIEW publication_sources AS
    SELECT publication_id, 'hal'::source_type AS source, halid AS source_id
    FROM hal_documents WHERE publication_id IS NOT NULL
    UNION ALL
    SELECT publication_id, 'openalex'::source_type AS source, openalex_id AS source_id
    FROM openalex_documents WHERE publication_id IS NOT NULL;
```


## Résumé de l'ordre d'exécution

```
 1. psql -f migration_014a_create_new_tables.sql
 2. psql -f migration_014b_modify_existing_tables.sql
 3. python3 migrate_hal.py
 4. python3 migrate_openalex.py
 5. python3 migrate_person_links.py
 6. python3 migrate_person_identifiers.py
 7. python3 migrate_deduplicate.py
 8. python3 migrate_authorships.py
 9. python3 migrate_addresses.py
10. psql -f migration_015_cleanup.sql
```

Étapes 3-4 sont les plus lourdes (re-normalisation complète du staging).
Étapes 5-9 sont relativement rapides (SQL pur ou presque).
Étape 10 est irréversible — s'assurer que tout est correct avant.


## Points d'attention

- **Sauvegarder la base** avant de commencer (pg_dump)
- **Les étapes 2.1-2.2** réécrivent les scripts normalize_hal.py et normalize_openalex.py
  pour écrire dans les nouvelles tables au lieu des anciennes. C'est le gros du travail.
- **L'étape 2.3** est critique : c'est là qu'on récupère le travail de curation
  (mappings person_id). Vérifier les stats avant/après.
- **L'étape 2.5** doit préserver les publications existantes (journal_id, oa_status enrichis).
- **L'étape 2.7** (adresses) peut être complexe car les FK changent de cible.
  Si trop compliqué, on peut reconstruire les adresses from scratch (elles sont
  re-dérivables du staging OpenAlex).
