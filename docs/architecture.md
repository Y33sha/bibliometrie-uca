# Architecture des données — Bibliométrie UCA

## Principes de conception

Le schéma repose sur une distinction entre des tables "sources" et des tables "canoniques" (= vérité).
    - Les tables sources contiennent les *records* non dédupliqués importés depuis les API. 
    - Les tables canoniques contiennent les référentiels **publications** et **personnes** dédupliqués et mappés depuis les sources (de manière automatisée avec possibilité de curation manuelle), ainsi que le référentiel **structures** (endogène, renseigné manuellement).

```mermaid
flowchart LR
    subgraph sources
    direction LR
        source_publications---source_authorships
        source_persons---source_authorships
        source_authorships---source_structures
    end
    subgraph vérité
        direction LR
        publications---authorships
        persons---authorships
        authorships---structures
    end
    source_publications--->publications
    source_authorships--->persons
    
```

### Entités principales et relations

#### Tables sources
Les tables sources s'organisent selon un schéma en quatre tables: `source_publications`, `source_persons`, `source_authorships`, `source_structures`. Une `authorship` représente la contribution d'**un** auteur à **une** publication. C'est elle qui porte l'information d'affiliation (`structure_ids`).

```mermaid
erDiagram 
    direction LR
    Publications ||--|{ Authorships : a_pour_auteurs
    Persons ||--|{ Authorships : est_auteur_de
    Authorships }o--|{ Structures : est_affilie_a

```

