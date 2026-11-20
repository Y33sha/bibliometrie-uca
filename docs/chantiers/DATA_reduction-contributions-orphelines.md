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
- Une forme de nom ambiguë se départage par une cascade d'indices : coauteurs, structure du référentiel, structure HAL, revue, années d'activité. La première étape qui désigne une seule personne candidate décide.

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
- [x] Indice coauteurs : personnes rattachées à la publication et présentes dans les autres publications de la personne candidate. Seuil : au moins un coauteur partagé, à défaut au moins deux. Mesure sur le contrôle épuré, laboratoire sans CHU, discipline sans domaine HAL de niveau 1 :

  | Règle | Orphelines départagées | Contrôle épuré : justes / faux |
  |---|---|---|
  | Coauteurs | 422 | 613 / 3 |
  | Coauteurs, puis laboratoire | 429 | 626 / 3 |
  | Coauteurs, puis laboratoire, puis discipline | 456 | 662 / 5 |
  | Laboratoire, puis discipline | 364 | 472 / 7 |

  Les coauteurs départagent 4 des 6 erreurs entre homonymes du même laboratoire et du même domaine.
- [x] Indices structures HAL (laboratoire, équipe ou département HAL), revue et années d'activité (année de la publication à deux ans au plus des autres publications de la personne). Mesure du 2026-11-19 (`data/experiments/contributions-orphelines/mesure.py`) :

  | Règle | Orphelines départagées | Contrôle épuré : justes / faux |
  |---|---|---|
  | Laboratoire seul | 142 | 286 / 0 |
  | Structures HAL seules | 85 | 372 / 3 |
  | Revue seule | 188 | 277 / 3 |
  | Années seules | 182 | 137 / 0 |
  | Coauteurs, laboratoire, structures HAL, revue | 453 | 688 / 3 |
  | Coauteurs, laboratoire, structures HAL, revue, discipline | 475 | 699 / 5 |
  | Coauteurs, laboratoire, structures HAL, revue, discipline, années | 488 | 703 / 5 |
  | Coauteurs, laboratoire, structures HAL, revue, années | 477 | 692 / 3 |
  | Coauteurs, laboratoire ou structures HAL en une étape, revue, années | 475 | 679 / 3 |

  Des profils tirés des seuls rattachements par identifiant ou à la main départagent autant de cas du contrôle, et moins d'orphelines. L'indice laboratoire réunit les structures du référentiel atteintes par l'adresse, le ROR ou la structure HAL. L'indice structures HAL ajoute les structures HAL hors du référentiel, et les équipes ou départements HAL rattachés à un laboratoire du référentiel.
- [x] Rejets d'une personne comme indice négatif (idée de ReCiter) : la personne candidate est écartée quand la publication partage un coauteur ou un laboratoire avec ses publications rejetées, et aucun avec ses propres publications. Sur le contrôle épuré, l'indice écarte 26 fois une autre personne et jamais la personne de référence. Les cas écartés sont déjà départagés par la cascade.
- [x] Règle de départage dans la phase `persons`, avec les indices retenus :
  - [x] Règle du domaine (`domain.persons.tie_break`) : cascade ordonnée d'indices. Chaque indice reçoit le contexte de la contribution et les profils des personnes candidates, et désigne une personne ou aucune. Constantes du domaine : structures du référentiel retenues (laboratoires), types de structure HAL retenus (laboratoire, équipe, département), écart d'années (2), seuils de coauteurs (1, puis 2).
  - [x] Décision : `decide_contribution` renvoie les personnes candidates d'une forme de nom ambiguë. La cascade décide ces contributions avant `settle_publication` (`decide_with_tie_break`). Dans une publication, un rattachement par la cascade cède devant un rattachement par le nom.
  - [x] Mode de rattachement : une valeur de `resolution_mode` par indice (migration `c5d8a1e3f276`), pour mesurer chaque indice et retrouver ses rattachements. Libellés dans la vue du pipeline de l'administration.
  - [x] Chargement par lot de publications : contexte des contributions ambiguës du lot (personnes rattachées à la publication, structures, revue, année) et profils de leurs personnes candidates, hors publication décidée. Profils et coauteurs présents viennent des seuls rattachements hors cascade, donc le résultat est indépendant de l'ordre des lots.
  - [x] Purge : la redécision des contributions rattachées par le nom ou par la cascade passe par la même cascade. Un changement de mode de rattachement marque aussi la contribution.
  - [x] Tests : un test du domaine par indice et pour l'ordre de la cascade ; tests d'intégration du rattachement et de la purge.
  - [x] Mesure du 2026-11-19 sur la base de production (`simulation_cascade.py`) : 477 orphelines départagées (coauteurs 422, années 24, revue 19, laboratoire 8, structure HAL 4), en 5,9 s.
  - [x] Après la migration : snapshot du schéma, run de la phase `persons`. Run du 2026-11-19 : 944 orphelines ramenées à 461, 492 rattachements par la cascade.
  - [ ] Capture de la vue du pipeline.

