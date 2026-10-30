# Alignement des auteurs

*À jour le 2026-10-26.*

La phase `author_grouping` réunit dans une [contribution](../donnees/04-contributions.md) les contributions sources d'un même auteur dans une publication, une par enregistrement source au plus (`aligned_source_contributions`). Elle vient après la phase `publications`, qui réunit les enregistrements sources d'un même document, et avant la phase [`persons`](09-persons.md), qui décide la personne de chaque contribution.

## Publications à recalculer

Les contributions d'une publication se recalculent entièrement, donc le résultat est indépendant de l'ordre d'arrivée des enregistrements sources. La file `publication_contributions_queue` liste les publications à recalculer : un enregistrement source y arrive ou en part, ou ses contributions sources changent. `--rebuild-author-grouping` les marque toutes.

## Contributions sources écartées

- Les contributions sources collectives (collaboration, consortium, rédaction…).
- Les doublons d'auteur : une source répète un bloc de sa liste à la suite, chaque nom à sa place, ou des auteurs dans la liste des membres d'un collectif. Le doublon reçoit `duplicate_of`, vers la première occurrence du nom (`domain/publications/list_copies.py`).
- Les enregistrements sources DataCite d'une version de concept ou d'une pièce de jeu de données, quand la publication a un autre enregistrement source : leur liste d'auteurs répète celle d'un autre enregistrement source.

Ces contributions sources ne sont dans aucune contribution et n'ont pas de personne.

## Alignement

Les enregistrements sources se traitent de la liste d'auteurs la plus longue à la plus courte, chacun face aux contributions déjà formées. Une contribution source rejoint une contribution par son nom (nom de famille et prénom, ou initiale, sans ambiguïté), par un ORCID ou un IdRef partagé, ou par sa place entre deux contributions sources déjà alignées. Un modèle probabiliste (Fellegi-Sunter) aligne le reste. Les règles sont dans `domain/publications/author_grouping.py`, les poids du modèle dans `pipeline/transformation/publications/author_grouping/residual_weights.py`.

## Écritures

- `contributions` : une ligne par auteur, avec `reference_position`, la position dans la liste la plus longue.
- `aligned_source_contributions` : une ligne par contribution source alignée, avec l'origine du lien (`method` : `reference`, `name`, `identifier`, `order`, `model`).

Chaque contribution reprend l'identifiant de la contribution en base avec laquelle elle partage le plus de contributions sources. La personne suit l'identifiant. Une contribution en base sans correspondant est supprimée. Une contribution rattachée dont les contributions sources changent entre dans la file de redécision de sa personne (`contribution_resolution_queue`).

La tâche `author_grouping.attributes` recompose les attributs des contributions de la file `contribution_attributes_queue` : `roles`, `is_corresponding` et `perimeter_evidence` sont l'union de ceux des contributions sources alignées.

La vue matérialisée `publication_author_alignment` mesure le recouvrement des listes d'auteurs de chaque publication. Elle sert l'onglet des fusions suspectes de l'administration.
