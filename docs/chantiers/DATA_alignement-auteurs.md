# Chantier — Alignement des auteurs d'une publication

## Contexte

Une publication réunit les notices de plusieurs sources. Chaque notice a ses signatures (`source_authorships`). Aucune table ne dit quelles signatures de notices différentes désignent le même auteur.

Le rapprochement passe aujourd'hui par la personne. La phase `persons` rattache chaque signature à une personne, puis `authorships` consolide par paire (publication, personne). Le rattachement cross-source reconnaît une personne déjà liée à la même position d'auteur dans une autre notice, si le nom est compatible.

La position est un indice faible. Au-delà d'un certain nombre d'auteurs, les écarts de position entre sources sont la règle : ordres différents, listes partielles, noms de collectifs.

Un niveau « auteur de la publication », indépendant de l'identification des personnes, servirait :

- l'identification des personnes : les identifiants de toutes les sources se réunissent avant toute décision, et la décision se prend une fois par auteur ;
- le contrôle de la déduplication des publications : des notices dont les listes d'auteurs ne s'alignent pas signalent une fusion suspecte (onglet « Recouvrement d'auteurs » de `METIER_gestion-admin-des-publications.md`) ;
- la détection des erreurs d'affiliation : un même auteur rattaché au périmètre par une source et ailleurs par une autre ;
- la consolidation du périmètre par auteur (`DATA_perimetre.md`).

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

| Source | Positions en désaccord | Source qui s'écarte |
|---|---|---|
| HAL | 5 507 | 37,9 % |
| Crossref | 5 585 | 26,4 % |
| WoS | 2 955 | 15,8 % |
| DataCite | 3 225 | 12,7 % |
| OpenAlex | 6 094 | 2,0 % |
| scanR | 646 | 1,5 % |

Le tableau compte les positions communes à trois sources indépendantes ou plus, au même nom de famille, dont les prénoms sont incompatibles. La source qui s'écarte a un prénom incompatible avec tous les autres, eux compatibles entre eux. 1 529 positions sont sans source unique qui s'écarte. HAL s'écarte le plus souvent, Crossref ensuite. scanR et OpenAlex partagent une partie de leurs données, donc le vote peut les favoriser.

## Décisions

- L'alignement se fait par publication, avant la phase `persons`.
- Un identifiant fort (ORCID, IdRef, idHAL) non neutralisé réunit deux signatures qui le partagent. Deux valeurs différentes du même type séparent deux signatures.
- La méthode se choisit d'après une mesure du stock, faite hors pipeline.

## Phasage

### Phase 1 — Mesure

- [x] Publications à plusieurs notices : nombre de signatures par notice, écarts de longueur entre listes.
- [x] Accord de la position : part des signatures dont le nom est compatible avec celui de la même position dans une autre notice, selon le nombre d'auteurs.
- [x] Accord des identifiants : paires de signatures réunies ou séparées par un identifiant fort, confrontées à la position et au nom.
- [ ] Échantillon de désaccords relu à la main : `data/measures/author_alignment_disagreements.csv`, 5 000 lignes.
- [x] Prénom incompatible à la même position : source qui s'écarte de la majorité, sur les publications à trois notices ou plus.
- [ ] Échantillon des positions où HAL s'écarte, relu à la main. Hypothèse : HAL rattache automatiquement une signature à un mauvais compte.
- [x] Sources dépendantes : accord mesuré sans les paires où une notice recopie l'autre (notice scanR issue d'un dépôt HAL, notice OpenAlex dont la location principale est HAL).
- [x] Ambiguïté des appariements par nom : nombre de noms compatibles par signature décalée, dans les grandes listes.

### Phase 2 — Méthode et modèle

- [ ] Méthode d'alignement, choisie d'après la mesure.
- [ ] Modèle : auteurs alignés d'une publication, et lien de chaque signature à son auteur.

### Phase 3 — Usages

- [ ] Identification des personnes par auteur aligné.
- [ ] Fusions suspectes : listes d'auteurs qui ne s'alignent pas.
- [ ] Désaccords d'affiliation entre sources pour un même auteur.

### Phase 4 — Fin de chantier

- [ ] Mise à jour de la documentation.

## Questions ouvertes

- **Méthode.** Affectation par similarité de noms sous les contraintes des identifiants. Rôle de la position : indice faible, ou critère pour les seules listes courtes.
- **Signature sans correspondant** dans les autres notices (liste partielle) : un auteur à une seule signature.
- **Auteurs collectifs** : noms de consortium dans la liste des auteurs.
- **Rapport avec `authorships`** : l'auteur aligné remplace-t-il la consolidation par paire (publication, personne) ?
