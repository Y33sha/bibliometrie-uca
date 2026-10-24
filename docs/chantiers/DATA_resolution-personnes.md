# Chantier — Résolution des personnes par groupe

## Contexte

La phase `author_grouping` réunit les contributions sources d'un même auteur d'une publication (`source_contribution_groups`). La cascade des personnes rattache chaque contribution source à une personne. Elle se sert des groupes seulement pour propager une personne d'une contribution source aux autres contributions sources du groupe.

`source_contribution_groups` et `contributions` font double emploi : les deux tables relient un auteur d'une publication à une personne.

L'affiliation sert seulement à délimiter le périmètre. Une forme de nom partagée par deux personnes laisse la contribution source sans personne. Les affiliations fausses des sources, qui créent de fausses personnes du périmètre, relèvent du chantier [vérification des affiliations](DATA_verification-affiliations.md).

La résolution probabiliste relève du chantier [résolution probabiliste des personnes](DATA_resolution-personnes-probabiliste.md).

## Décisions

- `source_contribution_groups` remplace `contributions`. Une contribution est un groupe dont `person_id` est renseigné. `person_id` et `resolution_mode` quittent `source_contributions`.
- Une contribution source sans jumelle forme un groupe à elle seule. Les contributions sources collectives et celles des enregistrements sources écartés de l'alignement restent hors groupe. Elles sont exclues de la résolution des personnes et restent sans personne.
- Seules les versions d'un concept (`DATACITE_VERSION_TO_CONCEPT`) et les pièces d'un jeu de données (`DATACITE_PACKAGE_PIECE`) sont écartées de l'alignement, quelle que soit la source de l'enregistrement source. La copie d'un article dans un repository (`DATACITE_VARIANT_TO_PRIMARY`) entre dans l'alignement : sur la publication la plus lourde du stock, le surcoût est de 0,8 s. Un enregistrement source scanR issu d'un dépôt HAL présent entre dans l'alignement : il porte des identifiants absents du dépôt HAL.
- Les changements irréversibles du schéma passent en dernier, après l'étude de leurs conséquences.
- La cascade décide par groupe. Elle cherche les indices de périmètre du groupe, puis rattache le groupe à une personne existante.
- Le périmètre d'un groupe est l'union des indices de ses contributions sources (`perimeter_evidence` : adresse, ROR, structure HAL, fiche RH, thèse). Sur une contribution source, un ROR attaché à une adresse compte seulement si l'adresse est rattachée à une structure du périmètre (`source_contribution_structures`).
- Le rattachement d'un groupe à une personne est figé tant que ses membres restent les mêmes. Un groupe dont les membres changent est réévalué.
- `source_contribution_groups.resolution_mode` a sa propre enum, `group_resolution_mode` : `manual`, `orcid`, `hal_person_id`, `idref`, `name`, `compatible_name`.
- Pendant la transition, la cascade des groupes écrit seulement la personne des groupes, sans créer de personne. L'ancienne cascade tient `source_contributions.person_id` jusqu'à la bascule des lecteurs ; les écarts entre les deux signalent des conflits. Entre le gel de `source_contributions.person_id` et la création par les groupes, aucune cascade ne crée de personne.
- Les décisions humaines visent des entités stables et se propagent au groupe :
  - l'épinglage d'une contribution source rattache son groupe ;
  - le rejet d'un couple (enregistrement source, personne) interdit de lier la personne à la publication de l'enregistrement source, donc à tout groupe de cette publication.
- **Rejet d'un identifiant ou d'une forme de nom.** Un identifiant ou une forme de nom est rejeté pour une personne. Les groupes non manuels rattachés par ce type d'identifiant, ou par le nom, dont un membre porte la valeur rejetée, redeviennent orphelins tout de suite. Le run suivant les résout sans cette valeur, par le nom s'ils sont du périmètre, ou par un autre identifiant du groupe.
- **Épinglage.** L'épinglage d'une contribution source rattache son groupe à la personne épinglée, à la place d'une personne non manuelle. Un autre groupe non manuel de la même personne dans la publication redevient orphelin.
- **Orphelins.** Un orphelin est un groupe du périmètre sans personne, avec un rôle d'auteur. L'attribution vise un groupe. Une contribution source hors groupe n'est pas attribuable.
- **Personnes supprimées.** Une personne sans contribution du périmètre, sans fiche RH et sans décision humaine est supprimée ; ses groupes redeviennent orphelins.
- **Formes de nom d'une personne.** Elles viennent des membres de ses groupes.
- Une décision de l'administration recalcule aussitôt le périmètre des publications touchées.
- Les variantes de la cascade s'évaluent hors pipeline, sur le jeu d'évaluation de la phase 1.

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

