# Chantier — Premier et dernier auteur

## Contexte

Les rapports bibliométriques par unité (`interfaces/cli/reporting/structure_report.py`) comptent les publications où un auteur de l'unité tient un rôle clé. Les rôles comptés dépendent de l'unité (`KEY_ROLES_BY_STRUCTURE`) : auteur correspondant, premier ou dernier auteur. Premier et dernier auteur se lisent dans la seule liste OpenAlex.

La facette « Position auteur » de la page personne propose seulement l'auteur correspondant. Chaque position de la facette correspond à une colonne booléenne de `contributions` (`AUTHOR_POSITION_COLUMNS`). Une contribution est correspondante si une de ses contributions sources l'est.

### Mesures du 2026-11-03 (base locale)

Publications de 2020 à 2025, types des rapports : articles, articles de synthèse, ouvrages, chapitres, conference papers. La liste d'auteurs d'un enregistrement source regroupe ses contributions sources au rôle auteur, non collectives, hors doublons (`duplicate_of`), avec une position. 31 125 publications ont au moins une liste, dont 28 655 au moins deux.

| Règle, publications à deux listes ou plus | Publications avec un accord |
|---|---:|
| Premier auteur, toutes les listes | 97,8 % |
| Dernier auteur, toutes les listes | 90,0 % |
| Dernier auteur, listes plus courtes que la plus longue écartées | 98,4 % |

Enregistrements sources au dernier auteur différent de celui de la majorité : scanR 2 121, dont 1 916 à liste plus courte ; OpenAlex 666 ; HAL 635 ; WoS 286 ; Crossref 129 ; DataCite 80. Une liste scanR plus courte que la plus longue de sa publication s'arrête souvent à 51 auteurs (2 616 cas, toutes années) ou à 41 (338 cas).

Écarter les listes plus courtes donne raison à une liste seule contre au moins deux listes plus courtes concordantes dans 194 publications :

- Dans près de la moitié, la liste HAL ajoute en fin de liste un auteur absent de Crossref, OpenAlex, scanR et WoS (249). Cet auteur a parfois le rôle `ctb` (1828).
- Dans 41 cas, la liste OpenAlex compte un auteur de plus que HAL et sa copie scanR (5207).
- WoS compte comme auteur un collectif abrégé, « FACE BD Grp » (6523). Les mots de collectif (`domain/persons/collective_names.py`) omettent les abréviations WoS `Grp` et `Collaborat`, présentes dans 13 contributions sources.
- Dans 60 cas, les listes plus courtes se réduisent au premier auteur.

Crossref donne une liste pour 21 947 publications (70,5 %). Son dernier auteur est celui de la règle à listes plus courtes écartées dans 21 314 cas. La règle trouve un désaccord dans 386 cas. Crossref donne un autre dernier auteur dans 247 cas, toujours avec une liste plus courte que la plus longue. La règle trouve un dernier auteur pour 9 112 publications sans liste Crossref.

## Décisions

- Le premier auteur est la contribution alignée avec le premier de chaque liste d'auteurs. Le dernier auteur est la contribution alignée avec le dernier de chaque liste.
- Seules les listes complètes votent pour le dernier auteur.
- Une colonne `contributions.author_positions`, tableau de l'enum `author_position` (`corresponding`, `first`, `last`), réunit les trois positions. `contributions.is_corresponding` disparaît.
- La facette « Position auteur » prend les valeurs de l'enum. « Autre position » correspond à un tableau vide.
- Les positions se recalculent avec les attributs des contributions (tâche `author_grouping.attributes`), par publication entière. La position d'une contribution dépend de toutes les listes de sa publication.
- Les rapports gardent les rôles comptés par unité.

## Phasage

### Phase 1 — Collectifs abrégés

- [ ] Abréviations `grp` et `collaborat` dans les mots de collectif. Script ponctuel ciblé pour les contributions sources existantes.

### Phase 2 — Positions des contributions

- [ ] Critère de troncature d'une liste.
- [ ] Enum `author_position` et colonne `contributions.author_positions`, remplie par sa migration. Suppression de `contributions.is_corresponding`.
- [ ] Calcul des positions dans la recomposition des attributs (`propagate_contribution_attributes_sql`). Un changement de rôles d'une contribution source marque toutes les contributions de sa publication.
- [ ] Lectures de `contributions.is_corresponding` reprises : liste et export des publications, détail d'une publication, filtres, frontend, tests.

### Phase 3 — Facette et rapports

- [ ] Facette « Position auteur » : premier et dernier auteur, libellés dans le frontend.
- [ ] Rapports : rôles lus dans `author_positions`, lecture de la liste OpenAlex supprimée. Libellé « PDC (premier, dernier ou correspondant) » pour les unités qui comptent les trois rôles.

### Phase 4 — Co-premiers et co-derniers auteurs

- [ ] Remplissage des rôles HAL `co_first_author` et `co_last_author`, perdus à la normalisation (`domain/publications/contribution_roles.py`).

### Phase 5 — Documentation

- [ ] Positions d'auteur dans la documentation des contributions.

## Questions ouvertes

- Critère de troncature. « Plus courte que la plus longue » écarte les listes coupées par scanR et les listes réduites au premier auteur. Il donne aussi raison à une liste seule qui ajoute un auteur en fin de liste. Autres critères possibles :
  - signatures connues de troncature : scanR à 41 ou 51 auteurs, `staging.authors_truncated` d'OpenAlex, liste d'un seul auteur ;
  - majorité des listes ;
  - copie scanR d'un dépôt HAL comptée comme une seule liste.
- Contribution source HAL au rôle `ctb` en fin de liste : dans la liste d'auteurs, ou hors de la liste pour le calcul du premier et du dernier auteur.
