# Chantier — Alignement des auteurs d'une publication

## Contexte

Une publication réunit les notices de plusieurs sources. Chaque notice a ses signatures (`source_authorships`). Aucune table ne dit quelles signatures de notices différentes désignent le même auteur.

Le rapprochement passe aujourd'hui par la personne. La phase `persons` rattache chaque signature à une personne, puis `authorships` consolide par paire (publication, personne). Le rattachement cross-source reconnaît une personne déjà liée à la même position d'auteur dans une autre notice, si le nom est compatible.

La position est un indice faible. Au-delà d'un certain nombre d'auteurs, les écarts de position entre sources sont la règle : ordres différents, listes partielles, noms de collectifs.

Un niveau « auteur de la publication », indépendant de l'identification des personnes, servirait :

- l'identification des personnes : les identifiants de toutes les sources se réunissent avant toute décision, et la décision se prend une fois par auteur ;
- le contrôle de la déduplication des publications : des notices dont les listes d'auteurs ne s'alignent pas signalent une fusion suspecte (onglet « Recouvrement d'auteurs » de `METIER_gestion-admin-des-publications.md`) ;
- la détection des erreurs d'affiliation : un même auteur rattaché au périmètre par une source et ailleurs par une autre ;
- la consolidation du périmètre par auteur (`archived/2026-10-16_DATA_perimetre.md`).

### Mesure

Mesure du 2026-10-15 (`interfaces/cli/oneshot/measure_author_alignment.py`), sur les publications à notices d'au moins deux sources, hors theses.fr : toutes jusqu'à 500 auteurs, 150 tirées au hasard au-delà. Chaque paire de notices de sources différentes compare la liste la plus courte à la plus longue. Une signature est « décalée » quand un nom compatible (`names_compatible`) figure à une autre position, « absente » quand aucun ne figure.

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
- Deux signatures qui partagent un identifiant fort ont toujours des noms compatibles (100 % dans chaque tranche).
- Deux signatures à la même position ont parfois deux valeurs différentes d'un même type d'identifiant avec des noms compatibles : environ 800 cas par tranche jusqu'à 50 auteurs. Ce sont des identifiants faux ou multiples pour une même personne.
- Par paire de sources, la position s'accorde le mieux avec scanR (93 à 97 %), dont les listes s'arrêtent à 51 auteurs, et le moins avec WoS et DataCite.
- Désaccords relevés dans les listes courtes : ordre différent entre sources, collectif d'auteurs inséré dans la liste, prénom différent à la même position (« Maxime » / « Martine Tisserant »), faute de deux lettres (« Pereira » / « Peirrera »), listes sans rapport, signe d'une fusion de publications erronée.
- Une notice scanR à identifiant `hal…` ou une notice OpenAlex dont la location principale est HAL recopie le dépôt HAL. Sans ces paires, l'accord de la position varie d'un point au plus par tranche.
- Une signature décalée trouve plusieurs noms compatibles dans 1 à 4 % des cas, et dans 8 % des cas entre 51 et 100 auteurs.
- Une notice scanR recopiée d'un dépôt HAL reprend sa liste entière dans 24 020 cas sur 24 372, mesure du 2026-10-17. Dans les 352 autres, la liste s'arrête à 51 auteurs (305 cas). Elle répète les 10 premiers auteurs aux positions 10 à 19 (346 cas), puis garde une partie des suivants. Au-delà du dixième auteur, scanR garde 39 % des auteurs qui ont un compte HAL et 1,7 % des autres (exemple : hal-05503063).

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

Mesure du 2026-10-16. Dans 2 931 notices, une même personne est rattachée à deux signatures d'auteur ou plus : 4 273 cas, 260 personnes. Exemple : dans la notice OpenAlex W4411690674, « k ma » et « k maj », deux co-auteurs aux ORCID distincts, sont rattachés à la même personne.

| Source | Mode de résolution | Signatures |
|---|---|---|
| Crossref | `identifier` | 1 926 |
| OpenAlex | `identifier` | 1 742 |
| HAL | `cross_source` | 1 323 |
| WoS | `cross_source` | 672 |
| OpenAlex | `name` | 525 |
| HAL | `name` | 464 |

Un ORCID décalé dans Crossref rattache une signature à la personne d'un co-auteur, qui reçoit alors deux ORCID. Les signatures portant l'un ou l'autre s'y rattachent par identifiant, d'autres par forme de nom. OpenAlex reproduit Crossref. HAL est contaminé ensuite par le rattachement `cross_source`.

### Identifiants contradictoires

Mesure du 2026-10-16 : couples (publication, personne) dont les signatures portent deux valeurs d'un même identifiant fort non neutralisé, sur 398 405 couples.

| Type | Dans une même notice | Cas | Personnes |
|---|---|---|---|
| ORCID | oui | 1 073 | 18 |
| ORCID | non | 583 | 127 |
| IdRef | non | 368 | 58 |
| IdRef | oui | 2 | 2 |
| idHAL | non | 5 | 4 |

- Dans une même notice, la contradiction est un double rattachement.
- Entre sources, une partie est légitime : une personne a deux IdRef (Antoine Vacavant, Céline Guillot : un IdRef dans HAL, un autre dans scanR) ou deux comptes ORCID (Marie-Ange Mouret-Reynier). Une autre partie réunit deux personnes : « Ana Raquel Marques » et « Ana Luisa Marques ».

### Synchronisation des signatures

La renormalisation d'une notice rapproche ses signatures de celles en base par identité : nom normalisé et identifiants. Une signature dont les identifiants changent est supprimée, puis insérée sans personne, et la résolution la reprend.

Les verdicts manuels sur les signatures ont deux ancrages :

- le détachement (`rejected_authorships`) vise un couple (notice, personne) et s'applique à toute la publication : il résiste à la resynchronisation des signatures ;
- le rattachement manuel d'une signature orpheline (`confirmed_authorships`) vise l'identifiant de la signature, en `ON DELETE CASCADE` : il disparaît quand les identifiants de la signature changent.

## Décisions

- L'alignement se fait par publication, avant la phase `persons`.
- Un identifiant fort (ORCID, IdRef, idHAL) non neutralisé réunit deux signatures qui le partagent.
- La méthode se choisit d'après une mesure du stock, faite hors pipeline.
- Une table des auteurs alignés relie les signatures d'un même auteur et porte `person_id`, retiré des `source_authorships`.
- Un auteur aligné réunit au plus une signature par notice. Une personne correspond au plus à un auteur aligné par publication. Les doubles rattachements relèvent de ce chantier.
- Les verdicts restent ancrés sur les données sources, pas sur les auteurs alignés : l'identifiant d'un auteur aligné change à chaque recalcul de l'alignement.
- Une signature dont les identifiants changent marque son auteur aligné à recalculer, et la résolution des personnes le reprend.

## Phasage

### Phase 1 — Mesure

- [x] Publications à plusieurs notices : nombre de signatures par notice, écarts de longueur entre listes.
- [x] Accord de la position : part des signatures dont le nom est compatible avec celui de la même position dans une autre notice, selon le nombre d'auteurs.
- [x] Accord des identifiants : paires de signatures réunies ou séparées par un identifiant fort, confrontées à la position et au nom.
- [x] Échantillon de désaccords de position relu à la main : 100 cas tirés de `data/measures/author_alignment_disagreements.csv`, 2026-10-17. Même auteur à une autre position : 50. Fusion erronée de deux publications : 21 cas, sur 12 publications. Autre personne : 10. Nom écrit autrement : 8. Auteur absent de l'autre liste : 6. Collectif : 4. Indéterminable : 1.
  - Les 21 cas jugés « fusion erronée » couvrent 12 publications, de quatre profils.
  - Communications d'un volume d'actes ou de résumés réunies sous le DOI du volume : 3 publications (IFORS 2023, ECO 2024, EAPC 2023). Corrigé par `ACTES_VS_COMMUNICATION`.
  - DOI gabarit d'Optica `10.1364/ao.xx.xxxxxx` sur 9 dépôts HAL : 1 publication (14441). La règle des DOI inconnus de doi.org le retirera.
  - Dépôt HAL au DOI d'un autre article : 2 publications (139772, 169584). Sur le stock, 135 dépôts HAL sur 28 675 n'ont aucun nom d'auteur en commun avec la notice Crossref de leur DOI, dont 41 de titre différent.
  - Même publication, listes d'auteurs partielles : 6 publications, 8 cas. ScanR coupe à 51 auteurs ; HAL liste parfois les seuls auteurs locaux (vérifié sur 240985). Les fusions erronées sont donc 13 cas sur 100.
- [x] Prénom incompatible à la même position : source qui s'écarte de la majorité, sur les publications à trois notices ou plus.
- [x] Échantillon des positions où HAL s'écarte, relu à la main : 100 cas, 2026-10-17. HAL a raison dans 38 cas : diminutif (Tony pour A. A. Affolder), initiale composée (Ch., Ph.), translittération (Ia), variante nationale (André pour Andrzej), erreur des autres sources. La liste HAL est décalée dans 31 cas. Le compte HAL est faux dans 20 cas, le plus souvent une faute de saisie sur un auteur sans compte ; parfois le bon compte a une forme différente (Joël J. Drevet pour Joël R. Drevet). 9 cas restent indéterminables.
- [x] Sources dépendantes : accord mesuré sans les paires où une notice recopie l'autre (notice scanR issue d'un dépôt HAL, notice OpenAlex dont la location principale est HAL).
- [x] Ambiguïté des appariements par nom : nombre de noms compatibles par signature décalée, dans les grandes listes.
- [x] Doubles rattachements : signatures d'une même notice rattachées à la même personne.
- [x] Identifiants contradictoires au sein d'un couple (publication, personne).
- [x] Échantillon des identifiants contradictoires entre sources, relu à la main : 78 paires ORCID et IdRef, 2026-10-17. Une différence de `hal_person_id` n'est pas une contradiction : une personne a souvent plusieurs comptes HAL.
  - Identifiant erroné dans une source : 39 (ScanR 18, HAL 14, Crossref et OpenAlex 5, IdRef supprimé ou indéterminé 2). ScanR attribue l'identifiant d'un homonyme. Dans Crossref, l'ORCID erroné est celui d'un co-auteur.
  - Même personne, deux identifiants : 30. Pour l'IdRef, un doublon, souvent redirigé. Pour l'ORCID, un compte vide ou désactivé.
  - Indéterminable : 9.
