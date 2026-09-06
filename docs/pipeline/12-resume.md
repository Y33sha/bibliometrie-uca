# Résumé : peuplement des référentiels

*À jour le 2026-06-30.*

1. Les **structures** préexistent au pipeline. Elles sont reconnues dans les adresses liées aux publications, et permettent de repérer les authorships (et indirectement les publications) du périmètre.

```mermaid
flowchart TB
    subgraph consolidé
    structures
    end
    subgraph sources
    SP@{ shape: procs, label: "source_publications"}---SA@{ shape: procs, label: "source_authorships"}
    SA---addresses
    end

    structures--->addresses
    classDef valid  fill:#af5
    class structures valid;
```

2. La phase [`publications`](07-publications.md) peuple la table **publications** par résolution d'entités à partir des sources.

```mermaid
flowchart LR
    subgraph consolidé
        publications
        structures

    end

    subgraph sources


        SP@{ shape: procs, label: "source_publications"}---SA@{ shape: procs, label: "source_authorships"}
        SA---structures
    end

    SP-->publications
    classDef valid  fill:#af5
    class structures,publications valid;
```

3. La phase [`persons`](08-persons.md) rattache les *authorships* du périmètre aux personnes existantes ou crée de nouvelles personnes.

```mermaid
flowchart LR
    subgraph consolidé
        publications
        structures
        persons
    end
    subgraph sources
        SP@{ shape: procs, label: "source_publications"}---SA@{ shape: procs, label: "source_authorships"}
    end

    SP---publications
    SA-->persons
    SA---structures
    classDef valid  fill:#af5
    class structures,publications,persons valid;
```


4. La phase [`authorships`](09-authorships.md) crée les liens entre les publications, les personnes et les structures. L'information portée par les `source_authorships` — l'auteur (`person_id`) et ses structures de rattachement — est agrégée dans la table `authorships` par union des sources.

```mermaid
flowchart LR
    subgraph consolidé
        publications---authorships
        persons---authorships
        structures---authorships
    end
    subgraph sources
        SP@{ shape: procs, label: "source_publications"}---SA@{ shape: procs, label: "source_authorships"}
    end

    SP---publications
    SA---persons
    SA---structures
    classDef valid  fill:#af5
    class structures,publications,persons,authorships valid;
```
