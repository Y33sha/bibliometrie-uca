# Résumé : peuplement des tables canoniques

*À jour le 2026-06-30.*

1. Les **structures** préexistent au pipeline. Elles sont reconnues dans les adresses liées aux publications, et permettent de repérer les authorships (et indirectement les publications) du périmètre.

```mermaid
flowchart TD
    subgraph vérité
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

2. La phase [`publications`](07-publications.md) peuple la table **publications** par déduplication à partir des sources.

```mermaid
flowchart LR
    subgraph vérité
        direction TD
        publications
        structures

    end

    subgraph sources
        direction TD
        SA---structures
        SP@{ shape: procs, label: "source_publications"}---SA@{ shape: procs, label: "source_authorships"}

    end

    SP-->publications
    classDef valid  fill:#af5
    class structures,publications valid;
```

3. La phase [`persons`](09-persons.md) rattache les *authorships* du périmètre aux personnes existantes ou crée de nouvelles personnes.

```mermaid
flowchart LR
    subgraph vérité
        direction TD
        publications
        structures
        persons
    end
    subgraph sources
        direction TD
        SP@{ shape: procs, label: "source_publications"}---SA@{ shape: procs, label: "source_authorships"}
    end

    SP---publications
    SA-->persons
    SA---structures
    classDef valid  fill:#af5
    class structures,publications,persons valid;
```


4. La phase [`authorships`](10-authorships.md) crée les liens entre publications, personnes et structures canoniques. L'information portée par les `source_authorships` — l'auteur (`person_id`) et ses structures de rattachement — est agrégée dans la table `authorships` par union des sources.

```mermaid
flowchart LR
    subgraph vérité
        direction TD
        publications---authorships
        persons---authorships
        structures---authorships
    end
    subgraph sources
        direction TD
        SP@{ shape: procs, label: "source_publications"}---SA@{ shape: procs, label: "source_authorships"}
    end

    SP---publications
    SA---persons
    SA---structures
    classDef valid  fill:#af5
    class structures,publications,persons,authorships valid;
```
