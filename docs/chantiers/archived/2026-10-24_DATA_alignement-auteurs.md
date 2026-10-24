# Chantier — Alignement des auteurs d'une publication

## Contexte

Une publication réunit les enregistrements sources de plusieurs sources. Chaque enregistrement source a ses contributions sources (`source_contributions`). Aucune table ne dit quelles contributions sources d'enregistrements sources différentes désignent le même auteur.

Le rapprochement passe aujourd'hui par la personne. La phase `persons` rattache chaque contribution source à une personne, puis `contributions` consolide par paire (publication, personne). Le rattachement cross-source reconnaît une personne déjà liée à la même position d'auteur dans un autre enregistrement source, si le nom est compatible.

La position est un indice faible. Au-delà d'un certain nombre d'auteurs, les écarts de position entre sources sont la règle : ordres différents, listes partielles, noms de collectifs.

Un niveau « auteur de la publication », indépendant de l'identification des personnes, servirait :

- l'identification des personnes : les identifiants de toutes les sources se réunissent avant toute décision, et la décision se prend une fois par auteur ;
- le contrôle de la déduplication des publications : des enregistrements sources dont les listes d'auteurs ne s'alignent pas signalent une fusion suspecte (onglet « Recouvrement d'auteurs » de `METIER_gestion-admin-des-publications.md`) ;
- la détection des erreurs d'affiliation : un même auteur rattaché au périmètre par une source et ailleurs par une autre ;
- la consolidation du périmètre par auteur (`archived/2026-10-16_DATA_perimetre.md`).

### Mesure

Mesure du 2026-10-15 (`interfaces/cli/oneshot/measure_author_alignment.py`), sur les publications à enregistrements sources d'au moins deux sources, hors theses.fr : toutes jusqu'à 500 auteurs, 150 tirées au hasard au-delà. Chaque paire d'enregistrements sources de sources différentes compare la liste la plus courte à la plus longue. Une contribution source est « décalée » quand un nom compatible (`names_compatible`) figure à une autre position, « absente » quand aucun ne figure.

| Auteurs | Longueurs égales | Même position | Décalée | Absente | Identifiant partagé à la même position |
|---|---|---|---|---|---|
| 1-5 | 99,4 % | 99,5 % | 0,4 % | 0,1 % | 98,9 % |
| 6-10 | 95,4 % | 98,3 % | 1,2 % | 0,5 % | 98,9 % |
| 11-20 | 94,8 % | 98,6 % | 1,2 % | 0,3 % | 98,8 % |
| 21-50 | 86,8 % | 95,9 % | 3,8 % | 0,3 % | 96,7 % |
| 51-100 | 38,1 % | 87,1 % | 12,1 % | 0,8 % | 95,9 % |
| 101-500 | 32,2 % | 75,9 % | 23,8 % | 0,3 % | 87,4 % |
| plus de 500 | 22,2 % | 38,1 % | 60,7 % | 1,2 % | 60,2 % |

- Le nom retrouve presque toujours l'auteur ailleurs dans l'autre liste : au-delà de 50 auteurs, l'écart est un ordre différent, rarement un auteur manquant.
- Deux contributions sources qui partagent un identifiant fort ont toujours des noms compatibles (100 % dans chaque tranche).
- Deux contributions sources à la même position ont parfois deux valeurs différentes d'un même type d'identifiant avec des noms compatibles : environ 800 cas par tranche jusqu'à 50 auteurs. Ce sont des identifiants faux ou multiples pour une même personne.
- Par paire de sources, la position s'accorde le mieux avec scanR (93 à 97 %), dont les listes s'arrêtent à 51 auteurs, et le moins avec WoS et DataCite.
- Désaccords relevés dans les listes courtes : ordre différent entre sources, collectif d'auteurs inséré dans la liste, prénom différent à la même position (« Maxime » / « Martine Tisserant »), faute de deux lettres (« Pereira » / « Peirrera »), listes sans rapport, signe d'une fusion de publications erronée.
- Un enregistrement source scanR à identifiant `hal…` ou un enregistrement source OpenAlex dont la location principale est HAL recopie le dépôt HAL. Sans ces paires, l'accord de la position varie d'un point au plus par tranche.
- Une contribution source décalée trouve plusieurs noms compatibles dans 1 à 4 % des cas, et dans 8 % des cas entre 51 et 100 auteurs.
- Un enregistrement source scanR recopié d'un dépôt HAL reprend sa liste entière dans 24 020 cas sur 24 372, mesure du 2026-10-17. Dans les 352 autres, la liste s'arrête à 51 auteurs (305 cas). Elle répète les 10 premiers auteurs aux positions 10 à 19 (346 cas), puis garde une partie des suivants. Au-delà du dixième auteur, scanR garde 39 % des auteurs qui ont un compte HAL et 1,7 % des autres (exemple : hal-05503063).

| Source | Positions en désaccord | Source qui s'écarte |
|---|---|---|
| HAL | 5 507 | 37,9 % |
| Crossref | 5 585 | 26,4 % |
| WoS | 2 955 | 15,8 % |
| DataCite | 3 225 | 12,7 % |
| OpenAlex | 6 094 | 2,0 % |
| scanR | 646 | 1,5 % |

Le tableau compte les positions communes à trois sources indépendantes ou plus, au même nom de famille, dont les prénoms sont incompatibles. La source qui s'écarte a un prénom incompatible avec tous les autres, eux compatibles entre eux. 1 529 positions sont sans source unique qui s'écarte. HAL s'écarte le plus souvent, Crossref ensuite. scanR et OpenAlex partagent une partie de leurs données, donc le vote peut les favoriser.

### Doubles rattachements

Mesure du 2026-10-16. Dans 2 931 enregistrements sources, une même personne est rattachée à deux contributions sources d'auteur ou plus : 4 273 cas, 260 personnes. Exemple : dans l'enregistrement source OpenAlex W4411690674, « k ma » et « k maj », deux co-auteurs aux ORCID distincts, sont rattachés à la même personne.

| Source | Mode de résolution | Contributions sources |
|---|---|---|
| Crossref | `identifier` | 1 926 |
| OpenAlex | `identifier` | 1 742 |
| HAL | `cross_source` | 1 323 |
| WoS | `cross_source` | 672 |
| OpenAlex | `name` | 525 |
| HAL | `name` | 464 |

Un ORCID décalé dans Crossref rattache une contribution source à la personne d'un co-auteur, qui reçoit alors deux ORCID. Les contributions sources qui contiennent l'un ou l'autre s'y rattachent par identifiant, d'autres par forme de nom. OpenAlex reproduit Crossref. HAL est contaminé ensuite par le rattachement `cross_source`.

### Identifiants contradictoires

Mesure du 2026-10-16 : couples (publication, personne) dont les contributions sources contiennent deux valeurs d'un même identifiant fort non neutralisé, sur 398 405 couples.

| Type | Dans un même enregistrement source | Cas | Personnes |
|---|---|---|---|
| ORCID | oui | 1 073 | 18 |
| ORCID | non | 583 | 127 |
| IdRef | non | 368 | 58 |
| IdRef | oui | 2 | 2 |
| idHAL | non | 5 | 4 |

- Dans une même notice, la contradiction est un double rattachement.
- Entre sources, une partie est légitime : une personne a deux IdRef (Antoine Vacavant, Céline Guillot : un IdRef dans HAL, un autre dans scanR) ou deux comptes ORCID (Marie-Ange Mouret-Reynier). Une autre partie réunit deux personnes : « Ana Raquel Marques » et « Ana Luisa Marques ».

### Synchronisation des contributions sources

La renormalisation d'un enregistrement source rapproche ses contributions sources de celles en base par informations du contributeur : nom normalisé et identifiants. Une contribution source dont les identifiants changent est supprimée, puis insérée sans personne, et la résolution la reprend.

Les verdicts manuels sur les contributions sources ont deux ancrages :

- le détachement (`rejected_contributions`) vise un couple (enregistrement source, personne) et s'applique à toute la publication : il résiste à la resynchronisation des contributions sources ;
- le rattachement manuel d'une contribution source orpheline (`confirmed_source_contributions`) vise l'identifiant de la contribution source, en `ON DELETE CASCADE` : il disparaît quand les identifiants de la contribution source changent.

## Décisions

- L'alignement se fait par publication, avant la phase `persons`.
- Un identifiant fort (ORCID, IdRef, idHAL) non neutralisé réunit deux contributions sources qui le partagent.
- La méthode se choisit d'après une mesure du stock, faite hors pipeline.
- `source_contribution_groups` réunit les contributions sources d'un même auteur dans une publication : `publication_id`, `person_id`, `resolution_mode`, `reference_position` (position dans la liste la plus longue). `person_id` et `resolution_mode` quittent `source_contributions` dans le chantier de [résolution des personnes](2026-10-24_DATA_resolution-personnes.md).
- `source_contribution_group_members` relie chaque contribution source à son groupe : `source_contribution_id` (clé primaire), `group_id`, `source_record_id`, `method`, `score`, `margin`.
  - `method` : `reference` (la contribution source fonde le groupe), `name`, `identifier`, `order`, `model`.
  - `score` et `margin`, en bits, pour `model` seulement : poids de Fellegi-Sunter du lien, et écart à la meilleure autre possibilité dans l'affectation hongroise.
- Un groupe réunit au plus une contribution source par enregistrement source. Une personne correspond au plus à un groupe par publication.
- Les groupes d'une publication se recalculent entièrement quand un de ses enregistrements sources arrive, part ou change ses contributions sources : le résultat ne dépend pas de l'ordre d'arrivée des enregistrements sources. `publications.contributions_dirty` marque les publications à recalculer. La réconciliation de `publications` le pose sur les publications touchées : celles qui reçoivent un enregistrement source réexaminé, et celles qu'un enregistrement source quitte. Un enregistrement source réécrit par `normalize`, contributions sources comprises, est réexaminé. La phase des groupes retire le drapeau.
- La phase des groupes, entre `publications` et `persons`, écrit seulement les deux tables des groupes. La phase `persons` garde sa cascade, à une exception : le rattachement `cross_source` devient une propagation dans le groupe. La résolution des personnes par groupe relève d'un chantier à part.
- Après le recalcul, chaque groupe reprend l'identifiant de l'ancien groupe avec lequel il partage le plus de contributions sources, chaque ancien identifiant une seule fois, le plus petit en cas d'égalité. `person_id` et `resolution_mode` suivent l'identifiant. Un ancien groupe sans correspondant est supprimé.
- Les verdicts restent ancrés sur les données sources : une contribution source dont les identifiants changent est supprimée puis réinsérée.
- Les groupes rattachés à une personne forment les couples (publication, personne) de `contributions`. `source_contribution_groups` remplace `contributions`, matviews comprises, dans le chantier de résolution des personnes.

## Phasage

### Phase 1 — Mesure

- [x] Publications à plusieurs enregistrements sources : nombre de contributions sources par enregistrement source, écarts de longueur entre listes.
- [x] Accord de la position : part des contributions sources dont le nom est compatible avec celui de la même position dans un autre enregistrement source, selon le nombre d'auteurs.
- [x] Accord des identifiants : paires de contributions sources réunies ou séparées par un identifiant fort, confrontées à la position et au nom.
- [x] Échantillon de désaccords de position relu à la main : 100 cas tirés de `data/measures/author_alignment_disagreements.csv`, 2026-10-17. Même auteur à une autre position : 50. Fusion erronée de deux publications : 21 cas, sur 12 publications. Autre personne : 10. Nom écrit autrement : 8. Auteur absent de l'autre liste : 6. Collectif : 4. Indéterminable : 1.
  - Les 21 cas jugés « fusion erronée » couvrent 12 publications, de quatre profils.
  - Communications d'un volume d'actes ou de résumés réunies sous le DOI du volume : 3 publications (IFORS 2023, ECO 2024, EAPC 2023). Corrigé par `ACTES_VS_COMMUNICATION`.
  - DOI gabarit d'Optica `10.1364/ao.xx.xxxxxx` sur 9 dépôts HAL : 1 publication (14441). La règle des DOI inconnus de doi.org le retirera.
  - Dépôt HAL au DOI d'un autre article : 2 publications (139772, 169584). Sur le stock, 135 dépôts HAL sur 28 675 n'ont aucun nom d'auteur en commun avec l'enregistrement source Crossref de leur DOI, dont 41 de titre différent.
  - Même publication, listes d'auteurs partielles : 6 publications, 8 cas. ScanR coupe à 51 auteurs ; HAL liste parfois les seuls auteurs locaux (vérifié sur 240985). Les fusions erronées sont donc 13 cas sur 100.
- [x] Prénom incompatible à la même position : source qui s'écarte de la majorité, sur les publications à trois enregistrements sources ou plus.
- [x] Échantillon des positions où HAL s'écarte, relu à la main : 100 cas, 2026-10-17. HAL a raison dans 38 cas : diminutif (Tony pour A. A. Affolder), initiale composée (Ch., Ph.), translittération (Ia), variante nationale (André pour Andrzej), erreur des autres sources. La liste HAL est décalée dans 31 cas. Le compte HAL est faux dans 20 cas, le plus souvent une faute de saisie sur un auteur sans compte ; parfois le bon compte a une forme différente (Joël J. Drevet pour Joël R. Drevet). 9 cas restent indéterminables.
- [x] Sources dépendantes : accord mesuré sans les paires où un enregistrement source recopie l'autre (enregistrement source scanR issu d'un dépôt HAL, enregistrement source OpenAlex dont la location principale est HAL).
- [x] Ambiguïté des appariements par nom : nombre de noms compatibles par contribution source décalée, dans les grandes listes.
- [x] Doubles rattachements : contributions sources d'un même enregistrement source rattaché à la même personne.
- [x] Identifiants contradictoires au sein d'un couple (publication, personne).
- [x] Échantillon des identifiants contradictoires entre sources, relu à la main : 78 paires ORCID et IdRef, 2026-10-17. Une différence de `hal_person_id` n'est pas une contradiction : une personne a souvent plusieurs comptes HAL.
  - Identifiant erroné dans une source : 39 (ScanR 18, HAL 14, Crossref et OpenAlex 5, IdRef supprimé ou indéterminé 2). ScanR attribue l'identifiant d'un homonyme. Dans Crossref, l'ORCID erroné est celui d'un co-auteur.
  - Même personne, deux identifiants : 30. Pour l'IdRef, un doublon, souvent redirigé. Pour l'ORCID, un compte vide ou désactivé.
  - Indéterminable : 9.
