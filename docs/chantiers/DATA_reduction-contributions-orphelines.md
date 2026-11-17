# Chantier — Réduction des contributions orphelines

## Contexte

Une contribution orpheline est une contribution du périmètre, sous un rôle d'auteur, sans personne rattachée. Motifs des 944 contributions orphelines, d'après le rejeu de la décision du rattachement au 2026-11-17 :

| Motif | Contributions |
|---|---|
| Forme de nom désignant plusieurs personnes | 533 |
| Personne rattachée à une autre contribution de la publication | 389 |
| Noms des contributions sources désignant des personnes différentes | 11 |
| Personnes candidates toutes rejetées pour la publication | 10 |
| Identifiants désignant des personnes différentes | 1 |

Les 389 contributions dont la personne est rattachée à une autre contribution de la publication se répartissent ainsi :

- par origine : 378 partagent un enregistrement source avec l'autre contribution, donc l'enregistrement liste l'auteur deux fois. 8 viennent de deux enregistrements d'une même source dans la publication. 3 viennent d'un alignement manqué entre deux sources.
- par graphie : 111 ont la même graphie que l'autre contribution, 250 une initiale face à un prénom complet, 28 deux prénoms complets différents (nom et prénom inversés, faute d'accent, changement de nom).

## Décisions

- Chaque catégorie d'orphelines se résout par une règle du pipeline.
- Les indices se mesurent sur les orphelines et sur un jeu de contrôle : contributions rattachées par un identifiant ou à la main, au nom désignant plusieurs personnes.
- Le chantier [Audit de la qualité de la résolution des personnes](DATA_audit-qualite-resolution-personnes.md) reprend après celui-ci.

## Phasage

### Phase 1 — Départage des formes de nom ambiguës

Un indice désigne une personne candidate quand elle seule partage cet indice avec la contribution, d'après ses autres publications. Indice laboratoire : un laboratoire ou une équipe du référentiel. Indice discipline : un sous-domaine OpenAlex, à défaut un domaine OpenAlex, puis un domaine HAL de niveau 2, puis de niveau 1. Mesure du 2026-11-17 sur les 533 orphelines au nom ambigu et sur un jeu de contrôle de 1 102 contributions :

| Verdict | Orphelines | Contrôle : justes / faux |
|---|---|---|
| Laboratoire et discipline désignent la même personne | 159 | 327 / 5 |
| Discipline seule | 150 | 290 / 18 |
| Laboratoire seul | 72 | 43 / 4 |
| Laboratoire et discipline désignent deux personnes | 5 | laboratoire juste 4 fois sur 4 |
| Aucun indice | 147 | 411 |

- [x] Relecture des 27 faux du jeu de contrôle :
  - 14 références fausses : 12 IdRef de ScanR, 2 identifiants HAL. La personne désignée par la règle est la bonne.
  - 1 personne en double : la règle désigne le doublon de la personne de référence.
  - 10 erreurs de la règle : 6 entre deux homonymes du même laboratoire et du même domaine, 3 par un domaine HAL de niveau 1, 1 par le laboratoire CHU.
  - 2 cas indécidables.
- [x] Variantes de la règle. 295 contributions du contrôle ont pour référence le seul IdRef de ScanR. Le contrôle épuré les écarte :

  | Variante | Orphelines départagées | Contrôle épuré : justes / faux |
  |---|---|---|
  | Règle mesurée | 386 | 476 / 11 |
  | Sans CHU | 368 | 484 / 11 |
  | Sans domaine HAL de niveau 1 | 382 | 464 / 7 |
  | Sans CHU ni domaine HAL de niveau 1 | 364 | 472 / 7 |
- [ ] Laboratoires, équipes et départements HAL comme indice laboratoire. Mesure du 2026-10-19 (`measure_affiliation.sql`) sur 2 176 contributions au nom ambigu, avec ces structures HAL et le référentiel : une seule personne concorde dans 1 631 cas, plusieurs dans 392. Sur les 1 631 cas, la personne désignée est la personne rattachée dans 1 151, une autre personne dans 7. Échantillon de 97 cas à relire (`build_affiliation_review.py`).
- [ ] Indice coauteurs : coauteurs habituels de la personne candidate présents dans la publication.
- [ ] Indices revue et années d'activité.
- [ ] Confirmations et rejets d'une personne comme indices pour ses autres contributions (idée de ReCiter).
- [ ] Règle de départage dans la phase `persons`, avec les indices retenus.

### Phase 2 — Auteur listé deux fois dans un enregistrement source

- [ ] Règle de réunion des deux contributions sources d'un enregistrement désignant la même personne, à décider. 378 orphelines.

### Phase 3 — Enregistrements d'une même source et alignements manqués

- [ ] Diagnostic des 8 orphelines issues de deux enregistrements d'une même source et des 3 alignements manqués.

### Phase 4 — Cas restants

- [ ] Relecture des 11 conflits de noms, des 10 orphelines aux candidats tous rejetés et du conflit d'identifiants.

### Phase 5 — Documentation

- [ ] Mise à jour de la documentation du rattachement des personnes.

## Questions ouvertes

- Deux coauteurs homonymes de même graphie dans un enregistrement : critère qui les distingue d'un auteur listé deux fois.
