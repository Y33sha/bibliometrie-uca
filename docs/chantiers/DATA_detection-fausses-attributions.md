# Chantier — Détection des fausses attributions

## Contexte

Les sources attribuent à un chercheur des publications d'un homonyme : HAL et ScanR par l'identifiant du chercheur (idHAL, IdRef), les autres sources par le nom. L'administration rejette ces publications une à une. Au 2026-11-20 : 5 019 rejets pour 64 personnes, 848 paires (publication, personne). Dans 589 de ces paires, une seule contribution sans personne a le nom de la personne : c'est la contribution de l'homonyme.

Mesures du 2026-11-20 (`data/experiments/contributions-orphelines/`), chaque publication jugée sans tenir compte d'elle-même :

- Profil de l'homonyme (`simulation_detection.py`) : la cascade de départage du rattachement compare une publication au profil de la personne et à celui de l'homonyme. Elle désigne l'homonyme pour 571 des 589 publications rejetées, et pour 1 des 738 publications non rejetées des 19 personnes concernées. Le rappel suppose au moins deux ou trois rejets pour la personne.
- Aucun indice commun avec la personne (coauteur, laboratoire, structure HAL, revue) : 584 des 589 publications rejetées, 110 des 738 non rejetées. Parmi les publications non rejetées sans indice commun, la plupart partagent un sous-champ OpenAlex avec la personne ou sont sans sujet OpenAlex.
- Clusters des publications d'une personne (`clusters_chercheurs.py`) : deux publications sont reliées si elles partagent un coauteur, un laboratoire, une structure HAL, une revue ou un thème OpenAlex ; un cluster est une composante connexe. 577 des 589 publications rejetées tombent dans des clusters sans publication non rejetée. Sur 1 225 personnes à fiche RH, 33 réunissent au moins deux clusters d'au moins trois publications, souvent de sous-champs sans rapport.

## Décisions

- L'homonyme d'une personne rejetée est une fiche de personne exclue hors périmètre, qui réunit les publications rejetées pour la personne. Il reste hors du rattachement par le nom : il sert seulement de profil de comparaison.
- La détection signale à l'administration, qui décide. Aucun détachement automatique.
- Les clusters amorcent l'homonyme d'une personne sans rejet : l'administration rejette un cluster entier.

## Phasage

### Phase 1 — Exploration du modèle

Scripts de mesure dans `data/experiments/`, sans code du pipeline. Jeu de validation : les publications rejetées, contributions de l'homonyme, face aux publications non rejetées des mêmes personnes.

- [ ] Pondération des indices selon leur rareté : une revue généraliste, un thème répandu, un coauteur d'une grande collaboration comptent peu.
- [ ] Détection de communautés (Louvain, Leiden) face aux composantes connexes, sur le graphe pondéré.
- [ ] Indices à retenir, et apport de chacun : coauteurs, laboratoires, structures HAL, revues, thèmes et sous-champs OpenAlex, domaines HAL, années.
- [ ] Mesures de chaque variante : séparation des publications rejetées sur le jeu de validation ; personnes à fiche RH signalées, avec relecture automatique des clusters (sous-champs, laboratoires, années) ; chercheurs pluridisciplinaires signalés à tort.
- [ ] Détecteur des attributions suspectes : profil de l'homonyme amorcé par un cluster, rappel et fausses alertes selon le nombre de publications de l'homonyme.
- [ ] Choix du modèle, puis décisions de conception : stockage ou calcul à la demande des clusters, seuils.

### Phase 2 — Clusters et homonymes probables

- [ ] Règle du domaine : clusters des publications d'une personne, selon le modèle retenu.
- [ ] Calcul des clusters des personnes pour l'administration.
- [ ] Onglet « Homonymes probables » de l'administration : personnes à plusieurs clusters, sous-champs de chaque cluster, rejet d'un cluster entier.

### Phase 3 — Homonyme des personnes rejetées

- [ ] Migration : colonne `persons.homonym_of`.
- [ ] Tâche du pipeline : dans une publication rejetée pour une personne, la seule contribution sans personne au nom de la personne rejoint l'homonyme, créé au besoin. Une contribution dont le rejet a disparu perd l'homonyme. Code de départ : commit 0b1be1d1a, sans le rattachement par le nom.
- [ ] Fusion de personnes : l'homonyme de la personne absorbée devient celui de la personne conservée.

### Phase 4 — Attributions suspectes

- [ ] Détecteur : une publication rattachée à une personne qui a un homonyme, hors épinglage, est suspecte quand la cascade de départage désigne l'homonyme.
- [ ] Onglet « Attributions suspectes » de l'administration : rejet ou confirmation d'un clic.
- [ ] Mesure sur le stock, puis relecture des alertes.

### Phase 5 — Documentation

- [ ] Mise à jour de la documentation du rattachement des personnes et de l'administration.

## Questions ouvertes

- Un chercheur pluridisciplinaire réunit des clusters distincts sans homonyme.