- [x] Liens au périmètre établis par la seule signature scanR : 5 735 couples (publication, personne), dont 100 relus à la main, 2026-10-17.

  | Indice de périmètre de scanR | Couples | Relus | À juste titre | À tort | Indéterminable |
  |---|---|---|---|---|---|
  | identité RH, autres sources présentes | 2 268 | 40 | 31 | 5 | 4 |
  | identité RH, scanR seul | 1 815 | 20 | 19 | 0 | 1 |
  | structure HAL ou ROR | 1 314 | 25 | 9 | 12 | 4 |
  | adresse | 338 | 15 | 5 | 10 | 0 |

  - Structure : 11 erreurs sur 12 sont des publications de collaborations de 1 000 à 3 000 auteurs. scanR y donne la structure ou le ROR à des auteurs extérieurs. La signature HAL de ces auteurs n'a aucune structure, dans les cas justes comme dans les cas faux.
  - Adresse : scanR attribue à l'auteur les adresses d'autres auteurs, jusqu'à 16 par signature, ou des blocs mal découpés.
  - Identité RH : les 5 erreurs sont des signatures à l'initiale, rapprochées d'un homonyme RH de même initiale.
  - 21 des 31 couples justes de la première strate ont une adresse OpenAlex au CHU de Clermont.
  - Priorité simulée sur les signatures appariées par nom et position : l'adresse OpenAlex prime, puis celle de WoS, puis les indices de scanR. Strate adresse : 9 erreurs sur 10 retirées, aucun couple juste perdu. Strate structure : 6 erreurs sur 12 retirées, 1 couple juste perdu.