### Phase 2 — Audit des consommateurs

- [x] Lecteurs et écrivains de `contributions`, de `source_contributions.person_id` et de `source_contributions.resolution_mode`, le 2026-10-21 : environ 100 fichiers hors documentation, dont 50 de tests. Environ 14 requêtes écrivent `source_contributions.person_id`, 4 écrivent `contributions`. Seule la fusion de personnes écrit `source_contribution_groups.person_id`. Aucune clé étrangère ne vise `contributions.id`.

### Phase 3 — Enregistrements sources écartés de l'alignement

- [x] Mesure de ce que leurs contributions sources apportent seules, le 2026-10-21. Hors collectifs, 3 134 000 contributions sources de 36 100 enregistrements sources sont hors groupe. Ce sont les doublons d'auteur (`duplicate_of`, sans personne) et les contributions sources des enregistrements sources écartés : DOI convergé, toutes sources (8 700 enregistrements sources, dont 4 900 DataCite et 3 500 OpenAlex), ou scanR issu d'un dépôt HAL présent (26 500).

  | Enregistrements sources écartés | Contributions sources | Avec personne | Couples (publication, personne) absents des groupes | Publications du périmètre par eux seuls |
  |---|---|---|---|---|
  | DataCite, DOI convergé | 2 732 000 | 81 700 | 17 474 | 5 |
  | OpenAlex, DOI convergé | 274 000 | 22 800 | 2 601 | 21 |
  | HAL, DOI convergé | 1 197 | 664 | 92 | 76 |
  | scanR issu d'un dépôt HAL | 104 800 | 51 400 | 2 104 | 148 |
  | WoS, DOI convergé | 1 | 1 | 0 | 1 |

  - 1 400 de ces enregistrements sources sont dans des publications marquées `contributions_dirty`.
  - Pertes du périmètre, personnes exclues écartées : 1 203 couples (publication, personne) du périmètre, dont 286 de personnes RH (271 par scanR issu de HAL) ; 88 personnes du périmètre sans aucune contribution source groupée (51 par OpenAlex au DOI convergé, 37 par scanR issu de HAL).
- [x] Mesure après la réintroduction des copies et de scanR issu de HAL, le 2026-10-22 (`measure_ungrouped.py`). Hors collectifs, 82 600 contributions sources sont hors groupe : 27 800 doublons d'auteur, 54 800 des enregistrements sources écartés (DataCite et OpenAlex surtout). 14 300 ont une personne, dont 9 épinglées. 22 couples (publication, personne) reposent sur elles seules. Pertes du périmètre : 32 couples, dont 3 de personnes RH ; 4 personnes ; 17 publications.
- [x] Relecture des pertes du périmètre (`build_ungrouped_review.py`). Premiers verdicts du 2026-10-21, avant la mesure du 2026-10-22 :
  - DOI convergé : indice de périmètre faux dans 33 couples sur 36 hors personnes RH, dont 20 des 21 personnes perdues d'OpenAlex. La perte est bénéfique.
  - scanR issu de HAL : indice juste pour les 28 personnes RH. Dans 50 fiches sur 54, la contribution source HAL du groupe est sans personne. La copie scanR porte l'IdRef, souvent l'ORCID, absents du dépôt HAL.
- [x] Copies d'un article dans un repository réintroduites dans l'alignement : 1 569 enregistrements sources, 2 951 000 contributions sources.
- [x] Enregistrements sources scanR issus d'un dépôt HAL présent réintroduits dans l'alignement.
- [x] Règle par nom de l'alignement : groupes liés et groupes par clé calculés une fois par enregistrement source, le 2026-10-22. Sur 3 000 publications, les groupes sont inchangés et le second passage tombe de 3,4 s à 0,3 s.
- [x] Contributions sources hors groupe exclues de la résolution des personnes.

### Phase 4 — Essais d'une cascade par groupe