- [x] Liens au périmètre établis par la seule contribution source scanR : 5 735 couples (publication, personne), dont 100 relus à la main, 2026-10-17.

  | Indice de périmètre de scanR | Couples | Relus | À juste titre | À tort | Indéterminable |
  |---|---|---|---|---|---|
  | identité RH, autres sources présentes | 2 268 | 40 | 31 | 5 | 4 |
  | identité RH, scanR seul | 1 815 | 20 | 19 | 0 | 1 |
  | structure HAL ou ROR | 1 314 | 25 | 9 | 12 | 4 |
  | adresse | 338 | 15 | 5 | 10 | 0 |

  - Structure : 11 erreurs sur 12 sont des publications de collaborations de 1 000 à 3 000 auteurs. scanR y donne la structure ou le ROR à des auteurs extérieurs. La contribution source HAL de ces auteurs n'a aucune structure, dans les cas justes comme dans les cas faux.
  - Adresse : scanR attribue à l'auteur les adresses d'autres auteurs, jusqu'à 16 par contribution source, ou des blocs mal découpés.
  - Fiche RH : les 5 erreurs sont des contributions sources à l'initiale, rapprochées d'un homonyme RH de même initiale.
  - 21 des 31 couples justes de la première strate ont une adresse OpenAlex au CHU de Clermont.
  - Priorité simulée sur les contributions sources appariées par nom et position : l'adresse OpenAlex prime, puis celle de WoS, puis les indices de scanR. Strate adresse : 9 erreurs sur 10 retirées, aucun couple juste perdu. Strate structure : 6 erreurs sur 12 retirées, 1 couple juste perdu.
