# Résolution des affiliations

```mermaid
flowchart LR
    A[source_authorships]-->B[addresses]
    D[structures]-->E[structure_name_forms]
    E-->|resolve_addresses|F[address_structures]
    B-->|resolve_addresses|F
    F-->|populate_affiliations|A
    classDef new  fill:#bbf
    classDef valid  fill:#af5
    class F new;
    class D,E valid;
```

Phase `affiliations` : deux sous-étapes enchaînées :

1. **`resolve_addresses`** — matche les adresses normalisées avec les formes de nom des structures (`structure_name_forms`). Résultat dans `address_structures` (avec `matched_form_id` pour la traçabilité). Code applicatif : `application/pipeline/affiliations/resolve_addresses.py`, entry point CLI : `interfaces/cli/pipeline/resolve_addresses.py`.
2. **`populate_affiliations`** — calcule `in_perimeter` et `structure_ids` sur les `source_authorships` à partir des `address_structures`. Code applicatif : `application/pipeline/affiliations/populate_affiliations.py`.

> **TODO :** documenter plus précisément la logique de `resolve_addresses`.
