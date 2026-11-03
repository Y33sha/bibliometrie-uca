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

Dans 120 publications, la liste HAL continue après sa dernière contribution source présente dans une autre source, scanR mis à part. Ces fins de liste comptent 3 705 contributions sources, dont 1 130 au rôle `ctb` et 3 531 sans personne. Une même personne figure dans 7 de ces fins de liste au plus.

Crossref donne une liste pour 21 947 publications (70,5 %). Son dernier auteur est celui de la règle à listes plus courtes écartées dans 21 314 cas. La règle trouve un désaccord dans 386 cas. Crossref donne un autre dernier auteur dans 247 cas, toujours avec une liste plus courte que la plus longue. La règle trouve un dernier auteur pour 9 112 publications sans liste Crossref.

### Critères de troncature

Même périmètre, base du 2026-11-03 après la phase 1 : 28 873 publications ont au moins une liste, dont 28 054 au moins deux. Une liste présente une signature de troncature si une autre liste de sa publication est plus longue et si elle compte un seul auteur, ou 41 ou 51 auteurs pour scanR. Dans un vote à la majorité, une égalité laisse la publication sans dernier auteur.

| Critère du dernier auteur | Accord, publications à deux listes ou plus | Désaccord avec Crossref |
|---|---:|---:|
| Toutes les listes, unanimité | 90,0 % | 0 |
| Listes les plus longues, unanimité | 98,6 % | 251 |
| Listes sans signature de troncature, unanimité | 95,5 % | 43 |
| Listes sans signature de troncature, majorité | 99,4 % | 68 |
| Idem, copie scanR d'un dépôt HAL écartée, majorité | 99,4 % | 64 |
| Toutes les listes, copie scanR écartée, majorité | 98,9 % | 20 |

Crossref vote lui-même. La dernière colonne favorise donc les critères où toutes les listes votent.

Une liste d'un seul auteur plus courte que la plus longue contient le premier auteur de la plus longue (406 cas), son dernier auteur (108) ou un autre auteur (104). Retirer les contributions sources `ctb` des listes change l'accord de 0,1 à 0,2 point. Pour le premier auteur, la majorité donne un accord dans 99,6 % des publications à deux listes ou plus, l'unanimité dans 97,9 %.

## Décisions

- Chaque liste d'auteurs vote pour la contribution alignée avec son premier auteur et pour la contribution alignée avec son dernier auteur. Le premier auteur et le dernier auteur sont les contributions majoritaires. Une égalité laisse la publication sans premier ou sans dernier auteur.
- Seules les listes complètes votent pour le dernier auteur. Une liste est tronquée si une autre liste de sa publication est plus longue et si elle compte un seul auteur, ou 41 ou 51 auteurs pour scanR.
- La copie scanR d'un dépôt HAL vote seulement en l'absence de l'enregistrement HAL.
- Les contributions sources au rôle `ctb` restent dans la liste d'auteurs.
- Une colonne `contributions.author_positions`, tableau de l'enum `author_position` (`corresponding`, `first`, `last`), réunit les trois positions. `contributions.is_corresponding` disparaît.
- La facette « Position auteur » prend les valeurs de l'enum. « Autre position » correspond à un tableau vide.
- Les positions se recalculent avec les attributs des contributions (tâche `author_grouping.attributes`), par publication entière. La position d'une contribution dépend de toutes les listes de sa publication.
- Les rapports gardent les rôles comptés par unité.

## Phasage

### Phase 1 — Collectifs abrégés

- [x] Abréviations `grp` et `collaborat` dans les mots de collectif. Script ponctuel `mark_collective_source_contributions` pour les contributions sources existantes. 2bf85b364

### Phase 2 — Positions des contributions

- [x] Critère de troncature d'une liste.
- [x] Enum `author_position` et colonne `contributions.author_positions`. La migration reprend la position de correspondant et marque toutes les contributions pour la recomposition de leurs attributs. Suppression de `contributions.is_corresponding`. a8d65d67f
- [x] Calcul des positions dans la recomposition des attributs (`propagate_contribution_attributes_sql`). Un changement de position ou de rôles d'une contribution source marque la publication pour le groupement des auteurs, donc toutes ses contributions. a8d65d67f
- [x] Lectures de `contributions.is_corresponding` reprises : liste et export des publications, détail d'une publication, filtres, rapports, frontend, tests. a8d65d67f

### Phase 3 — Facette et rapports

- [x] Facette « Position auteur » : premier et dernier auteur, libellés dans le frontend. 62ecc651c
- [x] Rapports : rôles lus dans `author_positions`, lecture de la liste OpenAlex supprimée. Libellé « PDC (premier, dernier ou correspondant) » pour les unités qui comptent les trois rôles. 0c3846001

### Phase 4 — Co-premiers et co-derniers auteurs

- [ ] Remplissage des rôles HAL `co_first_author` et `co_last_author`, perdus à la normalisation (`domain/publications/contribution_roles.py`).

### Phase 5 — Documentation

- [ ] Positions d'auteur dans la documentation des contributions.