- [x] IdRef attribués par la seule signature scanR : 3 660, comparés à leur notice IdRef, dont 100 relus à la main, 2026-10-17. 3 650 notices trouvées, 162 de nom incompatible avec la personne.

  | Strate | IdRef | Relus | IdRef de la personne | Homonyme | Prénom différent | Indéterminable |
  |---|---|---|---|---|---|---|
  | nom incompatible | 162 | 30 | 0 | 3 | 27 | 0 |
  | nom compatible | 3 488 | 60 | 54 | 4 | 2 | 0 |
  | IdRef introuvable | 10 | 10 | 8 | 0 | 0 | 2 |

  - Un nom incompatible signale un IdRef faux. Un nom compatible laisse passer les homonymes, environ 10 %. Les prénoms différents de cette strate sont réduits à l'initiale dans la signature.
  - 9 des 10 IdRef introuvables sont fusionnés : la page IdRef redirige vers un autre numéro, la recherche Solr ne les rend pas. Le dernier est supprimé.

### Phase 2 — Méthode et modèle

- [ ] Méthode d'alignement, choisie d'après la mesure. Essai du 2026-10-17, dans `data/experiments/alignement-auteurs/` (non versionné).
  - Modèle de Fellegi-Sunter (Splink). Les poids s'estiment par EM sur les paires de signatures d'une même publication. Comparaisons : nom, prénom, ORCID, IdRef, `hal_person_id` (égalité seule), position selon l'écart et la longueur de liste.
  - Affectation hongroise entre chaque paire de notices. Un lien est retenu quand les preuves dépassent log2 de la longueur de liste.
  - Le dernier auteur restant de chaque liste est lié quand les auteurs liés qui le précèdent sont les mêmes des deux côtés.
  - Une notice scanR recopiée d'un dépôt HAL est exclue quand la publication a ce dépôt.
  - Au-delà de 100 auteurs, un modèle distinct compare les seules paires de même position, de même identifiant ou aux noms de mêmes trois premières lettres.
  - Résultat sur les 326 paires relues en phase 1 : 313 correctes. Erreurs : 4 noms fréquents (Kim, Zhang) liés à la même position malgré des prénoms différents, dans des listes de plus de 400 auteurs ; 3 paires d'un auteur en double dans une notice HAL ; 3 paires « autre personne » non liées ; 2 auteurs déplacés non liés ; 1 variante de nom non liée.
