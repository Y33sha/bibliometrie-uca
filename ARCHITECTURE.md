# Architecture des données — Bibliométrie UCA v2

## Vue d'ensemble

Le système gère les publications scientifiques de l'Université Clermont Auvergne en
intégrant plusieurs sources de données (HAL, OpenAlex, Web of Science).

Principe fondamental : **les données source ne se mélangent jamais**. Chaque source
a ses propres tables ; les entités canoniques (publications, personnes, structures,
authorships) sont construites par déduplication et mapping.

```
 STAGING (brut API)                SOURCE (normalisé)                     VÉRITÉ
 ──────────────────               ─────────────────────                  ────────

 staging_hal ──────────→ hal_documents ──────────────────────────┐
                         hal_authors ─────────────────────┐      ├──→ publications
                         hal_authorships                  │      │
                         hal_structures ──────────┐       ├──→ persons ←── person_identifiers
                                                  │       │      │
                                                  ├──→ structures │
                                                  │       │      ├──→ authorships
 staging_openalex ─────→ openalex_documents ──────────────┘      │
                         openalex_authors ────────────┘          │
                         openalex_authorships ───────────────────┘
                         openalex_institutions ───┘
```


## Principes de conception

### 1. Séparation stricte des sources

Chaque source possède ses propres tables pour les entités clés :

| Entité     | HAL                | OpenAlex                | Vérité         |
|------------|--------------------|-------------------------|----------------|
| Documents  | `hal_documents`    | `openalex_documents`    | `publications` |
| Auteurs    | `hal_authors`      | `openalex_authors`      | `persons`      |
| Structures | `hal_structures`   | `openalex_institutions` | `structures`   |
| Authorship | `hal_authorships`  | `openalex_authorships`  | `authorships`  |

On ne crée **jamais** d'équivalence directe entre un auteur HAL et un auteur
OpenAlex. Chacun pointe indépendamment vers `persons` via un FK `person_id`.

### 2. Clés internes systématiques

Tous les identifiants primaires sont des `SERIAL`. Les identifiants naturels
(DOI, halId, openalex_id, hal_person_id, hal_struct_id) sont en colonnes `UNIQUE`
mais ne servent jamais de PK. Cela évite les problèmes quand un identifiant naturel
est absent.

### 3. Mappings many-to-one

Les liens source → vérité sont toujours many-to-one :