- [x] IdRef attribués par la seule contribution source scanR : 3 660, comparés à leur notice IdRef, dont 100 relus à la main, 2026-10-17. 3 650 notices trouvées, 162 de nom incompatible avec la personne.

  | Strate | IdRef | Relus | IdRef de la personne | Homonyme | Prénom différent | Indéterminable |
  |---|---|---|---|---|---|---|
  | nom incompatible | 162 | 30 | 0 | 3 | 27 | 0 |
  | nom compatible | 3 488 | 60 | 54 | 4 | 2 | 0 |
  | IdRef introuvable | 10 | 10 | 8 | 0 | 0 | 2 |

  - Un nom incompatible signale un IdRef faux. Un nom compatible laisse passer les homonymes, environ 10 %. Les prénoms différents de cette strate sont réduits à l'initiale dans la contribution source.
  - 9 des 10 IdRef introuvables sont fusionnés : la page IdRef redirige vers un autre numéro, la recherche Solr ne les rend pas. Le dernier est supprimé.

### Phase 2 — Méthode et modèle

- [x] Méthode d'alignement, choisie d'après la mesure : une règle de noms, puis un modèle de Fellegi-Sunter sur le résidu. Essais des 17 et 18 octobre 2026, dans `data/experiments/alignement-auteurs/` (non versionné).
  - Les enregistrements sources se traitent de la plus longue liste à la plus courte, chacune face aux groupes déjà formés : un groupe a au plus une contribution source par enregistrement source. Un enregistrement source scanR recopié d'un dépôt HAL est exclu quand la publication a ce dépôt.
  - Règle, à l'intérieur de chaque patronyme :
    1. patronyme unique des deux côtés ;
    2. patronyme et prénom complet uniques ;
    3. patronyme et initiale uniques ;
    4. ORCID ou IdRef partagé avec un membre du groupe, à patronyme égal ; un identifiant présent dans deux groupes ne lie rien ;
    5. filtre d'ordre : seule la plus longue suite de liens rangés dans le même ordre des deux côtés est gardée, les autres liens passent au résidu ; les liens par identifiant échappent au filtre ;
    6. dans chaque trou entre deux liens, patronyme et initiale en nombre égal des deux côtés : lien dans l'ordre des positions.
  - Prénom connu : un prénom absent ou réduit à des initiales prend la valeur du prénom de la personne à laquelle un humain a rattaché l'ORCID ou l'IdRef de la contribution source, si les initiales concordent. Une décision sur ce rattachement, ou un changement de ce prénom, marque à regrouper les publications des contributions sources qui contiennent l'identifiant.
  - Résidu : modèle de Fellegi-Sunter (Splink), estimé par EM sur les seules contributions sources restantes. Comparaisons : patronyme, prénom, ORCID, IdRef, trou (même trou, trou voisin, ailleurs). Affectation hongroise : un lien est retenu quand les preuves dépassent log2 du nombre de groupes restants. Les poids d'ORCID et d'IdRef viennent d'un modèle estimé sur toutes les paires : sur le résidu, l'EM ne les identifie pas.
  - Le résidu fait 1,9 % des liens jusqu'à 100 auteurs, 10,6 % au-delà.
  - Deux variantes essayées le 2026-10-19, sans gain net sur le stock, donc écartées. Ordre des enregistrements sources par source (theses.fr, Crossref, DataCite, HAL, OpenAlex, WoS, scanR) au lieu de la longueur : 2 paires de plus tranchées comme chacune des deux relectures, effet sur le stock impossible à juger sans relecture. Redécoupage d'un patronyme composé (« c adam / bourdarios » face à « adam bourdarios ») : autant de liens perdus que gagnés.
  - Évaluation sur trois relectures :

    | Méthode | 326 paires de la phase 1 | 97 désaccords entre Fellegi-Sunter et une règle sans filtre d'ordre | 47 écarts de l'hybride au consensus des deux autres |
    |---|---|---|---|
    | Fellegi-Sunter seul, position absolue | 312 | 46 | 33 |
    | Règle sans filtre d'ordre, trous comblés dans l'ordre | 314 | 51 | 33 |
    | Règle, puis Fellegi-Sunter sur le résidu | 315 | 86 | 39 |

  - Fellegi-Sunter seul confond les homonymes des grandes listes (Kim, Zhang). Sans filtre d'ordre, l'étape du patronyme unique lie des auteurs éloignés quand les sources découpent autrement nom et prénom (« A. Ferrer » en position 757, « J. A. Valls Ferrer » en position 2579).
  - Erreurs restantes sur les 326 paires : auteur en double dans un enregistrement source HAL, prénom faux dans HAL, noms différents à la même position, un auteur déplacé, une variante de nom.
  - Limite : trois « Y. Zhang » consécutifs, dans l'ordre inverse chez Crossref et chez HAL. Seuls les noms déclarés dans le registre ORCID les départagent.