- [x] Périmètre du groupe, par l'union des indices de ses contributions sources. 02f69c43b
- [x] Une décision par groupe, sur les signaux réunis de ses contributions sources (`domain/persons/group_matching.py`). 02f69c43b
  - Exécution à blanc le 2026-10-22 (`shadow_group_cascade.py`), sur les 464 227 groupes qui ont un membre du périmètre ou rattaché : 456 915 identiques au rattachement actuel, 6 119 toujours sans personne (5 951 jurys de thèse), 849 rattachements perdus, 266 conflits actuels tranchés, 73 rattachements gagnés, 3 autres personnes, 2 créations. L'index des personnes vient en partie des rattachements actuels, donc l'accord est surestimé.
  - Rattachements perdus : surtout des rattachements par un ORCID rejeté pour la personne, et des rattachements par le nom de groupes sortis du périmètre. Les 71 conflits de nom sont des doublons de personnes (« Zheng-Ze » et « Zhengze » Zhu), des fautes de source (« Buoef-Gibot » dans WoS) ou des erreurs de groupement.
  - Conflits actuels tranchés : membres rattachés à deux personnes par l'ancrage entre sources ; la décision suit l'identifiant ou l'épinglage.
  - Rattachements gagnés : nom complet d'un membre hors périmètre dans un groupe que l'adresse OpenAlex d'un autre membre met dans le périmètre.
  - Essai écarté : refuser un identifiant quand un membre de même nom de famille, au prénom complet, contredit sa personne. Un refus juste sur deux : diminutifs (Bob et Robert), translittérations (Kuleshov), fautes de source.
- [ ] Critère d'affiliation : les structures du groupe confrontées à celles des autres publications de chaque candidat. Il départage les homonymes et les identifiants contradictoires.
- [x] Une personne par groupe au plus, par construction.
- [x] Dans une publication, un groupe par personne au plus (`settle_publication`), y compris face aux groupes déjà rattachés. 8bd161212 a6e809b3d 1 527 couples (publication, personne) portés par plusieurs groupes : 779 auteurs répétés dans une liste (Fauchon aux positions 0, 1, 14 et 15 chez OpenAlex), 748 personnes qui portent les identifiants de deux chercheurs (Manea et Manna).
- [ ] Évaluation des variantes sur le jeu de la phase 1, dans `data/experiments/resolution-personnes/` (non versionné).

### Phase 5 — Migration du schéma

Les étapes A à C sont réversibles : `contributions` et `source_contributions.person_id` restent tenus à jour. L'étape D est irréversible.

#### Étape A — Personne sur le groupe, en double écriture

- [x] Colonnes de `contributions` ajoutées aux groupes : `is_corresponding`, `roles`, `perimeter_evidence`, `in_perimeter`, recomposés depuis les membres par la tâche `author_grouping.attributes`. `reference_position` tient lieu d'`author_position`. d21f109fc
- [x] Contrainte CHECK : `resolution_mode` est renseigné si et seulement si `person_id` l'est. La purge vide les groupes d'une personne avant de la supprimer. 4f7e62b73
- [x] Tâche `persons.resolve_groups`, après la purge : la décision par groupe rattache les groupes sans personne à une personne existante, sans créer de personne. L'ancienne cascade tient `source_contributions.person_id`. a6e809b3d
- [x] Réévaluation des groupes recomposés : `author_grouping` vide la personne d'un groupe dont les membres changent. c352def57
- [x] Écart entre les groupes et `contributions`, le 2026-10-22 après deux runs : 473 600 couples (publication, personne) des deux côtés, 860 seulement dans `contributions`, 79 seulement dans les groupes.
  - 735 groupes sans personne : fausses personnes du périmètre ancrées par le seul nom d'un membre aujourd'hui hors périmètre, identifiants rejetés pour la personne, conflits de nom ou d'identifiant, formes de nom devenues ambiguës.
  - 125 groupes rattachés à une autre personne : doublons de personnes nés de fautes de source (« Ren Lavigne », « Malys Clinchamps », accents perdus ou en notation LaTeX), que le groupe départage par identifiant. 406 épinglages en bloc de « Zhang, M. » et « Xu, Z. » à Maolin Zhang et Zehua Xu, qui imposaient leur personne à des groupes d'autres chercheurs, ont été supprimés.

#### Étape B — Bascule des lecteurs

