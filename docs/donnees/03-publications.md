# Publications

Référentiel dédupliqué. Hiérarchie de déduplication :

1. **DOI identique** (case-insensitive) → même publication (sauf cas particuliers)
2. **NNT identique** (pour les thèses)
3. **hal-id identique** (OpenAlex ou ScanR citant HAL comme source)
4. **Métadonnées** : rien en place pour l'instant, algorithme à mettre en place <!--TODO: algo de déduplication par identité de métadonnées-->
5. Interface de dédoublonnage manuel `admin/duplicates` <!--TODO: améliorer l'interface de déduplication ; à terme, autoriser un user à signaler un doublon-->

```mermaid
flowchart LR
    structures --- authorships
    authorships --- publications
    authorships --- persons
    structures --- apc_payments
    apc_payments ---|DOI| publications
    source_publications-->|match_or_create|publications
    publications---|publication_subjects|subjects
    publications---journals
    journals---publishers


    classDef manuel  fill:#8e5,stroke:#5a3
    class structures,structure_name_forms,perimeters,structure_relations manuel;
    classDef csv fill:#fa5
    class apc_payments csv
    classDef auto fill:#adf,stroke:#58c
    class source_publications,publications,journals,publishers,authorships,persons,subjects auto
    classDef main stroke-width:4px,font-weight:bold
    class structures,publications,persons,authorships main
```

Légende :
- **vert** : tables peuplées manuellement
- **orange** : imports CSV
- **bleu** : tables peuplées automatiquement par le pipeline à partir des imports API

## Tables associées

- **`journals`** : référentiel des revues.
- **`journal_name_forms`** : formes de noms normalisées pour le matching journaux (parallèle à `person_name_forms` et `structure_name_forms`).
- **`publishers`** : référentiel des éditeurs.
- **`publisher_name_forms`** : formes de noms normalisées pour le matching éditeurs.
- **`apc_payments`** : données issues d'un import CSV (cf. [doc sources](../sources/09-imports-manuels.md#donnees-apc)).
- **`distinct_publications`** : paires de publications marquées comme **distinctes malgré un titre identique**, évite de les re-suggérer dans l'interface de dédoublonnage `admin/duplicates`.

## Sujets / mots-clés

Trois tables alimentées par les phases `subjects` et `cooccurrences` du pipeline :

- **`subjects`** : référentiel des sujets/mots-clés indexés.
- **`publication_subjects`** : table de liaison publication ↔ sujet (avec score / source).
- **`subject_cooccurrences`** : matrice de co-occurrences entre sujets, alimentée à partir de `publication_subjects`.

## Services propriétaires

| Table | Propriétaire | Notes |
|---|---|---|
| `publications` | `application/publications.py` | `refresh_from_sources()` recalcule les métadonnées depuis les `source_publications` |
| `distinct_publications` | `application/publications.py` (endpoint admin) | paires marquées distinctes malgré titre identique |
| `journals` | `application/journals.py` | — |
| `journal_name_forms` | `application/journals.py` | formes de noms normalisées pour le matching |
| `publishers` | `application/publishers.py` | — |
| `publisher_name_forms` | `application/publishers.py` | formes de noms normalisées pour le matching |
| `subjects`, `publication_subjects` | `application/pipeline/subjects/run.py` | — |
| `subject_cooccurrences` | `application/pipeline/cooccurrences/run.py` | recalcul global après ingestion subjects |
| `apc_payments` | import APC (CSV) | — |