Les tables sources sont toutes peuplées lors de la [phase 3](pipeline#normalize) du pipeline (`normalize`).

#### Tables “canoniques”

Les tables canoniques obéissent au même schéma et sont peuplées progressivement au cours du [pipeline](pipeline#tables-canoniques) de traitement.


## Zones fonctionnelles et propriétaires de données

Chaque table a un **service propriétaire** qui est le seul autorisé à y écrire
(INSERT/UPDATE/DELETE). Les autres composants lisent via SELECT mais passent par
le service pour écrire.

### Staging — scripts d'extraction

| Table | Propriétaire |
|-------|-------------|
| `staging` | extracteurs (`extraction/*/extract_*.py`, cross-imports) |

Table unique pour toutes les sources. Colonnes notables : `source` (enum), `source_id`, `raw_data` (JSONB, vidé après normalisation), `hal_collections` (text[], HAL uniquement), `not_found` (documents disparus).

### Sources bibliographiques — scripts de normalisation

| Table | Propriétaire |
|-------|-------------|
| `source_publications` | `processing/normalize_*.py` |
| `source_persons` | `processing/normalize_*.py` |
| `source_authorships` | `processing/normalize_*.py` |
| `source_structures` | `processing/normalize_hal.py`, `enrich_hal_structures.py` |

Note : `person_id` sur `source_authorships` est écrit par `application/persons.py` (rattachement), pas par les normaliseurs. `in_perimeter` et `structure_ids` sont écrits par `populate_affiliations.py`.

### Référentiel Publications — `application/publications.py`

| Table | Propriétaire | Notes |
|-------|-------------|-------|
| `publications` | `application/publications.py` | `refresh_from_sources()` recalcule les métadonnées depuis les source_publications |
| `distinct_publications` | API admin | paires marquées distinctes malgré titre identique |
| `apc_payments` | import APC (CSV) | — |
| `journals` | `application/journals.py` | — |
| `publishers` | `application/journals.py` | — |

### Référentiel Personnes — `application/persons.py`

| Table | Propriétaire | Notes |
|-------|-------------|-------|
| `persons` | `application/persons.py` | import RH écrit aussi (toléré) |
| `persons_rh` | import RH (CSV) | table satellite |
| `person_identifiers` | `application/persons.py` | ORCID, idHAL, IdRef |
| `person_name_forms` | `application/persons.py` | recalcul bulk par `populate_person_name_forms.py` |

### Authorships canoniques — `build_authorships.py`

| Table | Propriétaire | Notes |
|-------|-------------|-------|
| `authorships` | `build_authorships.py` + `application/authorships.py` | dédupliqué (person_id, publication_id), consolide in_perimeter et structure_ids depuis les sources |

### Structures — admin (pas de service)

| Table | Propriétaire |
|-------|-------------|
| `structures` | admin / API |
| `structure_relations` | admin / API |
| `structure_name_forms` | admin / API |
| `perimeters` | admin / API |
| `countries`, `country_name_forms` | référentiel statique |
| `config` | admin / API |

### Adresses — scripts du pipeline

| Table | Propriétaire |
|-------|-------------|
| `addresses` | `populate_addresses.py` |
| `address_structures` | `resolve_addresses.py`, admin (confirmation manuelle) |
| `source_authorship_addresses` | `populate_addresses.py` |


## Détail des tables

### Tables canoniques

#### <span id="structures"></span>Domaine fonctionnel `structures`

Référentiel institutionnel maintenu manuellement. Contient l'UCA, ses laboratoires, les co-tutelles (CNRS, INRAE...), d'autres établissements partenaires (INP, VetAgro Sup, le CHU), etc.

- `code` : identifiant court stable (`uca`, `cnrs`, `lpc`, `ip`)
- `structure_type` : `universite`, `onr`, `chu`, `ecole`, `labo`, `equipe`, `site`, `autre`
- `ror_id` : identifiant ROR
- `rnsr_id` : identifiant RNSR
- `hal_collection` : collection HAL associée
- `api_ids` : identifiants dans les sources API (OpenAlex, etc.)

```mermaid
flowchart LR
    structure_name_forms --- structures
    structure_relations --- structures
    perimeters---structures
    structures --- authorships
    authorships --- publications
    authorships --- persons
    structures ---|acronyme| apc_payments
    apc_payments ---|DOI| publications
    structures --- address_structures
    address_structures --- addresses
    
    classDef manuel  fill:#8e5,stroke:#5a3
    class structures,structure_name_forms,perimeters,structure_relations manuel;
    classDef csv fill:#fa5
    class apc_payments csv
    classDef auto fill:#adf,stroke:#58c
    class address_structures,addresses,authorships,persons,publications auto
    classDef main stroke-width:4px,font-weight:bold
    class structures,publications,persons,authorships main
```

Légende:
- **vert**: tables peuplées manuellement;
- **orange**: imports CSV;
- **bleu**: tables peuplées automatiquement par le pipeline à partir des imports API.

Tables associées :
- `perimeters` : un périmètre est un ensemble de structures, incluant récursivement les sous-structures. Actuellement deux périmètres sont définis: **UCA** et **UCA élargi** (UCA + CHU + INP). Impacte:
    - les critères d'affiliation utilisés en paramètre des requêtes API;
    - les authorships sources dont le champ `structure_ids` sera peuplé par le pipeline ([phase 5](pipeline#affiliations) du pipeline), et qui serviront à générer des `publications` et des `personnes` dans les tables canoniques.

- `structure_relations` : définit les relations entre structures. Deux relations existent: **tutelle** (asymétrique), **partenariat** (symétrique, non transitif). La relation "partenariat" est purement informative (elle réplique l'information présente dans le [référentiel ROR](glossaire#ror)); la relation "tutelle" a une conséquence sur les **structures incluses dans un périmètre** donné.
- `structure_name_forms` : formes de noms pour la détection automatique des structures dans les adresses liées aux publications. Le champ `requires_context_of` (= liste d'id structures) permet de rendre une forme de nom *conditionnellement* valide. Exemple: `LMV` reconnaît le labo *Magmas et Volcans* seulement si `uca` ou `site_clermont` reconnus dans l'adresse. Sinon: probablement *Laboratoire de mathématiques de Versailles*. Cette table est utilisée dans la phase `addresses` du [pipeline](pipeline#addresses) pour peupler la table de liaison `address_structures`.
- `address_structures`: table de liaison. Les adresses proviennent des authorships sources (phase 4 `addresses` du pipeline). Les structures identifiées sont ensuite propagées aux authorships sources.
- `apc_payments`: données provenant d'un import CSV, voir [doc sources](sources#donnees-apc).

La page [**admin/structures**](guide-utilisateur#admin-structures) permet de gérer le CRUD des structures ainsi que leurs relations et formes de noms.

La page [**admin/config**](guide-utilisateur#admin-config) permet de gérer le CRUD des périmètres et quel périmètre est pris en compte à différentes étapes du *pipeline*.

#### <span id="publications"></span>Domaine fonctionnel  `publications`

Référentiel dédupliqué. Hiérarchie de déduplication :
1. **DOI identique** (case-insensitive) → même publication (sauf cas particuliers)
2. **NNT identique** (pour les thèses)
3. **hal-id identique** (OpenAlex ou ScanR citant HAL comme source)
4. **Métadonnées** : rien en place pour l'instant, algorithme à mettre en place <!--TODO: algo de déduplication par identité de métadonnées-->
5. Interface de dédoublonnage manuel `admin/duplicates` <!--TODO: améliorer l'interface de déduplication; à terme, autoriser un user à signaler un doublon-->


```mermaid
flowchart LR
    structures --- authorships
    authorships --- publications
    authorships --- persons
    structures --- apc_payments
    apc_payments ---|DOI| publications
    source_publications-->|normalize|publications
    publications---journals
    journals---publishers
        
    classDef manuel  fill:#8e5,stroke:#5a3
    class structures,structure_name_forms,perimeters,structure_relations manuel;
    classDef csv fill:#fa5
    class apc_payments csv
    classDef auto fill:#adf,stroke:#58c
    class source_publications,publications,journals,publishers,authorships,persons auto
    classDef main stroke-width:4px,font-weight:bold
    class structures,publications,persons,authorships main

```

Tables associées:
- `journals`: référentiel des revues
- `publishers` : référentiel des éditeurs
- `apc_payments`
- `distinct_publications` (non représenté ci-dessus): Paires de publications marquées comme **distinctes malgré un titre identique**, évite de les re-suggérer dans l'interface de dédoublonnage `admin/duplicates`.

#### <span id="persons"></span>Domaine fonctionnel `persons`

Référentiel des individus. Une ligne = une personne physique. Alimenté par le script `create_persons_from_source_authorships.py` (création automatique depuis les authorships) et complété par les exports RH (données dans la table satellite `persons_rh`).

```mermaid
flowchart LR
    structures --- authorships
    
    authorships --- publications
    authorships ---- persons
    source_authorships-->persons
    persons---persons_rh
    persons---person_identifiers
    persons---person_name_forms

    classDef manuel  fill:#8e5,stroke:#5a3
    class structures,structure_name_forms,perimeters,structure_relations manuel;
    classDef csv fill:#fa5
    class persons_rh csv
    classDef auto fill:#adf,stroke:#58c
    class source_authorships,publications,person_identifiers,person_name_forms,authorships,persons auto
    classDef main stroke-width:4px,font-weight:bold
    class structures,publications,persons,authorships main


```

Tables associées :
- `persons_rh`: Table satellite liée à `persons` (FK `person_id`, ON DELETE RESTRICT). Contient les données issues des exports RH : cf [doc sources](sources#donnees-rh).
- `person_identifiers`: Identifiants persistants : ORCID, idHAL, IdRef, etc. Chaque ligne associe un identifiant (`id_type` + `id_value`) à une personne (`person_id`). Le champ `source` trace la provenance (`hal`, `openalex`, `scanr`, `theses`, `manual`, `auto`). La relation *many-to-one* permet de gérer les quelques cas d'ORCID multiples confirmés, et les nombreux cas d'identifiants (corrects ou erronés) en attente de vérification moissonnés dans les sources. 
- `person_name_forms`: Formes de noms normalisées, utilisées pour le matching lors de la création de personnes. Chaque forme pointe vers un tableau de `person_ids`. Lorsqu'une authorship source est reliée à une personne, la forme de nom est ajoutée (si absente) aux name_forms de cette personne.

#### `authorships`

Table de liaison recensant les contributions individuelles aux publications. Chaque entrée référence **1 personne**, **1 publication**, *n* structures. Construite par `build_authorships.py` à partir des *authorships* sources.

- `person_id` 
- `structure_ids`
- `in_perimeter` : TRUE si l'auteur est affilié UCA sur cette publication
- `author_position` : position dans la liste d'auteurs
- `is_corresponding` : auteur correspondant

### Tables source

Toutes les sources partagent les mêmes tables, discriminées par la colonne `source` (enum `source_type` : hal, openalex, wos, scanr, theses).

- **`source_publications`** : un enregistrement par document par source. Relié à `publications` via `publication_id` (peut être NULL si pas encore rattaché). Contient les métadonnées (doc_type non mappé, oa_status, abstract, keywords, topics, biblio, meta). Le champ `hal_collections` (text[]) est spécifique à HAL.
- **`source_persons`** : un enregistrement par auteur par source. Déduplication par `(source, source_id)`. Le `source_id` est l'identifiant interne de l'entité auteur dans la source. Porte aussi `orcid`, `idref` et `source_ids` (JSONB, identifiants propres à la source : idhal, hal_person_id, etc.).
- **`source_authorships`** : contribution d'un auteur source à un document source. Porte `person_id` (rattachement à une personne canonique), `authorship_id` (FK vers l'authorship canonique), `in_perimeter`, `structure_ids` (affiliation résolue), `raw_author_name`, `raw_affiliations` (affiliations textuelles brutes issues de la source), `roles` (auteur, directeur, rapporteur — theses.fr), `excluded` (authorship rejetée manuellement).
- **`source_structures`** : structures importées depuis HAL, OpenAlex et WoS. Mapping vers `structures` canoniques via `structure_id`. Utilisée par `populate_affiliations` pour résoudre les affiliations.

