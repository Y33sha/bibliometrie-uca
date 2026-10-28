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

Les règles sont dans `domain/publications/author_grouping.py`. Les enregistrements sources se traitent de la liste la plus longue à la plus courte, chacun face aux contributions déjà formées. À longueur égale, un enregistrement source scanR passe après les autres. Une liste qui intervertit patronyme et prénom s'aligne avec ses noms remis dans l'ordre.

Un prénom réduit à des initiales prend le prénom de la personne à laquelle un humain a rattaché l'ORCID ou l'IdRef de la contribution source, si les initiales concordent.

**Règle de noms**, à l'intérieur de chaque patronyme :

1. patronyme unique des deux côtés ;
2. patronyme et prénom complet uniques ;
3. patronyme et initiale uniques ;
4. ORCID ou IdRef partagé avec une contribution source de la contribution, à patronyme égal. Un identifiant présent dans deux contributions ne lie rien.

**Filtre d'ordre.** Seule la plus longue suite de liens rangés dans le même ordre des deux côtés est gardée ; les autres liens passent au résidu. Les liens par identifiant, et ceux d'une contribution source sans position, échappent au filtre.

**Trous.** Entre deux liens, les contributions sources de même patronyme et de même initiale, en nombre égal des deux côtés, se lient dans l'ordre des positions.

**Modèle du résidu.** Un modèle de Fellegi-Sunter lie le reste. Il compare le patronyme, le prénom, l'ORCID, l'IdRef et le trou. Une affectation hongroise retient un lien quand les preuves dépassent log2 du nombre de contributions restantes. Deux patronymes seulement proches, aux premières initiales différentes, ne se lient pas, sauf identifiant commun. Les poids sont dans `pipeline/transformation/publications/author_grouping/residual_weights.py` ; `interfaces/cli/dev/estimate_residual_weights.py` les réestime avec Splink.

Une contribution fondée par une liste plus courte prend rang juste après la contribution de son voisin précédent dans cette liste.

## Écritures

- `contributions` : une ligne par auteur, avec `reference_position`, la position dans la liste la plus longue.
- `aligned_source_contributions` : une ligne par contribution source alignée, avec l'origine du lien (`method` : `reference`, `name`, `identifier`, `order`, `model`), et pour le modèle le score et la marge, en bits.

Chaque contribution reprend l'identifiant de la contribution en base avec laquelle elle partage le plus de contributions sources : chaque identifiant une seule fois, le plus petit en cas d'égalité. La personne suit l'identifiant. Une contribution en base sans correspondant est supprimée. Une contribution rattachée dont les contributions sources changent entre dans la file de redécision de sa personne (`contribution_resolution_queue`).

La tâche `author_grouping.attributes` recompose les attributs des contributions de la file `contribution_attributes_queue` : `roles`, `is_corresponding` et `perimeter_evidence` sont l'union de ceux des contributions sources alignées.

La vue matérialisée `publication_author_alignment` mesure le recouvrement des listes d'auteurs de chaque publication. Elle sert l'onglet des fusions suspectes de l'administration.