- [x] Modèle : `source_contribution_groups` et `source_contribution_group_members`, contraintes d'unicité.
- [x] Temps de calcul de l'essai, en Python sur un cœur : 36 minutes pour le stock (18,6 millions de contributions sources), de 0,4 à 2,2 secondes pour une collaboration d'environ 11 700 contributions sources en 5 enregistrements sources.
- [x] Réconciliation des identifiants de groupes après recalcul.
- [x] Phase `author_grouping`, entre `publications` et `persons`.
- [x] Alignement tous rôles réunis, le 2026-10-19. Rôles séparés, 2 630 paires de groupes au même nom complet restaient à part, dans 1 210 publications : un rôle HAL (contributeur, éditeur, conseiller scientifique) face à l'auteur d'OpenAlex ou de Crossref. Rôles réunis, 3 494 paires se lient et 30 se délient, surtout des liens faux. Une contribution source sans position (jury chez theses.fr) se lie par le nom et l'identifiant, hors du filtre d'ordre, des trous et du résidu. scanR, qui liste une personne une fois par rôle dans une thèse, donne une contribution source par personne, comme theses.fr. Sur 1 000 thèses, 688 paires se lient, aucune ne se délie.
- [x] Poids du modèle du résidu versionnés dans le dépôt. Le pipeline calcule les poids des paires sans Splink.
- [x] Script qui réestime les poids avec Splink (`interfaces/cli/dev/estimate_residual_weights.py`).
- [x] Temps de calcul : lots bornés en nombre de contributions sources, écriture des seules appartenances modifiées, calcul réparti sur les cœurs disponibles (quota du conteneur compris). Un lot de grandes collaborations passe de 9,7 à 4,6 secondes sur deux cœurs.
- [x] Premier passage de la phase sur le stock, le 2026-10-18 : 76 511 publications en une heure environ, 6,3 millions de groupes, 19,9 millions de contributions sources groupées. Liens par le nom : 12,4 millions ; par le modèle : 858 000 ; par l'ordre : 285 000 ; par l'identifiant : 30 000. Évaluation identique à l'essai : 316 paires correctes sur 327, 86 désaccords sur 97 et 39 écarts sur 47 tranchés comme la relecture.

