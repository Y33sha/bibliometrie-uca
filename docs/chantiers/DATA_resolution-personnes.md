# Chantier — Résolution des personnes

## Contexte

La résolution des personnes est une cascade de règles. Elle rattache chaque contribution source à une personne existante, sans comparer les contributions sources entre elles. C'est la forme de ReCiter. La réconciliation des publications regroupe les enregistrements sources qui partagent une clé de confirmation.

La phase `author_grouping` réunit en amont les contributions sources d'un même auteur d'une publication (`source_contribution_groups`). La cascade se sert des groupes seulement pour propager une personne d'une contribution source aux autres contributions sources du groupe. Une décision par groupe réunit les identifiants, les noms et les affiliations de toutes les sources avant de trancher.

L'affiliation sert seulement à délimiter le périmètre. Une forme de nom partagée par deux personnes laisse la contribution source sans personne. Les affiliations fausses des sources, qui créent de fausses personnes du périmètre, relèvent du chantier [vérification des affiliations](DATA_verification-affiliations.md).

**Contrat de la résolution** : en entrée, les enregistrements sources et les contributions sources, plus les décisions humaines ; en sortie, une table de correspondance entre chaque enregistrement source ou contribution source et son entité. Le contrat tient quel que soit l'algorithme.

**Forme par paires**, celle de Splink et de dnet-dedup. Chaque étape lit en base ce que la précédente a écrit :

1. **paires candidates** : les paires d'enregistrements sources ou de contributions sources qui concordent, avec leur origine ou leur score ;
2. **décisions** : les confirmations ajoutent des paires, les rejets et les non-doublons en retirent ;
3. **groupes** : composantes connexes sur les paires retenues ;
4. **identifiant** : chaque groupe reçoit un identifiant ;
5. **entité** : construite à partir des membres du groupe.

La table des paires est du dérivé recalculable. C'est la sortie d'un modèle probabiliste comme de règles déterministes.

## Décisions

- La méthode de résolution des personnes se choisit d'après des essais hors pipeline, évalués sur les verdicts humains, comme dans le chantier [alignement des auteurs](DATA_alignement-auteurs.md).
- **Rejet d'un identifiant.** Un identifiant est rejeté pour une personne. Le rejet invalide les rattachements non épinglés que cet identifiant soutient seul : la contribution source redevient orpheline. Le run suivant la résout sans cet identifiant, par le nom si elle est du périmètre, ou par une autre source où la même contribution source est présente. Les rattachements entre sources ancrés sur elle tombent s'ils n'ont pas d'autre appui.

## Phasage

### Phase 1 — Mesure

- [x] Jeu d'évaluation tiré des verdicts humains, le 2026-10-19 (`build_evaluation_set.py`). Il compte 2 373 couples (contribution source, personne) justes, 523 couples (enregistrement source, personne) faux et 23 paires de personnes distinctes.
  - Couples justes : 1 610 rattachements manuels (`confirmed_source_contributions`), et 763 contributions sources des groupes jugés « doublon de personnes », rattachées à la personne conservée par la fusion. 78 contributions sources sont hors groupe.
  - Couples faux : rattachements détachés (`rejected_contributions`).
  - Le jeu est concentré : trois personnes ont 80 % des détachements, cinq personnes 45 % des rattachements manuels.
  - La cascade lit les rattachements manuels et les détachements. L'évaluation la fait tourner sans eux.
- [x] Précision et rappel de la cascade actuelle sur ce jeu, le 2026-10-19. La phase `persons` reconstruit les rattachements dans une copie de la base (`reset_eval.sql`). La copie garde les personnes, les fiches RH et les décisions humaines sur les identifiants et les formes de nom. Elle perd les rattachements, les épinglages, les détachements et les attributions déduites des rattachements. Les résultats sur le jeu d'évaluation varient peu après le deuxième passage (`evaluate.py`). Le tableau donne le troisième.

  | Lignes du jeu | Total | Juste | Sans personne | Autre personne | Personne créée |
  |---|---|---|---|---|---|
  | rattachements manuels | 1 610 | 464 | 755 | 363 | 28 |
  | contributions sources des doublons fusionnés | 763 | 592 | 29 | 0 | 142 |

  - La reconstruction converge en cinq passages : 756 000, 1 307 000, 1 612 000, 1 732 000 puis 1 736 000 contributions sources rattachées, contre 1 833 000 en production. La phase charge les candidats hors périmètre en début de passage. Un lien entre sources attend donc le passage qui suit l'identification de son ancre.
  - 128 détachements sur 523 se reproduisent, dont 90 pour cinq personnes.
  - 345 rattachements faux viennent de deux personnes connues seulement par leurs épinglages, « A. Devaux » et « G. Roche ». La reconstruction les supprime, et leurs contributions sources rejoignent un homonyme par le nom.
  - Les doublons fusionnés se reforment : 142 contributions sources créent une autre personne.
  - 704 des 755 rattachements manuels restés sans personne sont groupés et du périmètre, et leur forme de nom désigne plusieurs personnes. L'affiliation spécifique, sur les profils de la reconstruction, désigne la personne épinglée dans 340 cas (59 personnes), une autre personne dans 5 cas (2 personnes), plusieurs candidats dans 317 cas (24 personnes). Elle ne tranche pas 42 cas (`affiliation_on_pins.sql`).
