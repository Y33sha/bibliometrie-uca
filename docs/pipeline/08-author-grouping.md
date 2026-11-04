# Alignement des auteurs

*À jour le 2026-11-04.*

La phase `author_grouping` réunit dans une [contribution](../donnees/04-contributions.md) les contributions sources d'un même auteur dans une publication, une par enregistrement source au plus (`aligned_source_contributions`). Elle vient après la phase `publications`, qui réunit les enregistrements sources d'un même document, et avant la phase [`persons`](09-persons.md), qui décide la personne de chaque contribution.

## Publications à recalculer

Les contributions d'une publication se recalculent entièrement, donc le résultat est indépendant de l'ordre d'arrivée des enregistrements sources. La file `publication_contributions_queue` liste les publications à recalculer : un enregistrement source y arrive ou en part, ou ses contributions sources changent. `--rebuild-author-grouping` les marque toutes.

## Contributions sources écartées

- Les contributions sources collectives (collaboration, consortium, rédaction…).
- Les doublons d'auteur : une source répète un bloc de sa liste à la suite, chaque nom à sa place, ou des auteurs dans la liste des membres d'un collectif. Après l'alignement s'y ajoute une contribution source restée seule, de même nom et même prénom complet qu'une contribution source de son enregistrement source alignée avec d'autres sources. Le doublon reçoit `duplicate_of`, vers la contribution source répétée (`domain/contributions/author_duplicates.py`).
- Les enregistrements sources DataCite d'une version de concept ou d'une pièce de jeu de données, quand la publication a un autre enregistrement source : leur liste d'auteurs répète celle d'un autre enregistrement source.

Ces contributions sources ne sont dans aucune contribution et n'ont pas de personne.

## Alignement

Les enregistrements sources se traitent de la liste d'auteurs la plus longue à la plus courte, chacun face aux contributions déjà formées. Une contribution source rejoint une contribution :

1. par une clé de nom unique des deux côtés : nom de famille, nom et prénom, ou nom et initiale ;
2. par la ressemblance des noms dans son trou, l'intervalle entre deux contributions sources déjà alignées ;
3. par la ressemblance des noms hors de l'ordre des listes, avec un mot identique.

La ressemblance compare les noms complets, quel que soit leur découpage entre nom de famille et prénom. Les règles sont dans `domain/contributions/author_grouping.py`, la ressemblance des noms dans `domain/contributions/name_similarity.py`.

## Écritures

- `contributions` : une ligne par auteur, avec `reference_position`, la position dans la liste la plus longue.
- `aligned_source_contributions` : une ligne par contribution source alignée, avec l'origine du lien (`method` : `reference`, `name`, `gap`, `unordered`).

Chaque contribution reprend l'identifiant de la contribution en base avec laquelle elle partage le plus de contributions sources. La personne suit l'identifiant. Une contribution en base sans correspondant est supprimée. Une contribution rattachée entre dans la file de redécision de sa personne (`contribution_resolution_queue`) quand ses contributions sources changent.

La tâche `author_grouping.attributes` recompose les attributs des contributions de la file `contribution_attributes_queue`. `roles` et `perimeter_evidence` sont l'union de ceux des contributions sources alignées. `author_positions` réunit les positions d'auteur. Une contribution est correspondante si une de ses contributions sources l'est. Les listes d'auteurs de la publication votent pour le premier et le dernier auteur, à la majorité. Les listes tronquées votent seulement pour le premier auteur.

La vue matérialisée `publication_author_alignment` mesure le recouvrement des listes d'auteurs de chaque publication. Elle sert l'onglet des fusions suspectes de l'administration.
