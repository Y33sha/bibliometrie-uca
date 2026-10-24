# Chantier — Résolution probabiliste des personnes

## Contexte

La résolution des personnes est une cascade de règles. Elle rattache chaque groupe de contributions sources à une personne existante, sans comparer les groupes entre eux. C'est la forme de ReCiter. La réconciliation des publications regroupe les enregistrements sources qui partagent une clé de confirmation.

Ce chantier dépend du chantier [résolution des personnes par groupe](archived/2026-10-24_DATA_resolution-personnes.md), qui fournit le jeu d'évaluation.

**Contrat de la résolution** : en entrée, les enregistrements sources et les contributions sources, plus les décisions humaines ; en sortie, une table de correspondance entre chaque enregistrement source ou groupe et son entité. Le contrat tient quel que soit l'algorithme.

**Forme par paires**, celle de Splink et de dnet-dedup. Chaque étape lit en base ce que la précédente a écrit :

1. **paires candidates** : les paires d'enregistrements sources ou de groupes qui concordent, avec leur origine ou leur score ;
2. **décisions** : les confirmations ajoutent des paires, les rejets et les non-doublons en retirent ;
3. **groupes** : composantes connexes sur les paires retenues ;
4. **identifiant** : chaque groupe reçoit un identifiant ;
5. **entité** : construite à partir des membres du groupe.

La table des paires est du dérivé recalculable. C'est la sortie d'un modèle probabiliste comme de règles déterministes.

## Décisions

- La méthode se choisit d'après des essais hors pipeline, évalués sur les verdicts humains, comme dans le chantier [alignement des auteurs](archived/2026-10-24_DATA_alignement-auteurs.md).

## Phasage

### Phase 1 — Essais

- [ ] Modèle probabiliste sur le résidu de la cascade par groupe, évalué sur le jeu d'évaluation.

### Phase 2 — Choix de la méthode

- [ ] Cascade seule, ou cascade puis modèle probabiliste sur le résidu.

## Questions ouvertes

- Splink plutôt qu'un modèle maison.
- Splink additionne les comparaisons comme si elles étaient indépendantes : revue, sujet et structure, corrélés, sont à regrouper en une seule comparaison.
- Splink ne prévoit pas les liens imposés ou interdits : les décisions humaines s'appliquent à l'étape 2.
- Les composantes connexes ne respectent pas les interdictions. La réconciliation des publications sépare toujours deux DOI différents, ce que la transitivité des paires ne garantit pas. L'étape 3 devient alors un regroupement sous contraintes, et l'étape 2 reçoit aussi les interdictions issues des règles.
- Les décisions sur les personnes visent des entités (un rejet vise un couple publication-personne, un non-doublon deux personnes), non des paires de groupes. Comment les traduire en contraintes sur les groupes ?
- `publications.reconcile`, une seule tâche du graphe : le scinder selon les étapes de la forme par paires, si elle est retenue.
