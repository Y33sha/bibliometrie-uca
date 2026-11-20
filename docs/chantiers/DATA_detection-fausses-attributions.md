# Chantier — Détection des fausses attributions

## Contexte

Les sources attribuent à un chercheur des publications d'un homonyme : HAL et ScanR par l'identifiant du chercheur (idHAL, IdRef), les autres sources par le nom. L'administration rejette ces publications une à une. Un rejet porte sur un couple (enregistrement source, personne) : le rejet d'une publication en compte un par enregistrement source. Au 2026-11-20 : 5 019 rejets, 848 paires (publication, personne), 64 personnes.

Dans une publication rejetée, la contribution au nom de la personne rejetée est celle de l'homonyme. État de ces contributions au 2026-11-20 (`rejets_etat.py`) :

| État | Contributions |
|---|---|
| Sans personne, hors périmètre | 583 |
| Épinglée sur une personne sans fiche RH, homonyme créé par l'administration | 145 |
| Épinglée sur une autre personne à fiche RH | 14 |
| Rattachée par le pipeline à une autre personne à fiche RH | 45 |
| Rattachée par le pipeline à une autre personne sans fiche RH | 22 |
| Sans personne, du périmètre | 8 |

40 paires sont sans contribution au nom de la personne, 9 en comptent plusieurs.

Mesures du 2026-11-20 (`data/experiments/contributions-orphelines/`), chaque publication jugée sans tenir compte d'elle-même :

- Profil des publications rejetées (`simulation_detection.py`), tiré des 589 contributions sans personne seules au nom de la personne dans leur publication : la cascade de départage du rattachement compare une publication au profil de la personne et au profil des publications rejetées. Elle désigne le profil des publications rejetées pour 571 des 589 publications rejetées, et pour 1 des 738 publications non rejetées des 19 personnes concernées. Le rappel suppose au moins deux ou trois rejets pour la personne.
- Aucun indice commun avec la personne (coauteur, laboratoire, structure HAL, revue) : 584 des 589 publications rejetées, 110 des 738 non rejetées. Parmi les publications non rejetées sans indice commun, la plupart partagent un sous-champ OpenAlex avec la personne ou sont sans sujet OpenAlex.
- Clusters des publications d'une personne (`clusters_chercheurs.py`) : deux publications sont reliées si elles partagent un coauteur, un laboratoire, une structure HAL, une revue ou un thème OpenAlex ; un cluster est une composante connexe. 577 des 589 publications rejetées tombent dans des clusters sans publication non rejetée. Sur 1 225 personnes à fiche RH, 33 réunissent au moins deux clusters d'au moins trois publications, souvent de sous-champs sans rapport.

Mesures de la phase 1 (`data/experiments/fausses-attributions/`). Jeu de validation : 794 paires rejetées à contribution unique au nom de la personne, chez 34 personnes ayant des publications acceptées. Une personne réunit 493 paires : son homonyme est membre d'une grande collaboration de physique.

- Une publication rejetée compte 2 905 contributions en médiane, une publication acceptée 7.
- Huit personnes seulement ont au moins trois publications rejetées. Une publication rejetée isolée est indiscernable d'une publication acceptée isolée. Les clusters détectent donc seulement les homonymes à plusieurs publications.
- Modèle de référence (`validation.py`, `criblage.py`) :
  - graphe des publications d'une personne, chaque indice partagé pondéré par sa rareté dans la base ;
  - indices : coauteurs, laboratoires, structures HAL de recherche, revue, thèmes OpenAlex, domaines HAL de niveau 2 ;
  - partition de Leiden, résolution 0,2 ;
  - cluster principal : le plus de contributions rattachées par ORCID ou épinglées ;
  - cluster signalé : au moins trois publications, aucune contribution rattachée par ORCID ou épinglée, conductance d'au plus 0,15.