### Phase 3 — Usages

- [x] Rattachement `cross_source` remplacé par la propagation de la personne dans le groupe, quand le groupe en a une seule.
  - Passage de `persons` du 2026-10-18 : les contributions sources sans personne dans un groupe qui en a une passent de 223 829 à 5 695 ; les groupes à plusieurs personnes, de 752 à 431.
  - Relecture de 62 de ces 431 groupes, classés par la méthode la moins sûre parmi leurs membres :

    | Strate | Relus | Doublon de personnes | Erreur de groupement | Erreur de source | Rattachement existant faux | Indéterminé |
    |---|---|---|---|---|---|---|
    | modèle | 30 | 15 | 11 | 1 | 1 | 2 |
    | nom | 20 | 16 | 0 | 4 | 0 | 0 |
    | ordre | 12 | 0 | 3 | 0 | 9 | 0 |

  - Modèle : 9 des 11 erreurs de groupement viennent de deux œuvres distinctes réunies dans une même publication. Une autre vient d'un enregistrement source scanR qui répète un auteur et sert de liste de référence. La dernière vient de noms inversés par quatre sources sur cinq : le niveau « noms inversés » du modèle n'a pas de poids, faute d'estimation par l'EM.
  - Ordre : 7 des 9 rattachements faux concernent un même ORCID, rattaché par identifiant à une autre personne que son titulaire. Les 3 erreurs de groupement sont des homonymes que l'ordre départage à tort, alors que l'ORCID les distingue.
  - Nom : les doublons de personnes viennent d'un prénom absent, réduit ou différent selon la source. Deux erreurs de source sont deux noms concaténés par Crossref.
