# Schéma `publications`

*À jour le 2026-10-12.*

Référentiel consolidé des productions de recherche et de leurs contributions. Cf [doc pipeline](../pipeline/07-publications.md) pour la logique de résolution d'entités.

```mermaid
flowchart LR
    structures --- contributions
    contributions --- publications
    contributions --- persons
    structures --- apc_payments
    apc_payments ---|DOI| publications
    source_records-->|match_or_create|publications
    publications---|publication_subjects|subjects
    publications---journals
    journals---publishers


    classDef manuel  fill:#8e5,stroke:#5a3
    class structures manuel;
    classDef csv fill:#fa5
    class apc_payments csv
    classDef auto fill:#adf,stroke:#58c
    class source_records,publications,journals,publishers,contributions,persons,subjects auto
    classDef main stroke-width:4px,font-weight:bold
    class structures,publications,persons,contributions main
```

Légende :
- **vert** : tables peuplées manuellement
- **orange** : imports CSV
- **bleu** : tables peuplées automatiquement par le pipeline à partir des imports API

## Tables associées

- **`publications_detail`** : satellite 1:1 de `publications` qui contient les métadonnées volumineuses. Cf. [données dérivées](08-donnees-derivees.md).
- **`publication_relations`** : relations sémantiques entre publications distinctes mais apparentées (preprint ↔ version publiée, supplément ↔ article, erratum ↔ article corrigé…). Peuplée par la phase `relations`.

## `contributions` — table consolidée des contributions

Table de liaison recensant les contributions individuelles aux publications. Chaque entrée référence **1 personne**, **1 publication**, *n* structures (via la matview `group_structures` de son groupe de contributions sources). Construite par `pipeline/transformation/publications/contributions/build_contributions.py` à partir des *contributions* sources.

**Couverture partielle assumée** : la table contient seulement les signataires ayant une `person_id`. Les co-auteurs hors périmètre sont absents ; la liste exhaustive des auteurs d'une publication se lit dans `source_contributions`.

Colonnes notables :

- `in_perimeter` : TRUE si une contribution source de la personne sur cette publication entre dans le périmètre (`perimeter_evidence` non vide)
- `roles` (text[]) : rôles (auteur, directeur, rapporteur — pour theses.fr)

`contribution_structures (contribution_id, structure_id)` donne les affiliations résolues. C'est une **vue matérialisée**, réunion des `source_contribution_structures` des contributions sources qui attestent la contribution (même publication par leur enregistrement source, même personne), rafraîchie par le pipeline en fin de phase `contributions`.

**Une édition d'administration laisse la vue matérialisée en l'état.** La review d'un lien adresse ↔ structure et l'assignation d'une contribution source orpheline recalculent `in_perimeter` en direct, mais l'agrégation des structures reste sur l'état de la dernière exécution du pipeline.

**Cohérence avec les sources** : la table est **entièrement dérivée** des `source_contributions`. `in_perimeter`, `is_corresponding`, `author_position` et `roles` en sont des consolidations, par union ou par priorité de source. Les décisions humaines sont dans le [schéma `persons`](05-persons.md#décisions-humaines).

## Sujets / mots-clés

Trois tables alimentées par la phase `subjects` du pipeline :

- **`subjects`** : référentiel des sujets/mots-clés indexés.
- **`publication_subjects`** : table de liaison publication ↔ sujet (avec score / source).
- **`subject_cooccurrences`** : matrice de co-occurrences entre sujets, alimentée à partir de `publication_subjects`.

## Propriété des tables

| Table | Auteur | Écrit par |
|---|---|---|
| `publications` | pipeline | `pipeline/transformation/publications/consolidation.py` (`refresh_from_sources` recalcule depuis les sources) |
| `publications_detail` | pipeline | `pipeline/transformation/publications/store.py` |
| `publication_relations` | pipeline | phase `relations` |
| `contributions` | pipeline | `build_contributions.py` (consolidée depuis les sources) |
| `subjects`, `publication_subjects` | pipeline | `pipeline/transformation/publications/subjects/subject_ingestion.py` |
| `subject_cooccurrences` | pipeline | `pipeline/transformation/publications/subjects/subject_cooccurrences.py` (matview) |