- [ ] Modèle : table des auteurs alignés portant `person_id`, lien de chaque signature à son auteur, contraintes d'unicité.
- [ ] Marquage à recalculer d'un auteur aligné dont une signature change d'identifiants.

### Phase 3 — Usages

- [ ] Identification des personnes par auteur aligné. Une adresse au CHU de Clermont laisse l'auteur hors périmètre, mais appuie son rattachement à une personne RH.
- [ ] Correction des doubles rattachements et des personnes portant deux identifiants de deux personnes.
- [ ] Fusions suspectes : listes d'auteurs qui ne s'alignent pas.
- [ ] Désaccords d'affiliation entre sources pour un même auteur.
- [ ] Indices de périmètre par auteur aligné : l'adresse OpenAlex prime, puis celle de WoS, puis les indices de scanR.
- [ ] Revue des appariements : trois classes selon le score et la marge (lien, non-lien, lien possible). Une file de revue de l'UI admin confirme ou infirme les liens possibles. La comparaison des listes d'auteurs entre sources (`SourceComparison.svelte`) quitte la page publique d'une publication pour le volet publication de l'UI admin.

### Phase 4 — Fin de chantier

- [ ] Mise à jour de la documentation.

## Questions ouvertes

- **Méthode.** Affectation par similarité de noms sous les contraintes des identifiants. Rôle de la position : indice faible, ou critère pour les seules listes courtes.
- **Identifiants différents entre sources.** Deux valeurs différentes d'un même type, à des signatures de sources différentes, séparent-elles deux signatures ? Une personne peut avoir deux IdRef ou deux comptes ORCID.
- **Ancrage des rattachements manuels.** Sur quoi ancrer un rattachement manuel pour qu'il survive à un changement d'identifiants de la signature : notice et position, notice et nom ?
- **Signature sans correspondant** dans les autres notices (liste partielle) : un auteur à une seule signature.
- **ORCID d'OpenAlex sans DOI.** Sur des notices OpenAlex sans DOI, `raw_orcid` donne deux fois un ORCID faux (Yannick Chevalier, Bruno Pereira). Provenance de `raw_orcid` hors Crossref à vérifier.
- **Rapport avec `authorships`** : l'auteur aligné remplace-t-il la consolidation par paire (publication, personne) ?
- **Nom déclaré par IdRef et ORCID.** Les API d'IdRef et d'ORCID donnent le nom de la personne. Ce nom permettrait d'écarter les identifiants attribués à tort.