- [x] Relecture des 346 groupes à plusieurs personnes après les corrections des listes d'auteurs, le 2026-10-19 : 335 jugés, dont 147 verdicts repris des relectures précédentes.

  | Verdict | Groupes |
  |---|---|
  | Doublon de personnes | 202 |
  | Erreur de groupement | 43 |
  | Rattachement existant faux | 28 |
  | Erreur de source | 27 |
  | Fusion erronée de publications | 26 |
  | Indéterminable | 9 |

  - Les erreurs de groupement concernent presque toutes trois homonymes « Z. Xu » d'une collaboration de physique des particules. Les sources ne les rangent pas dans le même ordre, et leur ORCID figure sur une contribution source autre que la référence. La comparaison de l'identifiant à tous les membres du groupe ne suffit pas : la contribution source à initiale a l'ORCID, la contribution source au prénom complet n'en a pas. Le prénom connu sépare 10 des 21 erreurs de la strate ordre ; les autres groupes relus sont justes, ou l'ORCID est en attente de confirmation.
  - 21 rattachements faux viennent d'un ORCID en attente, rattaché à une autre personne que son titulaire.
  - Erreurs de source : noms concaténés par Crossref et WoS, accents LaTeX, rédactions et organismes non reconnus comme collectifs.
  - Accord avec les deux relectures de la phase 2, le 2026-10-19 : 93 paires sur 97 et 40 sur 47. Dans une publication ATLAS, une copie OpenAlex sans DOI d'un dépôt d'archives, plus longue de 38 auteurs, est devenue la liste de référence. Elle écrit autrement les patronymes composés et range les auteurs dans un autre ordre.