- Validation : 749 des 794 publications rejetées signalées, 14 des 1 522 publications acceptées.
- Criblage des 1 225 personnes à fiche RH d'au moins six publications : 36 personnes, 37 clusters, 225 publications. 25 clusters sont sans affiliation au périmètre, 12 affiliés. Les contributions sont rattachées par IdRef (118), idHAL (81) ou le nom (26).
- Les composantes connexes signalent 559 publications rejetées : elles réunissent la personne et l'homonyme de même discipline. Louvain équivaut à Leiden. Sans les filtres d'ancrage et de conductance, Leiden découpe les publications de la personne en plusieurs clusters : 118 personnes signalées.
- Apport des indices, hors de la personne à 493 paires : 243 des 301 publications rejetées signalées avec pondération par la rareté, 67 sans pondération, 66 sans coauteurs. Laboratoires, structures HAL et thèmes réduisent les signalements de clusters affiliés. Les domaines HAL de niveau 2 apportent peu, la revue rien, le facteur de taille de collaboration des coauteurs rien. Sous-champs, champs OpenAlex et domaines HAL de niveau 1 relient les clusters et font perdre des rejets.
- Les 37 clusters signalés ont un cosinus des sous-champs inférieur à 0,3 avec le cluster principal. Ce critère sépare mal un chercheur pluridisciplinaire d'un homonyme.
- Profil de comparaison (`profil_comparaison.py`). Un profil limité aux contributions sans personne attribue à la personne 137 des 139 publications épinglées sur un homonyme créé par l'administration, et 57 des 59 publications détenues par une autre personne à fiche RH. Un profil réunissant toutes les publications rejetées, quel que soit le détenteur de la contribution, en désigne 132 et 55. Fausses alertes : 3 des 1 314 publications acceptées. Les personnes de nom compatible ajoutées comme concurrentes apportent peu.
- Détecteur amorcé par k publications rejetées (`amorce.py`) : rappel moyen par personne 0,53 pour k = 1, 0,71 pour 2, 0,91 pour 3, 0,93 pour 5. Fausses alertes : au plus 4 sur 4 050.
- Détecteur amorcé par les clusters signalés du criblage (`amorce_cluster.py`) : 3 contributions suspectes de plus sur 2 615, dont 2 rattachées par ORCID. Sur le stock, les clusters réunissent déjà les fausses attributions. Le détecteur sert aux publications à venir.
- Détection unifiée par clusters (`unifie.py`) : le graphe réunit les publications de la personne et k publications rejetées ; une publication est suspecte dans un cluster contenant une publication rejetée. À amorce égale, la cascade de départage donne dix fois moins de fausses alertes. Son rappel moyen par personne est meilleur dès k = 3 : 0,91 contre 0,87 pour k = 3, 0,96 contre 0,79 pour k = 10. Les clusters servent donc seulement aux personnes sans rejet.
- Le criblage complet prend 50 secondes et 400 Mo.
- Épreuve sur les données actuelles (`epreuve.py`). Chaque cluster signalé est vérifié par l'ORCID et les adresses de ses contributions sources, et par les périodes RH de la personne. 22 des 37 clusters sont des fausses attributions : 21 personnes, 143 publications. 13 clusters sont de vraies publications de la personne, 2 restent incertains.
  - Fausses attributions : ORCID différent de celui de la personne, ou adresses hors d'Auvergne, le plus souvent dans une autre discipline.
  - Vraies publications : adresses en Auvergne (10 clusters), ou thèses sans adresse (3 clusters).
  - Témoins, tirés des clusters principaux : 1 ORCID différent et 14 adresses hors d'Auvergne sur 168 contributions.
  - La cascade de départage signale 3 publications des personnes du jeu de validation : 2 de la personne, 1 incertaine.

## Décisions

- Le profil de comparaison d'une personne réunit les publications rejetées pour elle, quel que soit le détenteur de la contribution à son nom. Il se calcule à la demande depuis les rejets.
- La détection signale à l'administration, qui décide. Aucun détachement automatique.
- Pour une personne sans rejet, l'administration rejette un cluster signalé entier : ses publications amorcent le profil de comparaison.

## Phasage

### Phase 1 — Exploration du modèle

Scripts de mesure dans `data/experiments/`, sans code du pipeline. Jeu de validation : les publications rejetées, contributions de l'homonyme, face aux publications non rejetées des mêmes personnes.

- [x] Pondération des indices selon leur rareté : une revue généraliste, un thème répandu, un coauteur d'une grande collaboration comptent peu.
- [x] Détection de communautés (Louvain, Leiden) face aux composantes connexes, sur le graphe pondéré.
- [x] Indices à retenir, et apport de chacun : coauteurs, laboratoires, structures HAL, revues, thèmes et sous-champs OpenAlex, domaines HAL, années.
- [x] Mesures de chaque variante : séparation des publications rejetées sur le jeu de validation ; personnes à fiche RH signalées, avec relecture automatique des clusters (sous-champs, laboratoires, années) ; chercheurs pluridisciplinaires signalés à tort.
- [x] Profil de comparaison d'une publication rejetée épinglée ou rattachée à une autre personne : homonyme créé par l'administration, autre personne à fiche RH.
- [x] Détecteur des attributions suspectes : profil de l'homonyme amorcé par un cluster, rappel et fausses alertes selon le nombre de publications de l'homonyme.
- [ ] Choix du modèle, puis décisions de conception : stockage ou calcul à la demande des clusters, seuils.

### Phase 2 — Clusters et homonymes probables

- [ ] Règle du domaine : clusters des publications d'une personne, selon le modèle retenu.
- [ ] Calcul des clusters des personnes pour l'administration.
- [ ] Onglet « Homonymes probables » de l'administration : personnes à plusieurs clusters, sous-champs de chaque cluster, rejet d'un cluster entier.

### Phase 3 — Attributions suspectes

- [ ] Détecteur : une publication rattachée à une personne, hors épinglage, est suspecte quand la cascade de départage désigne le profil des publications rejetées pour la personne.
- [ ] Onglet « Attributions suspectes » de l'administration : rejet ou confirmation d'un clic.
- [ ] Mesure sur le stock, puis relecture des alertes.

### Phase 4 — Documentation

- [ ] Mise à jour de la documentation du rattachement des personnes et de l'administration.

## Questions ouvertes

- Un chercheur pluridisciplinaire réunit des clusters distincts sans homonyme.
