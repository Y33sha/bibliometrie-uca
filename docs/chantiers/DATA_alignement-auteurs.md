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

## Décisions

- L'alignement se fait par publication, avant la phase `persons`.
- Un identifiant fort (ORCID, IdRef, idHAL) non neutralisé réunit deux signatures qui le partagent. Deux valeurs différentes du même type séparent deux signatures.
- La méthode se choisit d'après une mesure du stock, faite hors pipeline.

## Phasage

### Phase 1 — Mesure

- [ ] Publications à plusieurs notices : nombre de signatures par notice, écarts de longueur entre listes.
- [ ] Accord de la position : part des signatures dont le nom est compatible avec celui de la même position dans une autre notice, selon le nombre d'auteurs.
- [ ] Accord des identifiants : paires de signatures réunies ou séparées par un identifiant fort, confrontées à la position et au nom.
- [ ] Échantillon de désaccords relu à la main.

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