- [x] Fusion des doublons de personnes relevés par les relectures : 165 personnes absorbées dans 157 (`data/experiments/alignement-auteurs/person_merges.csv`, non versionné), par `interfaces/cli/oneshot/merge_reviewed_person_duplicates.py`. Deux paires restent hors de la liste. « Blandine Tauleigne Adib Essid » vient d'un nom concaténé par WoS : ses contributions sources désignent deux auteurs. Rosana Lopez et Rosa Ana Lopez Rodriguez sont deux personnes, que HAL confond.
- [x] Enregistrements sources aux noms inversés : un enregistrement source qui intervertit nom et prénom s'aligne avec ses noms remis dans l'ordre. À longueur égale, un enregistrement source scanR passe après les autres et ne fonde un groupe qu'à défaut d'une autre. Sur les jeux relus, 91 désaccords sur 97 sont tranchés comme la relecture, contre 86 ; le reste est inchangé.
- [x] Fusions suspectes : onglet du référentiel des publications de l'UI admin. Il retient les publications dont moins de la moitié des auteurs se retrouvent d'un enregistrement source à l'autre (vue `publication_author_alignment`).
- [x] Comparaison des listes d'auteurs entre sources : elle quitte la page publique d'une publication pour le volet publication de l'UI admin, une ligne par groupe.

### Phase 4 — Diagnostic des listes d'auteurs

- [x] Liste recopiée en tout ou en partie. Relecture de 64 enregistrements sources où un nom complet revient, le 2026-10-18 : sous 10 % de répétitions, 5 vrais homonymes et 3 enregistrements sources indéterminés ; au-delà, 51 listes recopiées et 5 enregistrements sources indéterminés.
  - Signal : au moins deux noms répétés avec le même décalage de position, supérieur à 1. Il trouve 47 des 51 copies et aucun des 5 homonymes, qui sont tous côte à côte (décalage de 1).
  - La longueur ne détecte pas la copie, qui se retrouve dans d'autres sources. Un enregistrement source plus long que la médiane des autres manque 15 copies sur 51 ; un écart avec un autre enregistrement source égal au nombre de répétitions confirme 26 copies sur 51.
  - Conséquence : seule la première occurrence de chaque nom s'aligne. Les répétitions restent hors des groupes, donc hors du rattachement aux personnes.
- [x] Liste doublée sur place (A A B B…) : une suite d'au moins 4 paires côte à côte, de noms différents.
- [x] Copies notées dans `source_contributions.duplicate_of` par la phase `author_grouping`, vers la première occurrence du nom. La phase `persons` détache les copies de leur personne, sauf épinglage. Sur les 64 enregistrements sources relus, 44 des 45 copies qui ont encore des noms répétés sont détectées, et aucun des 5 cas d'homonymes. Sur le stock : 578 enregistrements sources, 21 971 doublons d'auteur.
- [x] Décomptes d'auteurs de chaque enregistrement source : `source_records.author_count` (contributions sources d'auteur individuelles) et `distinct_author_count` (noms complets distincts parmi elles).
- [x] Noms de collectifs : une contribution source dont le nom entier est « et al. » est collective, ainsi qu'un nom d'organisme ou de rédaction (« Die Redaktion », « Editorial Office »). Accents LaTeX décodés dans les noms d'auteur à la normalisation ; un oneshot corrige les 1 421 contributions sources du stock. Encodage réparé de la même façon (UTF-8 lu comme du Latin-1 ou du Windows-1252, Windows-1252 lu comme du GBK) : 2 487 contributions sources du stock, surtout chez OpenAlex.
- [x] Un contributeur HAL ou scanR (`ctb`) est aussi auteur : dans 510 dépôts HAL sur 840 comparables, la longueur des autres enregistrements sources égale le nombre d'auteurs et de contributeurs réunis.
- [x] Classement des écarts de longueur entre les enregistrements sources d'une publication, le 2026-10-18 (`measure_list_gaps.py`). La longueur de référence est la plus fréquente parmi les enregistrements sources. Un enregistrement source scanR issu d'un dépôt HAL est ignoré quand l'enregistrement source HAL de ce dépôt est présent. Sur 69 428 publications à plusieurs enregistrements sources, 62 807 ont des listes de même longueur, 4 091 des écarts expliqués, 88 une fusion erronée probable et 2 441 un écart inexpliqué.
  - Causes reconnues : enregistrement source à un auteur, scanR coupé à 51, homonymes fusionnés par WoS, excédent fait de noms complets répétés, liste tronquée, dépôt HAL in2p3, fusion erronée probable.
  - Liste tronquée : 80 % de ses patronymes figurent parmi les premiers patronymes de la liste longue, et 80 % des patronymes de la suite de la liste longue lui sont absents. Elle se termine souvent par un collectif que l'autre source détaille. La source omet souvent ce collectif.
  - Dépôt HAL `in2p3-*` plus court que la référence, dont 80 % des patronymes figurent dans la référence : il liste les auteurs locaux.
  - Fusion erronée probable : 20 % au plus des patronymes de la liste courte figurent dans la liste longue. La fusion d'une pièce DataCite avec son ensemble échappe à ce critère : la liste de la pièce est contenue dans celle de l'ensemble.