### Phase 2 — Auteur listé deux fois dans un enregistrement source

Au 2026-11-19, 387 orphelines ont leur personne rattachée à une autre contribution de la publication. La détection existante des doublons d'auteur (`duplicate_of`) compare les noms à l'identique. Elle manque deux cas : une source liste l'auteur deux fois sous deux graphies (INSPIRE : « Porteboeuf, Sarah Julie » et « Porteboeuf-Houssais, S. ») ; Crossref et OpenAlex ajoutent la liste des membres d'un collectif, aux initiales, à la suite des auteurs. D'autres paires sont des homonymes réels, listés deux fois par toutes les sources (« Xu, Z. » dans les grandes collaborations).

- [x] Détection des doublons d'auteur par comparaison des listes de la publication (`cross_list_duplicates`). Deux contributions sources d'une liste au nom d'un même auteur forment un doublon :
  - dans une liste de moins de 100 auteurs : une liste de référence cite le nom une seule fois, ou l'une a un prénom complet et l'autre des initiales, ou elles ont le même nom complet ;
  - dans une grande collaboration : les deux occurrences sont à 10 rangs au plus, un nom de famille prolonge l'autre, et une liste de référence cite le nom une seule fois.

  Une liste de référence est complète et d'une source hors WoS : WoS fusionne des homonymes. Deux ORCID non neutralisés différents pour ce nom, dans les listes de la publication, désignent deux homonymes. L'occurrence gardée est celle dont le rang relatif est le plus proche de celui du nom dans les listes de référence.
- [x] Mesure du 2026-11-19 (`simulation_doublons.py`) : 129 des 140 doublons confirmés par un même ORCID et 112 des 168 doublons sans contrôle disparaissent ; les homonymes « Xu », « Schmidt » et « Dias » restent distincts. Sur 3 000 publications tirées au hasard, 35 nouveaux doublons dans 15 publications, relus justes. L'alignement prend 8 % de temps en plus, 14 % sur les 50 plus longues listes.
- [x] Recalcul des contributions de toutes les publications (`--rebuild-author-grouping`). Run du 2026-11-19 : 461 orphelines ramenées à 212, dont 138 ont leur personne rattachée à une autre contribution de la publication. Motifs de ces 138 (`doublons_restants_motifs.py`) :

  | Motif | Orphelines |
  |---|---|
  | Nom listé deux fois par chaque enregistrement source de la publication | 38 |
  | Liste des membres d'un collectif ajoutée à une liste d'au moins 100 auteurs : une liste complète cite le nom une fois, et sa longueur sépare les rangs des deux occurrences | 24, plus 14 où cette liste est celle de WoS |
  | Aucun enregistrement source partagé avec l'autre contribution | 11 |
  | Même ORCID, neutralisé ou non, sur les deux occurrences | 9 |
  | Nom et prénom inversés | 3 |
  | Autres, surtout dans les grandes collaborations | 39 |
- [x] Extension de la détection :
  - seuil des grandes collaborations : 300 auteurs. Sous ce seuil, les doublons viennent surtout des listes de membres d'essais cliniques. Au-delà, les homonymes des collaborations de physique apparaissent (Finger M. et Finger M. Jr). Beaucoup de ces collaborations sont absentes d'INSPIRE ;
  - même ORCID d'auteur sur les deux occurrences, quelle que soit la longueur de la liste. Seuls HAL et INSPIRE donnent un ORCID d'auteur. Crossref, OpenAlex et DataCite donnent un même ORCID à des homonymes voisins (deux « Rossi, E. ») ;
  - nom et prénom permutés, comptés comme un même nom complet.
