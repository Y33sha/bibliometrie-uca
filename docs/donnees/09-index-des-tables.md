# Index des tables

*À jour le 2026-10-12.*

## Vue macro

Vue globale du modèle : l'ingestion par source en haut, les référentiels consolidés au centre, et les satellites rattachés à leur entité-pivot. Seules les tables principales y figurent ; l'index ci-dessous est exhaustif.

```mermaid
flowchart TB
    subgraph ingestion["Ingestion — tables sources (par source)"]
        staging --> source_publications --> source_authorships
        source_authorships --> source_authorship_addresses --> addresses
    end

    subgraph publishing["Revues & éditeurs"]
        journals --> publishers
    end

    subgraph canon["Référentiel consolidé"]
        publications
        authorships
        structures
        persons
    end

    source_publications -->|match / create| publications
    source_authorships -->|match / create| persons
    source_authorships --> authorships
    authorships --> publications
    authorships --> persons
    authorships -.->|via matview authorship_structures| structures
    addresses --> address_structures --> structures
    source_publications --- publishing
    publications --- publishing

    subgraph satP["Satellites publication"]
        publications_detail
        subjects
        publication_relations
    end
    subgraph satS["Structures & périmètre"]
        structure_name_forms
        structure_tutelles
        perimeters --> perimeter_structures
    end
    subgraph satN["Satellites personne"]
        person_identifiers
        person_name_forms
        persons_rh
    end

    publications --- satP
    structures --- satS
    persons --- satN
```

## Index alphabétique

Les vues et vues matérialisées sont signalées comme telles.

| Objet | Description | Schéma |
|---|---|---|
| `address_structures` | liaison adresse ↔ structure (avec confirmation) | [structures](06-structures.md) |
| `addresses` | adresses normalisées issues des signatures | [structures](06-structures.md) |
| `alembic_version` | révision de schéma appliquée — technique | `public` |
| `apc_payments` | frais de publication (import CSV) | [publishing](04-publishing.md) |
| `audit_log` | journal des événements (actions admin, fusions) — technique | [ops](07-ref-et-ops.md) |
| `author_identifying_keys` | attributs d'identité d'une signature source (nom normalisé, identifiants), partagés via `identity_id` | [sources](02-sources.md) |
| `authorship_structures` | *vue matérialisée* : structures liées à une authorship | [publications](03-publications.md) |
| `authorships` | table consolidée personne × publication | [publications](03-publications.md) |
| `candidate_dois` | *vue* : DOI des publications du périmètre, lus par le rattrapage par DOI et la résolution des agences d'enregistrement | [sources](02-sources.md) |
| `config` | réglages d'exploitation du pipeline (périmètres actifs, années couvertes…) | [ops](07-ref-et-ops.md) |
| `confirmed_authorships` | épinglages admin (must-link) signature source ↔ personne, réappliqués à chaque exécution | [persons](05-persons.md) |
| `countries` | référentiel des pays | [ref](07-ref-et-ops.md) |
| `distinct_persons` | paires marquées distinctes malgré un nom commun | [persons](05-persons.md) |
| `doi_prefixes` | cache préfixe DOI → agence + éditeur | [publishing](04-publishing.md) |
| `failed_lookups` | identifiants cherchés en vain dans une source, avec la date de la prochaine tentative | [sources](02-sources.md) |
| `journal_doi_namespaces` | espaces de noms DOI qui désignent une revue | [publishing](04-publishing.md) |
| `journal_issns` | ISSN des revues | [publishing](04-publishing.md) |
| `journal_name_forms` | formes de noms pour reconnaître une revue | [publishing](04-publishing.md) |
| `journals` | référentiel des revues | [publishing](04-publishing.md) |
| `language_forms` | formes sous lesquelles les sources désignent une langue | [ref](07-ref-et-ops.md) |
| `languages` | référentiel des langues | [ref](07-ref-et-ops.md) |
| `monographs` | livres et volumes d'actes de congrès | [publishing](04-publishing.md) |
| `perimeter_structures` | appartenance au périmètre, recalculée par le pipeline | [structures](06-structures.md) |
| `perimeters` | définition des périmètres | [structures](06-structures.md) |
| `person_identifiers` | identifiants persistants (ORCID, idHAL, IdRef) | [persons](05-persons.md) |
| `person_name_forms` | formes de noms pour reconnaître une personne | [persons](05-persons.md) |
| `persons` | référentiel des personnes du périmètre | [persons](05-persons.md) |
| `persons_rh` | satellite des données RH (import CSV) | [persons](05-persons.md) |
| `pipeline_phase_executions` | historique d'exécution des phases — technique | [ops](07-ref-et-ops.md) |
| `place_name_forms` | formes de noms pour la détection des pays | [ref](07-ref-et-ops.md) |
| `publication_relations` | relations sémantiques entre publications | [publications](03-publications.md) |
| `publication_structures` | *vue matérialisée* : structures d'une publication | [publications](03-publications.md) |
| `publication_subjects` | liaison publication ↔ sujet | [publications](03-publications.md) |
| `publications` | référentiel consolidé des productions | [publications](03-publications.md) |
| `publications_detail` | satellite 1:1 (abstract, keywords, topics, biblio) | [publications](03-publications.md) |
| `publisher_name_forms` | formes de noms pour reconnaître un éditeur | [publishing](04-publishing.md) |
| `publishers` | référentiel des éditeurs | [publishing](04-publishing.md) |
| `rejected_authorships` | rejets manuels de paires personne × publication | [persons](05-persons.md) |
| `ror_dump_imports` | imports du dump ROR | [ref](07-ref-et-ops.md) |
| `ror_organizations` | organisations du Research Organization Registry | [ref](07-ref-et-ops.md) |
| `ror_relations` | relations parent/enfant entre organisations ROR | [ref](07-ref-et-ops.md) |
| `source_authorship_addresses` | liaison authorship source ↔ adresse | [sources](02-sources.md) |
| `source_authorship_rors` | ROR attribués par la source à une signature, rattachés à l'adresse de leur affiliation | [sources](02-sources.md) |
| `source_authorship_structures` | *vue matérialisée* : affiliations résolues d'un authorship source | [sources](02-sources.md) |
| `source_authorships` | contribution d'un auteur source à un document source | [sources](02-sources.md) |
| `source_publications` | un enregistrement par document par source | [sources](02-sources.md) |
| `staging` | ingestion brute par source, payload vidé après normalisation | [sources](02-sources.md) |
| `structure_name_forms` | formes de noms pour la détection des structures | [structures](06-structures.md) |
| `structure_tutelles` | rattachement hiérarchique entre structures | [structures](06-structures.md) |
| `structures` | référentiel institutionnel | [structures](06-structures.md) |
| `subject_cooccurrences` | *vue matérialisée* : paires de sujets co-présents | [publications](03-publications.md) |
| `subjects` | référentiel des sujets / mots-clés | [publications](03-publications.md) |