- [x] Relecture de 71 grands écarts (du simple au double au moins), le 2026-10-18 : 23 listes tronquées, 13 fusions erronées, 9 listes recopiées, 7 listes d'auteurs locaux, 4 références fausses, 15 cas indéterminables. Les écarts que les règles laissent sans cause sont des listes partielles (directeurs d'ouvrage, collectif omis) et des listes longues qui contiennent la référence. Ces dernières y ajoutent les membres d'un collectif ou une copie sous d'autres formes de noms ; les répétitions de patronyme et d'initiale ne séparent pas ces deux cas.
### Phase 5 — Suites

Ces items exploitent les groupes ou les affinent. Aucun ne bloque la refonte de la résolution des personnes.

- [x] Rang d'un groupe fondé par une liste plus courte : juste après le groupe de son voisin précédent dans cette liste, le 2026-10-22. Sur 3 000 publications, 1 107 liens passent du modèle à la règle. 316 contributions sources changent de groupe dans 16 grandes collaborations. Les homonymes reprennent leur ordre, mais le modèle lie aussi des voisins aux initiales incompatibles.
- [x] Une paire seule dans un trou, de même patronyme et même initiale, se lie par l'ordre, le 2026-10-22. Sur 3 000 publications, 2 258 liens passent du modèle à l'ordre. 124 contributions sources changent de groupe dans 8 publications : une quinzaine de groupes corrigés, trois groupes d'homonymes mélangés (Li H, Wang Z).
- [x] Poids du modèle du résidu réestimés après le changement de rang des groupes, le 2026-10-22 : poids en place gardés. Les poids réestimés séparent 3 des 83 liens justes de la relecture des liens du modèle, sans écarter de lien faux. D'un export à l'autre, le niveau « jw 0.8 » du patronyme varie de 3 bits.
- [x] Le modèle du résidu écarte deux auteurs aux patronymes seulement proches et aux premières initiales différentes, sauf identifiant commun (`conflicting_initials`), le 2026-10-22. Sur les verdicts de la relecture encore en base, les 78 liens justes restent, les 6 liens faux sont écartés. Sur 3 000 publications, 398 liens du modèle disparaissent ; 40 relus, tous faux, surtout dans des listes WoS divergentes.
- [x] Liste tronquée : elle reprend le début d'une liste plus longue de la même publication. Les enregistrements sources s'alignent de la plus longue à la plus courte, donc elle ne fonde pas les groupes.

### Phase 6 — Fin de chantier

- [x] Mise à jour de la documentation. 12ede2eb8

## Questions ouvertes

- **Lecture anticipée des lots d'`author_grouping`.** Un thread lirait le lot suivant, sur sa propre connexion, pendant le calcul et l'écriture du lot en cours : environ 7 s gagnées par lot de grandes collaborations. Prérequis : supprimer une appartenance par couple (contribution source, groupe). Sinon, la publication de départ d'un enregistrement source déplacé, lue avant le commit du lot qui contient la publication d'arrivée, effacerait la nouvelle appartenance.

Les autres suites de l'alignement se poursuivent dans le chantier [qualité des contributions](../DATA_qualite-des-contributions.md).
