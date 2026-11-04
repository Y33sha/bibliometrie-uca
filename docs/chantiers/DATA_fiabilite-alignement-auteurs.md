# Chantier — Fiabilité de l'alignement des auteurs

## Contexte

La phase `author_grouping` réunit dans une contribution les contributions sources d'un même auteur dans une publication (`domain/contributions/author_grouping.py`). Des étapes strictes (nom, identifiant, filtre d'ordre, ordre dans les trous) précèdent un modèle probabiliste (Fellegi-Sunter) appliqué au résidu. Les noms de famille et les prénoms se comparent séparément. Plusieurs règles servent aux méga-collaborations, où des auteurs partagent un nom de famille et une initiale.

Au 2026-11-04, les liens se répartissent ainsi : 15 878 841 par le nom, 850 094 par le modèle, 288 071 par l'ordre, 127 535 par identifiant.

Exemple : la publication 22307 a quatre auteurs dans chacun de ses cinq enregistrements sources. Les trois derniers sont alignés. HAL découpe la première autrice en « fernandes da rocha / carmella puleoto », OpenAlex, WoS et ScanR en « da rocha puleoto / carmella fernandes ». Il reste une contribution source de chaque côté, dans le même trou. Les noms de famille et les prénoms tombent au niveau `else` (Jaro-Winkler 0,52 et 0,84), donc `_position_only` écarte la paire avant le modèle. Les deux noms complets ont pourtant les mêmes mots. La publication a cinq contributions.

## Décisions

- Les variantes se comparent sur un banc de simulation hors base, avant toute modification du pipeline.
- Le temps d'exécution de la phase compte autant que la fiabilité de l'alignement.

## Phasage

### Phase 1 — Banc de simulation

- [ ] Rejeu de l'alignement hors base, sur tout le stock ou sur un échantillon stratifié par nombre d'auteurs. Entrées et résultats persistés sur disque.
- [ ] Mesures : publications aux listes d'auteurs toutes de longueur N, avec plus de N contributions ; contributions sans personne pour cause de personne présente dans une autre contribution de la publication (`PERSON_IN_OTHER_CONTRIBUTION`) ; écarts avec l'alignement en base ; temps d'exécution.
- [ ] Jeu de cas annotés, dont la publication 22307.

### Phase 2 — Variantes

- [ ] Résidu de même taille des deux côtés d'un trou : comparaison des noms complets, indépendante du découpage entre nom de famille et prénom (ensemble des mots, ou similarité de chaînes des noms complets triés).
- [ ] Critère d'ambiguïté : nombre d'auteurs de la publication, ou nombre de candidats dans le trou. Un jeu de règles par régime si la simulation le justifie.
- [ ] Remplacement du modèle probabiliste par quelques étapes simples : sort des liens du modèle.

### Phase 3 — Intégration

- [ ] Variante retenue dans `domain/contributions/author_grouping.py`.
- [ ] `--rebuild-author-grouping`, après mesure de l'écart entre l'alignement en base et le résultat de la variante.

### Phase 4 — Documentation

- [ ] Mise à jour de `docs/pipeline/08-author-grouping.md`.

## Questions ouvertes

- Attribution manuelle d'une contribution orpheline en conflit avec une contribution automatique de la même personne. La contribution épinglée garde la personne, l'autre contribution reste sans personne (`settle_publication`). Sous la centaine d'auteurs, ce conflit révèle surtout un défaut d'alignement ou un doublon d'auteur dans un enregistrement source. Piste : l'épinglage comme contrainte de l'alignement. Les deux contributions fusionnent si elles ont des enregistrements sources disjoints ; sinon, l'une des deux contributions sources est un doublon. La phase `author_grouping` précède la phase `persons`.