- Plusieurs `hal_structures` → une `structure` (phases d'un même labo)
- Plusieurs `hal_authors` → une `person` (variantes de nom d'un même chercheur)
- Plusieurs `hal_documents` / `openalex_documents` → une `publication` (déduplication)

Le mapping inverse n'est pas garanti : un auteur-source marqué `is_reliable = FALSE`
peut recouvrir plusieurs personnes. Le `person_id` est alors laissé NULL et la
résolution se fait au niveau des authorships individuels.

### 4. Identifiants certifiants

ORCID et idHAL certifient l'unicité d'une personne. Ils sont dans
`person_identifiers` (many-to-one vers `persons`) :

- **Un identifiant donné → une seule personne** (UNIQUE sur `id_type, id_value`)
- **Une personne → potentiellement plusieurs identifiants** (comptes multiples)

Si deux auteurs-source partagent le même ORCID ou idHAL, ils correspondent à la
même personne. C'est le chaînon principal de la déduplication inter-sources.

Les ORCID et idHAL observés dans les données source sont aussi stockés sur
`hal_authors` / `openalex_authors` (données source brutes). `person_identifiers`
contient les associations vérifiées.


## Tables de vérité (détail)

### `structures`

Référentiel institutionnel maintenu manuellement. Contient l'UCA, ses laboratoires,
les tutelles (CNRS, INRAE...), composantes (INP, VetAgro Sup...), CHU, etc.

- `code` : identifiant court stable (`uca`, `cnrs`, `lpc`, `ip`)
- `type` : `universite`, `onr`, `chu`, `ecole`, `labo`, `equipe`, `site`, `autre`
- `ror_id`, `rnsr_id` : identifiants externes (optionnels)
- `hal_collection` : collection HAL associée (labos uniquement). Sert à vérifier
  si un document HAL est présent dans la collection du labo auquel il est rattaché
  (jointure `hal_documents.collections` ∩ `structures.hal_collection`).

Tables associées :
- `structure_relations` : hiérarchie (tutelles, partenariats)
- `name_forms` : formes de noms pour la détection automatique dans les affiliations

### `persons`

Référentiel des individus. Une ligne = une personne physique. Alimenté par les
exports RH (données dans la table satellite `persons_rh`) et par le script
`create_persons_from_authorships.py` (création automatique depuis les authorships
en 5 passes). Ne contient aucun identifiant bibliométrique directement — ceux-ci
sont dans `person_identifiers`.

### `persons_rh`

Table satellite liée à `persons` (FK `person_id`, ON DELETE CASCADE). Contient les
données issues des exports RH : `department_name`, `role_title`, `structure_id`,
`start_date`, `end_date`. Une personne sans entrée dans `persons_rh` n'a pas de
données RH (créée automatiquement depuis les authorships).

### `person_identifiers`

Identifiants certifiants : ORCID, idHAL, ResearcherID, etc. Chaque ligne associe
un identifiant (`id_type` + `id_value`) à une personne (`person_id`). Le champ
`source` trace la provenance (`hr`, `hal`, `openalex`, `manual`).

### `publications`

Référentiel dédupliqué. Hiérarchie de déduplication :
1. **DOI identique** → même publication
2. **Lien explicite** source→source (ex: OpenAlex cite HAL comme primary_location)
3. **Heuristique** : titre normalisé + année + type + journal identiques
   (cas éliminatoires : dates différentes, types incompatibles)

### `authorships`

Table de vérité reliant personnes, publications et structures. Construite à partir
des authorships source en résolvant les liens auteur→personne et document→publication.

- `person_id` : peut être NULL si la personne n'est pas encore identifiée
- `structure_id` : structure UCA (NULL si non UCA ou non résolu)
- `is_uca` : TRUE si l'auteur est affilié UCA sur cette publication
- `source_hal`, `source_openalex`, `source_wos`, `source_manual` : booléens traçant
  quelles sources ont contribué à cet authorship
- `excluded` : lien erroné (homonyme, etc.)

Contrainte d'unicité sur `(publication_id, person_id, structure_id)` : un même
triplet ne peut exister qu'une fois, même si plusieurs sources le confirment.

### `publishers` / `journals`

Référentiel bibliographique. Non dupliqué par source — une seule entrée par journal,
alignée par ISSN-L ou openalex_id.


## Tables source — HAL

### `staging_hal`

Import brut de l'API HAL. `raw_data` (JSONB) contient la réponse API complète.
`collection` est la collection d'origine de la requête. `processed` passe à TRUE
après normalisation. Le staging n'est jamais modifié après import (sauf
enrichissement de champs manquants).

### `hal_structures`

Référentiel des structures HAL, peuplé depuis l'API `ref/structure`.

Champs clés :
- `hal_struct_id` : identifiant numérique HAL (UNIQUE, pas PK)
- `parent_ids` : hiérarchie (tableau d'entiers → autres hal_structures)
- `alias_ids` : phases de la même structure (HAL les relie automatiquement)
- `start_date`, `end_date`, `valid` : validité temporelle
- `structure_id` (FK → `structures`) : mapping vers le référentiel. Plusieurs
  hal_structures peuvent pointer vers la même structure (phases successives).

Scripts associés :
- `populate_hal_struct_ids.py extract` : extrait les structures depuis le staging
- `enrich_hal_structures.py` : enrichit depuis l'API ref/structure
- `enrich_hal_structures.py --crawl` : remonte l'arbre des parents
- `enrich_hal_structures.py --children <id>` : liste les descendants

### `hal_authors`

Un enregistrement = un identifiant auteur dans HAL.

- `hal_person_id` : numérique HAL (de `authFullNameId_fs`), UNIQUE mais nullable
  (vieux documents)
- `idhal` : identifiant volontaire lié à un compte HAL (donnée source)
- `orcid` : ORCID observé dans HAL (donnée source)
- `is_reliable` : FALSE si cet identifiant recouvre plusieurs personnes réelles
- `person_id` : FK vers `persons` (NULL si non résolu ou non fiable)

### `hal_documents`

Un enregistrement = un document HAL.

- `halid` : identifiant HAL (UNIQUE)
- `collections` : **tableau** de collections HAL contenant ce document (un document
  peut figurer dans plusieurs collections)
- `publication_id` : FK vers la publication canonique (rempli par déduplication)

Pour vérifier si un document figure dans la collection de son labo :
```sql
SELECT hd.halid, s.hal_collection
FROM hal_authorships ha
JOIN hal_documents hd ON hd.id = ha.hal_document_id
JOIN structures s ON s.id = ANY(ha.structure_ids)
WHERE ha.is_uca = TRUE
  AND s.hal_collection IS NOT NULL
  AND NOT s.hal_collection = ANY(hd.collections);
-- → documents rattachés à un labo UCA mais absents de sa collection HAL
```

### `hal_authorships`

Relation document × auteur dans HAL.

- `hal_struct_ids` : tableau des hal_struct_id affiliés sur ce document
  (extrait de `authIdHasStructure_fs`)
- `structure_ids` : tableau des `structures.id` UCA résolues. Chaque hal_struct_id
  affilié est cherché dans `hal_structures.structure_id` ; toutes les correspondances
  trouvées sont conservées.
- `is_uca` : TRUE si `structure_ids` est non vide


## Tables source — OpenAlex

Architecture identique à HAL, adaptée aux spécificités d'OpenAlex.

### `openalex_institutions`

Pendant de `hal_structures`. `ror_id` permet l'alignement automatique avec
`structures.ror_id`.

### `openalex_authors`

Un enregistrement = un auteur OpenAlex. `is_reliable` important car OpenAlex
fusionne parfois des homonymes.

### `openalex_documents`

Même logique que `hal_documents`. Pas de champ `collections` (concept HAL).

### `openalex_authorships`

- `raw_affiliation` : affiliation brute
- `openalex_institution_ids` : institutions OpenAlex détectées


## Adresses d'affiliation

Les tables d'adresses sont **source-agnostiques**. L'adresse brute et sa
résolution en structures sont indépendantes de la source qui l'a fournie.

### `addresses`

Chaque adresse brute unique rencontrée. `review_status` : `pending`, `confirmed`,
`rejected`.

### `address_structures`

Lien adresse → structure détectée, avec traçabilité de la forme de nom qui a
déclenché la détection (`matched_form_id`). `is_confirmed` : validation manuelle.

### Tables de liaison authorship ↔ adresses

Chaque source qui fournit des adresses a sa propre table de liaison :

- `openalex_authorship_addresses` : lie un `openalex_authorships.id` à un `addresses.id`
- `wos_authorship_addresses` : à créer quand WoS sera disponible

Cela permet d'exploiter les mêmes adresses résolues quel que soit le nombre de
sources, sans duplication.


## Vue `publication_sources`

Vue (pas table) qui consolide les liens publication → source en combinant les FK
`publication_id` de `hal_documents` et `openalex_documents`. L'information étant
déjà dans les tables source, il n'y a pas besoin d'une table physique.


## Workflow de traitement

### 1. Moissonnage
```
extract_hal.py → staging_hal
extract_openalex.py → staging_openalex
extract_wos.py → staging_wos  (ou scrape_wos.py --parse-only pour fichiers manuels)
```

### 2. Enrichissement structures
```
populate_hal_struct_ids.py extract → hal_structures
enrich_hal_structures.py [--crawl] → hal_structures (enrichissement API)
populate_hal_struct_ids.py match/apply → hal_structures.structure_id
```

### 3. Normalisation
```
staging_hal → hal_documents + hal_authors + hal_authorships
staging_openalex → openalex_documents + openalex_authors + openalex_authorships
```

### 4. Déduplication publications
```
hal_documents.doi = openalex_documents.doi → même publications.id
```

### 5. Résolution personnes
Par fiabilité décroissante :
1. ORCID commun → même person_id
2. idHAL → via person_identifiers
3. Matching par nom → candidats à confirmer

### 6. Construction authorships (vérité)
```
hal_authorships + hal_authors.person_id + hal_documents.publication_id → authorships
openalex_authorships + openalex_authors.person_id + openalex_documents.publication_id → authorships
```

### 7. Curation
- Détection faux positifs (interface web `/signatures`)
- Validation authorships (`excluded = TRUE` pour les erreurs)
- Vérification présence dans les collections HAL

### 8. Complément ORCID
Moissonner les profils ORCID des personnes vérifiées pour récupérer les
publications manquantes.


## Migration depuis le schéma v1

1. **Renommer** `authors` → `legacy_authors`
2. **Créer** les nouvelles tables
3. **Peupler** les tables source depuis le staging (re-normalisation)
4. **Transférer** les `person_id` de `legacy_authors` vers `hal_authors` et
   `openalex_authors` via les identifiants communs (ORCID, idHAL, openalex_id)
5. **Reconstruire** les publications canoniques et les liens de déduplication
6. **Construire** la table `authorships` depuis les authorships source
7. **Supprimer** les anciennes tables (`legacy_authors`, `publication_authors`,
   `laboratories`, ancienne `publication_sources`)


## Inventaire des tables

### Vérité (10)
`structures`, `structure_relations`, `name_forms`, `persons`, `persons_rh`,
`person_identifiers`, `publishers`, `journals`, `publications`, `authorships`

### Source HAL (5)
`staging_hal`, `hal_structures`, `hal_authors`, `hal_documents`, `hal_authorships`

### Source OpenAlex (5)
`staging_openalex`, `openalex_institutions`, `openalex_authors`,
`openalex_documents`, `openalex_authorships`

### Adresses (3)
`addresses`, `address_structures`, `openalex_authorship_addresses`

### Source WoS (1, staging uniquement — normalisation à venir)
`staging_wos`

### Vues (1)
`publication_sources`

### Temporaire (1)
`legacy_authors` (migration)
