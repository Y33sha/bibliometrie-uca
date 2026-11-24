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

Mesure exploratoire du 2026-11-24 (`data/experiments/fausses-attributions/embeddings_*.py`) : embedding du titre et du début du résumé, modèle `paraphrase-multilingual-MiniLM-L12-v2`. Jeu : 52 personnes ayant des rejets, 3 153 publications actuelles, 852 publications rejetées. Score d'une publication : similarité moyenne avec ses cinq plus proches voisines parmi les publications actuelles de la personne.

| Score | AUC | Rappel des rejetées, 1 % des actuelles signalées | Rappel des rejets isolés (41, personnes à 3 rejets au plus) |
|---|---|---|---|
| Embeddings | 0,986 | 0,80 | 0,88 |
| Sous-champs OpenAlex | 0,979 | 0,73 | 0,63 |

- Les embeddings couvrent toutes les publications ; 5 des 41 rejets isolés sont sans sous-champ OpenAlex.
- Comparées entre elles, les publications rejetées d'un même homonyme se ressemblent : AUC de 0,40 quand le voisinage réunit publications actuelles et rejetées. Les clusters couvrent ce cas.
- Publications actuelles les plus isolées, relues à vue : des homonymes probables, comme la karstification chez un physicien d'ALICE ou la valve aortique chez une généticienne animale. Les fausses alertes sont des articles d'instrumentation d'ALICE chez des physiciens d'ALICE, des titres génériques (« Guest Editor introduction », « Data integration ») et des titres en français.
- Le calcul prend environ 11 publications par seconde sur le CPU, soit environ une heure pour les publications des personnes à fiche RH.
- Un modèle d'embeddings statiques (`potion-multilingual-128M`) calcule ces 41 699 publications en 3 minutes. Sur 1 394 personnes, il retrouve 5 % des rejetées quand 1 % des actuelles sont signalées. Ses publications les plus isolées sont des titres génériques : actes de colloque, éditoriaux, réponses.

## Décisions

- La méthode se choisit d'après des essais hors pipeline, évalués sur les verdicts humains, comme dans le chantier [alignement des auteurs](archived/2026-10-24_DATA_alignement-auteurs.md).

## Phasage

### Phase 1 — Essais

- [ ] Modèle probabiliste sur le résidu de la cascade par groupe, évalué sur le jeu d'évaluation.
- [ ] Modèle sans les identifiants : le nom et les indices du départage des noms ambigus (coauteurs, laboratoire, structure HAL, revue, années d'activité). Le poids des identifiants écraserait les autres indices.
- [ ] Similarité d'embeddings du titre et du résumé comme indice de discipline, à la place des sous-champs OpenAlex : publication isolée dans la production d'une personne, comparaison d'une publication aux profils des personnes candidates.
- [ ] Identifiants comme second signal. Un désaccord entre le modèle et les identifiants signale une erreur d'identifiant ou une fausse attribution, présentée à l'administration.

### Phase 2 — Choix de la méthode

- [ ] Cascade seule, ou cascade puis modèle probabiliste sur le résidu.
- [ ] Résolution indépendante de l'ordre d'arrivée des enregistrements sources. Les rattachements non épinglés sont remis en jeu à chaque passage.

## Questions ouvertes

- Splink plutôt qu'un modèle maison.
- Splink additionne les comparaisons comme si elles étaient indépendantes : revue, sujet et structure, corrélés, sont à regrouper en une seule comparaison.
- Splink ne prévoit pas les liens imposés ou interdits : les décisions humaines s'appliquent à l'étape 2.
- Les composantes connexes ne respectent pas les interdictions. La réconciliation des publications sépare toujours deux DOI différents, ce que la transitivité des paires ne garantit pas. L'étape 3 devient alors un regroupement sous contraintes, et l'étape 2 reçoit aussi les interdictions issues des règles.
- Les décisions sur les personnes visent des entités (un rejet vise un couple publication-personne, un non-doublon deux personnes), non des paires de groupes. Comment les traduire en contraintes sur les groupes ?
- `publications.reconcile`, une seule tâche du graphe : le scinder selon les étapes de la forme par paires, si elle est retenue.
