# Chantier — Résolution des personnes

## Contexte

La résolution des personnes est une cascade de règles. Elle rattache chaque signature à une personne existante, sans comparer les signatures entre elles. C'est la forme de ReCiter. La réconciliation des publications regroupe les notices qui partagent une clé de confirmation.

La phase `author_grouping` réunit en amont les signatures d'un même auteur d'une publication (`source_authorship_groups`). La cascade se sert des groupes seulement pour propager une personne d'une signature aux autres signatures du groupe. Une décision par groupe réunit les identifiants, les noms et les affiliations de toutes les sources avant de trancher.

L'affiliation sert seulement à délimiter le périmètre. Une forme de nom partagée par deux personnes laisse la signature sans personne.

**Contrat de la résolution** : en entrée, les notices et les signatures sources, plus les décisions humaines ; en sortie, une table de correspondance entre chaque notice ou signature et son entité. Le contrat tient quel que soit l'algorithme.

**Forme par paires**, celle de Splink et de dnet-dedup. Chaque étape lit en base ce que la précédente a écrit :

1. **paires candidates** : les paires de notices ou de signatures qui concordent, avec leur origine ou leur score ;
2. **décisions** : les confirmations ajoutent des paires, les rejets et les non-doublons en retirent ;
3. **groupes** : composantes connexes sur les paires retenues ;
4. **identifiant** : chaque groupe reçoit un identifiant ;
5. **entité** : construite à partir des membres du groupe.

La table des paires est du dérivé recalculable. C'est la sortie d'un modèle probabiliste comme de règles déterministes.

## Décisions

- La méthode de résolution des personnes se choisit d'après des essais hors pipeline, évalués sur les verdicts humains, comme dans le chantier [alignement des auteurs](DATA_alignement-auteurs.md).

## Phasage

### Phase 1 — Mesure

- [x] Jeu d'évaluation tiré des verdicts humains, le 2026-10-19 (`build_evaluation_set.py`). Il compte 2 373 couples (signature, personne) justes, 523 couples (notice, personne) faux et 23 paires de personnes distinctes.
  - Couples justes : 1 610 rattachements manuels (`confirmed_authorships`), et 763 signatures des groupes jugés « doublon de personnes », rattachées à la personne conservée par la fusion. 78 signatures sont hors groupe.
  - Couples faux : rattachements détachés (`rejected_authorships`).
  - Le jeu est concentré : trois personnes ont 80 % des détachements, cinq personnes 45 % des rattachements manuels.
  - La cascade lit les rattachements manuels et les détachements. L'évaluation la fait tourner sans eux.
- [ ] Précision et rappel de la cascade actuelle sur ce jeu. Ils servent de base de comparaison aux essais.
- [ ] Signaux par groupe. Décompte des groupes dont les identifiants désignent plusieurs personnes, dont l'identifiant et le nom désignent deux personnes différentes, dont le nom désigne plusieurs personnes ou aucune.
- [ ] Pouvoir de l'affiliation : parmi les groupes au nom ambigu, part de ceux dont les structures recoupent celles d'un seul candidat sur ses autres publications. Échantillon relu à la main.
- [ ] Rattachements par identifiant dont l'identifiant est rejeté ou absent chez la personne : 2 232 au 2026-10-18, dont 885 rejetés. L'identifiant de la signature est souvent faux et la personne souvent juste. Échantillon relu à la main.

### Phase 2 — Essais d'une cascade par groupe

- [ ] Une décision par groupe, sur les signaux réunis de ses signatures : identifiants des sources fiables, nom au prénom le plus complet, structures et adresses.
- [ ] Critère d'affiliation : les structures du groupe confrontées à celles des autres publications de chaque candidat. Il départage les homonymes et les identifiants contradictoires. Une adresse au CHU de Clermont laisse l'auteur hors périmètre, mais appuie son rattachement à une personne RH.
- [ ] Une personne par groupe au plus. Dans une publication, un groupe par personne au plus.
- [ ] Signatures hors groupe : doublons d'auteur des notices écartées de l'alignement (notice scanR issue d'un dépôt HAL présent, notice DataCite au DOI convergé). `author_grouping` ne les détecte pas, donc la résolution les rattache à une personne. 358 notices au 2026-10-18.
- [ ] Évaluation des variantes sur le jeu de la phase 1, dans `data/experiments/resolution-personnes/` (non versionné).

### Phase 3 — Choix de la méthode

- [ ] Cascade seule, ou cascade puis modèle probabiliste sur le résidu, d'après l'évaluation de la phase 2.

### Phase 4 — Intégration au pipeline

- [ ] `person_id` et `resolution_mode` passent de `source_authorships` à `source_authorship_groups`. `source_authorship_groups` remplace `authorships`, matviews reportées.
- [ ] Correction du stock : doubles rattachements (une personne rattachée à deux signatures d'une même notice), personnes qui ont les identifiants de deux personnes, ORCID en attente rattachés à une autre personne que leur titulaire (21 groupes dans la relecture du 2026-10-19).

### Phase 5 — Fin de chantier

- [ ] Mise à jour de la documentation.

## Questions ouvertes

- Pour le modèle probabiliste, Splink plutôt qu'un modèle maison.
- Splink additionne les comparaisons comme si elles étaient indépendantes : revue, sujet et structure, corrélés, sont à regrouper en une seule comparaison.
- Splink ne prévoit pas les liens imposés ou interdits : les décisions humaines s'appliquent à l'étape 2.
- Les composantes connexes ne respectent pas les interdictions. La réconciliation des publications sépare toujours deux DOI différents, ce que la transitivité des paires ne garantit pas. L'étape 3 devient alors un regroupement sous contraintes, et l'étape 2 reçoit aussi les interdictions issues des règles.
- Les décisions sur les personnes visent des entités (un rejet vise un couple publication-personne, un non-doublon deux personnes), non des paires de signatures. Comment les traduire en contraintes sur les signatures ?
- Deux idées de ReCiter : enregistrer ce qui a concordé et pas seulement la règle ; réutiliser les confirmations et les rejets d'une personne comme indices pour ses autres signatures.
- `publications.reconcile`, aujourd'hui un seul nœud du graphe : le scinder selon les étapes de la forme par paires, si elle est retenue.