- [x] Mesure du 2026-11-19 (`simulation_regle_300.py`) : 53 des 138 couples résolus (seuil 37, ORCID 11, noms permutés 5). Sur 3 000 publications tirées au hasard et les 3 013 publications à liste d'au moins 100 auteurs : 1 776 doublons ajoutés dans 226 publications (seuil 1 471, ORCID 232, noms permutés 73), justes sur l'échantillon relu. Durée de la détection inchangée.
- [x] Recalcul des contributions de toutes les publications (`--rebuild-author-grouping`). Run du 2026-11-19 : 212 orphelines ramenées à 159. Parmi elles, 87 ont leur personne rattachée à une autre contribution de la publication. Motifs : nom listé deux fois par chaque enregistrement source (36), aucun enregistrement source partagé (11), liste de membres dans une liste d'au moins 300 auteurs (4), autres cas des grandes collaborations surtout (36).

### Phase 3 — Enregistrements d'une même source et alignements manqués

- [x] Diagnostic des 11 orphelines sans enregistrement source partagé avec la contribution de leur personne (`sans_enregistrement_partage.py`) :
  - changement de nom entre deux enregistrements sources, même rang et autres auteurs identiques (6) : Vernier et Gable, Van Lander et Maneval (3 publications), Araujo da Silva et Guérin, Batisse et Lance ;
  - nom mal découpé par la source (4) : « as / gremeau », « hang nguyen / and », « nemo » pour « nemoto / rie » ;
  - fusion erronée de deux communications HAL de même titre, aux listes d'auteurs différentes (1).
- [x] Alignement par le rang : dans un trou d'un seul auteur de chaque côté, la contribution source rejoint la contribution quand l'initiale du prénom concorde, dans une liste de moins de 300 auteurs. Simulation du 2026-11-19 (`simulation_trou_unique.py`) : 5 des 11 orphelines résolues ; sur 3 000 publications tirées au hasard, 8 liens ajoutés, dont 7 changements de nom plausibles. Au-delà de 300 auteurs, les liens ajoutés sont souvent faux (Reboud et Rebollo de Miguel, Xia et Xie).
- [x] Recalcul des contributions après l'alignement par le rang. Run du 2026-11-20 : 162 orphelines. Les liens par le rang résolvent 3 doublons et font apparaître 3 conflits de noms : les deux noms de Marie Riquelme désignent deux personnes.

### Phase 4 — Cas restants

- [x] Relecture des 13 conflits de noms, des 8 orphelines aux personnes candidates toutes rejetées et du conflit d'identifiants (`conflits_noms.py`) :
  - conflits de noms : 10 contributions d'une personne en double sous deux noms, soit 8 paires de personnes (Ribeiro Mickael et Micakël, Fahrat et Farhat, Riquelme et Arbre, « Chéreau Dr Isabelle »…). 3 erreurs d'alignement ou de source (« goli / g » pour Godi, « laurichesse / h » rattaché à Henri pour Hélène) ;
  - personnes candidates toutes rejetées : le rejet humain écarte la seule personne au nom de la contribution, donc l'auteur est un homonyme sans fiche de personne ;
  - conflit d'identifiants : l'IdRef de ScanR désigne une autre personne que l'identifiant HAL.
- [ ] Deux contributions rattachées par le rejeu de la décision restent orphelines après le run du 2026-11-20 (Cosserant, Clement). Vérifier au run suivant.

### Phase 5 — Contributions des brevets

L'indice de périmètre « déposant du brevet » va à tous les inventeurs de la famille. HAL donne par défaut le rôle d'auteur aux inventeurs. Ce rôle permettait à un co-inventeur extérieur de fonder une personne : 56 personnes sans fiche RH au 2026-11-19.

- [x] Une contribution d'une publication de type brevet a le seul rôle inventeur (`ROLE_BY_DOC_TYPE`). La décision du rattachement juge la création d'une personne sur les rôles de la contribution. Un changement de type de la publication remet ses contributions en recomposition.
- [x] Remise en file des 410 contributions de brevet au rôle d'auteur (`requeue_doc_type_roles`), puis `run_pipeline --from author_grouping`.

### Phase 6 — Documentation

- [ ] Mise à jour de la documentation du rattachement des personnes.

## Questions ouvertes

- Deux coauteurs homonymes de même graphie dans un enregistrement : critère qui les distingue d'un auteur listé deux fois.
