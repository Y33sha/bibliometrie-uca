# Chantier — Résolution des entités avec Splink

## Contexte

La résolution des personnes est une cascade de règles : elle rattache chaque signature à une personne existante, sans comparer les signatures entre elles. C'est la forme de ReCiter. La réconciliation des publications regroupe les notices qui partagent une clé de confirmation.

**Contrat de la résolution** : en entrée, les notices et les signatures sources, plus les décisions humaines ; en sortie, une table de correspondance entre chaque notice ou signature et son entité. Le contrat tient quel que soit l'algorithme.

**Forme par paires**, celle de Splink et de dnet-dedup. Chaque étape lit en base ce que la précédente a écrit :

1. **paires candidates** : les paires de notices ou de signatures qui concordent, avec leur origine ou leur score ;
2. **décisions** : les confirmations ajoutent des paires, les rejets et les non-doublons en retirent ;
3. **groupes** : composantes connexes sur les paires retenues ;
4. **identifiant** : chaque groupe reçoit un identifiant ;
5. **entité** : construite à partir des membres du groupe.

La table des paires est du dérivé recalculable. C'est la sortie d'un modèle probabiliste comme de règles déterministes.

**Dépendance.** Le chantier [alignement des auteurs](DATA_alignement-auteurs.md) regroupe par publication les signatures des différentes sources qui désignent le même auteur. La résolution des personnes compare alors des auteurs alignés : le volume à comparer diminue, et chaque auteur aligné réunit les identifiants de ses signatures.

## Décisions

## Phasage

### Phase 1 — Cadrage

- [ ] Trancher l'algorithme de résolution des personnes : cascade de règles ou modèle probabiliste, et avec lui le recalcul complet de la résolution.
- [ ] Rattachements par identifiant dont l'identifiant est rejeté ou absent chez la personne : 2 232 au 2026-10-18, dont 885 rejetés. Ils sont à réexaminer sur les autres critères (nom, groupe), sans détachement systématique. L'identifiant de la signature est souvent faux alors que la personne est la bonne.
- [ ] Doublons d'auteur des notices écartées de l'alignement (notice scanR issue d'un dépôt HAL présent, notice DataCite au DOI convergé) : `author_grouping` ne les détecte pas, donc la résolution les rattache à une personne. 358 notices au 2026-10-18.

### Phase 2 — Résolution par groupe

- [ ] Identification des personnes par groupe de signatures (`source_authorship_groups`) au lieu de chaque signature. Une adresse au CHU de Clermont laisse l'auteur hors périmètre, mais appuie son rattachement à une personne RH.
- [ ] Correction des doubles rattachements (une personne rattachée à deux signatures d'une même notice) et des personnes qui ont les identifiants de deux personnes.
- [ ] ORCID en attente rattachés à une autre personne que leur titulaire : 21 groupes dans la relecture du 2026-10-19.
- [ ] `person_id` et `resolution_mode` passent de `source_authorships` à `source_authorship_groups`. `source_authorship_groups` remplace `authorships`, matviews reportées.

## Questions ouvertes

- Pour le modèle probabiliste, Splink plutôt qu'un modèle maison.
- Splink additionne les comparaisons comme si elles étaient indépendantes : revue, sujet et structure, corrélés, sont à regrouper en une seule comparaison.
- Splink ne prévoit pas les liens imposés ou interdits : les décisions humaines s'appliquent à l'étape 2.
- Les composantes connexes ne respectent pas les interdictions. La réconciliation des publications sépare toujours deux DOI différents, ce que la transitivité des paires ne garantit pas. L'étape 3 devient alors un regroupement sous contraintes, et l'étape 2 reçoit aussi les interdictions issues des règles.
- Les décisions sur les personnes visent des entités (un rejet vise un couple publication-personne, un non-doublon deux personnes), non des paires de signatures. Comment les traduire en contraintes sur les signatures ?
- Deux idées de ReCiter : enregistrer ce qui a concordé et pas seulement la règle ; réutiliser les confirmations et les rejets d'une personne comme indices pour ses autres signatures.
- La précision et le rappel de la cascade après l'alignement des auteurs, mesurés contre les décisions humaines (rattachements rejetés, rattachements manuels qu'elle avait manqués) : base de comparaison avec Splink.
- `publications.reconcile`, aujourd'hui un seul nœud du graphe : le scinder selon les étapes de la forme par paires, si elle est retenue.