- [x] Matviews des structures calculées par les membres des groupes : `group_structures` remplace `contribution_structures`, `publication_structures` lit les groupes. 2e6ee5782 f7d53ca45
- [x] Read models, API, frontend, scripts `report_open_science` et `snapshot_perimeter`. `contribution_id` et `PATCH /api/contributions/{contribution_id}/exclude` désignent un groupe. Les lecteurs liés à un écrivain de `source_contributions.person_id` (orphelins, formes de nom, conflits d'identifiants) et la purge des publications restent sur l'ancienne table jusqu'à l'étape C. 4e1e81472
- [x] Compteurs `source_contribution_count` et `in_perimeter_source_contribution_count` de l'API personnes renommés `contribution_count` et `in_perimeter_contribution_count`. 4e1e81472

#### Étape C — Bascule des écrivains

- [x] Décisions humaines propagées au groupe : épinglage, attribution d'un orphelin, détachement, rejet, statut d'une forme de nom, fusion. L'exclusion d'une personne laisse ses groupes ; le périmètre des publications l'écarte. Le périmètre des publications touchées est recalculé aussitôt. 4e1e81472 250e73ff4 bc94685f2
- [x] Invalidation des rattachements au rejet d'un identifiant ou d'une forme de nom. bc94685f2 Au 2026-10-20, 836 contributions sources non épinglées de 39 personnes sont rattachées par un identifiant rejeté pour leur personne, sans autre identifiant valide. Elles ancrent 2 223 rattachements entre sources.
- [x] La cascade par groupe écrit seulement le groupe. a6e809b3d
- [ ] La phase `contributions` cesse de construire la table `contributions`.
- [ ] `source_contributions.person_id` figé et comparé aux groupes sur plusieurs runs. L'ancienne cascade cesse de créer des personnes.
- [ ] La cascade par groupe crée les personnes des groupes du périmètre restés sans personne, sur un index tenu à jour après chaque création.

#### Étape D — Suppressions

- [ ] Décisions humaines contradictoires entre les groupes et `contributions` recherchées et tranchées.
- [ ] Suppression de `contributions`, de `source_contributions.person_id` et `resolution_mode`, de leurs index et de leurs statistiques. Perte : la personne de chaque contribution source et le mode de son rattachement.
- [ ] Scripts ponctuels qui écrivent ces colonnes supprimés.
- [ ] `source_contribution_groups` renommée `contributions`.

### Phase 6 — Règles de la résolution dans le domaine

- [x] Une entrée de domaine rend la décision complète d'un groupe (`decide_group`). Elle lit un index de personnes en mémoire et renvoie les refus de corroboration. 02f69c43b
- [ ] L'index est mis à jour après chaque écriture (formes de nom, homonymes par nom de famille), quand la cascade des groupes crée des personnes.
- [ ] `NameFormDecision` et `PersonMatchDecision` fusionnent, avec la disparition de l'ancienne cascade.
- [x] Règles assemblées par `pipeline/transformation/persons/cascade.py`, reprises par `decide_group` : ORCID des seules sources à dépôt par l'auteur (`trusted_identifier`), personnes rejetées pour la publication, nom seul sans effet hors périmètre. 02f69c43b
- [ ] Verdict d'une forme de nom calculé en Python sur `AttributionStatus` ; `fetch_name_form_status_map` rend les faits bruts.

### Phase 7 — Correction du stock

- [ ] Doubles rattachements (une personne rattachée à deux contributions sources d'un même enregistrement source), personnes qui ont les identifiants de deux personnes, ORCID en attente rattachés à une autre personne que leur titulaire (21 groupes dans la relecture du 2026-10-19).

### Phase 8 — Fin de chantier

- [ ] Mise à jour de la documentation.

## Questions ouvertes

- Scénarios qui changent la personne d'un groupe sans décision humaine : lesquels, et faut-il les autoriser ?
- Recalcul immédiat des groupes invalidés par une décision de l'administration, exposé par le pipeline (`pipeline/public.py`) sur un index réduit aux valeurs de leurs membres.
- Erreurs des sources révélées par un groupe : groupement, nom, identifiant, affiliation. Des contributions sources d'un même groupe qui désigneraient seules des personnes différentes signalent une erreur. Il faut un outil de repérage dans l'administration, comme pour les fusions douteuses de publications. Les affiliations conflictuelles relèvent du chantier [vérification des affiliations](DATA_verification-affiliations.md). Le conflit se calcule à la demande, ou se lit sur un `person_id` dénormalisé sur `source_contributions`.
- Scission d'un groupe par une décision humaine, quand deux de ses contributions sources désignent deux personnes.
- Nom de `source_contribution_group_members` quand `source_contribution_groups` prend le nom `contributions`.
- Deux idées de ReCiter : enregistrer ce qui a concordé et pas seulement la règle ; réutiliser les confirmations et les rejets d'une personne comme indices pour ses autres groupes.