- [x] Signaux par groupe, le 2026-10-19 (`measure_group_signals.sql`), sur les 503 276 groupes qui ont une contribution source du périmètre ou un identifiant connu. Identifiants : ORCID des sources à dépôt auteur, IdRef, compte HAL. Nom : forme exacte de la contribution source.

  | Signal | Groupes | Sans personne |
  |---|---|---|
  | identifiants de plusieurs personnes | 26 | 0 |
  | identifiant et nom de deux personnes différentes | 28 | 22 |
  | identifiant d'une personne, nom concordant ou inconnu | 437 834 | 1 048 |
  | nom d'une seule personne | 57 197 | 0 |
  | nom de plusieurs personnes | 2 176 | 684 |
  | aucun signal, périmètre | 6 015 | 6 014 |

  - Les identifiants et les formes de nom en base viennent en partie des rattachements, donc la mesure sous-estime les conflits.
- [ ] Pouvoir de l'affiliation, le 2026-10-19 (`measure_affiliation.sql`), sur les 2 176 groupes au nom ambigu. Une clé spécifique est un laboratoire ou une équipe du référentiel, ou un laboratoire, une équipe ou un département HAL. Le profil d'un candidat réunit les clés de ses autres publications.
  - Avec toutes les clés, établissements et ROR compris, plusieurs candidats concordent dans 1 725 groupes. Avec les clés spécifiques, un seul candidat concorde dans 1 631 groupes, plusieurs dans 392.
  - Sur ces 1 631 groupes, le candidat désigné est la personne rattachée dans 1 151 groupes, une autre personne dans 7. 463 groupes sont sans personne, 10 rattachés à plusieurs personnes.
  - Échantillon de 97 groupes à relire (`build_affiliation_review.py`).
- [ ] Rattachements par identifiant dont l'identifiant est rejeté ou absent chez la personne : 2 232 au 2026-10-18, dont 885 rejetés. L'identifiant de la contribution source est souvent faux et la personne souvent juste. Échantillon relu à la main.

### Phase 2 — Essais d'une cascade par groupe

- [ ] Une décision par groupe, sur les signaux réunis de ses contributions sources : identifiants des sources fiables, nom au prénom le plus complet, structures et adresses.
- [ ] Critère d'affiliation : les structures du groupe confrontées à celles des autres publications de chaque candidat. Il départage les homonymes et les identifiants contradictoires. Une adresse au CHU de Clermont laisse l'auteur hors périmètre, mais appuie son rattachement à une personne RH.
- [ ] Une personne par groupe au plus. Dans une publication, un groupe par personne au plus.
- [ ] Contributions sources hors groupe : doublons d'auteur des enregistrements sources écartés de l'alignement (enregistrement source scanR issu d'un dépôt HAL présent, enregistrement source DataCite au DOI convergé). `author_grouping` ne les détecte pas, donc la résolution les rattache à une personne. 358 enregistrements sources au 2026-10-18.
- [ ] Évaluation des variantes sur le jeu de la phase 1, dans `data/experiments/resolution-personnes/` (non versionné).

### Phase 3 — Choix de la méthode

- [ ] Cascade seule, ou cascade puis modèle probabiliste sur le résidu, d'après l'évaluation de la phase 2.

### Phase 4 — Intégration au pipeline

- [ ] `person_id` et `resolution_mode` passent de `source_contributions` à `source_contribution_groups`. `source_contribution_groups` remplace `contributions`, matviews reportées.
- [ ] Invalidation des rattachements au rejet d'un identifiant. Au 2026-10-20, 836 contributions sources non épinglées de 39 personnes sont rattachées par un identifiant rejeté pour leur personne, sans autre identifiant valide. Elles ancrent 2 223 rattachements entre sources.
- [ ] Correction du stock : doubles rattachements (une personne rattachée à deux contributions sources d'un même enregistrement source), personnes qui ont les identifiants de deux personnes, ORCID en attente rattachés à une autre personne que leur titulaire (21 groupes dans la relecture du 2026-10-19).

### Phase 5 — Règles de la résolution dans le domaine

- [ ] Une entrée de domaine rend la décision complète d'une contribution source, pour les deux passes de la cascade. Elle lit un index de personnes en mémoire, que le pipeline met à jour après chaque écriture : formes de nom, homonymes par nom de famille, ancres entre sources. Elle renvoie les refus de corroboration. `NameFormDecision` et `PersonMatchDecision` fusionnent.
- [ ] Règles assemblées par `pipeline/transformation/persons/cascade.py`, reprises par cette entrée : ORCID des seules sources à dépôt par l'auteur (`trusted_identifier`), personnes rejetées pour la publication, nom seul sans effet hors périmètre.
- [ ] Verdict d'une forme de nom calculé en Python sur `AttributionStatus` ; `fetch_name_form_status_map` rend les faits bruts.

### Phase 6 — Fin de chantier

- [ ] Mise à jour de la documentation.

## Questions ouvertes

- Pour le modèle probabiliste, Splink plutôt qu'un modèle maison.
- Splink additionne les comparaisons comme si elles étaient indépendantes : revue, sujet et structure, corrélés, sont à regrouper en une seule comparaison.
- Splink ne prévoit pas les liens imposés ou interdits : les décisions humaines s'appliquent à l'étape 2.
- Les composantes connexes ne respectent pas les interdictions. La réconciliation des publications sépare toujours deux DOI différents, ce que la transitivité des paires ne garantit pas. L'étape 3 devient alors un regroupement sous contraintes, et l'étape 2 reçoit aussi les interdictions issues des règles.
- Les décisions sur les personnes visent des entités (un rejet vise un couple publication-personne, un non-doublon deux personnes), non des paires de contributions sources. Comment les traduire en contraintes sur les contributions sources ?
- Deux idées de ReCiter : enregistrer ce qui a concordé et pas seulement la règle ; réutiliser les confirmations et les rejets d'une personne comme indices pour ses autres contributions sources.
- `publications.reconcile`, aujourd'hui une seule tâche du graphe : le scinder selon les étapes de la forme par paires, si elle est retenue.
