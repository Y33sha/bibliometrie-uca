# Chantier — Résolution probabiliste des personnes

## Contexte

La résolution des personnes est une cascade de règles. Elle rattache chaque contribution à une personne existante : identifiants, puis forme de nom, puis départage d'un nom ambigu par une cascade d'indices. La détection des attributions suspectes repère les clusters isolés et les publications proches des rejets. Chaque règle pondère ses indices à la main.

**Contrat de la résolution** : en entrée, les enregistrements sources et les contributions sources, plus les décisions humaines ; en sortie, une table de correspondance entre chaque contribution et sa personne. Le contrat tient quel que soit l'algorithme.

Mesure exploratoire du 2026-11-24 (`data/experiments/fausses-attributions/embeddings_*.py`) : embedding du titre et du début du résumé, modèle `paraphrase-multilingual-MiniLM-L12-v2`. Jeu : 52 personnes ayant des rejets, 3 153 publications actuelles, 852 publications rejetées. Score d'une publication : similarité moyenne avec ses cinq plus proches voisines parmi les publications actuelles de la personne.

| Score | AUC | Rappel des rejetées, 1 % des actuelles signalées | Rappel des rejets isolés (41, personnes à 3 rejets au plus) |
|---|---|---|---|
| Embeddings | 0,986 | 0,80 | 0,88 |
| Sous-champs OpenAlex | 0,979 | 0,73 | 0,63 |

- Les embeddings couvrent toutes les publications ; 5 des 41 rejets isolés sont sans sous-champ OpenAlex.
- Comparées entre elles, les publications rejetées d'un même homonyme se ressemblent : AUC de 0,40 quand le voisinage réunit publications actuelles et rejetées. Les clusters couvrent ce cas.
- Publications actuelles les plus isolées, relues à vue : des homonymes probables, comme la karstification chez un physicien d'ALICE ou la valve aortique chez une généticienne animale. Les fausses alertes sont des articles d'instrumentation d'ALICE chez des physiciens d'ALICE, des titres génériques (« Guest Editor introduction », « Data integration ») et des titres en français.
- Jeu élargi aux personnes à fiche RH d'au moins quatre publications : 1 394 personnes, 67 721 publications actuelles. Quand 1 % des actuelles sont signalées, le rappel des rejetées est de 0,74 (0,81 en score normalisé). Le rappel des rejets isolés est de 0,80.
- Les 25 publications actuelles les plus isolées comptent quelques homonymes probables, et surtout des titres génériques (actes de colloque, éditoriaux, réponses, préfaces) et des articles d'instrumentation des grandes collaborations.
- Le calcul prend 48 minutes pour 41 699 publications sur le CPU.
- Alertes filtrées (`embeddings_alertes.py`) : seuil de 1 % des publications actuelles, contributions signalables selon la règle des clusters, publications à contenu disciplinaire (types et titres génériques écartés). 611 alertes avant filtres, 76 après. 557 des 565 rejetées signalables à contenu disciplinaire passent sous le seuil.
- Verdicts de l'administration sur les 76 alertes, le 2026-11-24 (`embeddings_verdicts.py`) : 46 homonymes, 20 publications de la personne, 10 incertaines.

  | Critère | Homonymes | De la personne | Incertaines |
  |---|---|---|---|
  | Score normalisé sous −4 | 10 | 1 | 1 |
  | Score normalisé au-dessus de −3 | 6 | 8 | 3 |
  | Au moins un coauteur à fiche RH dans la publication | 0 | 8 | 2 |
  | Revue partagée avec une autre publication de la personne | 1 | 6 | 2 |
  | Ni coauteur à fiche RH cosignant une autre publication de la personne, ni revue partagée | 45 | 9 | 6 |

  - Le score seul n'a pas de seuil fiable. Coauteurs et revue écartent 16 alertes, dont un seul homonyme.
  - Les 9 fausses alertes restantes sont des publications éloignées des autres publications de la personne, sans coauteur ni revue habituels.
  - Score thématique (`embeddings_sujets.py`) : similarité maximale entre la publication et les libellés des 15 thèmes OpenAlex les plus fréquents chez la personne, encodés par le même modèle. Médiane de 0,20 pour les homonymes, de 0,37 pour les publications de la personne. Un seuil à 0,33 ramène les 60 alertes restantes à 50 : 42 homonymes, 4 publications de la personne, 4 incertaines. Le seuil est choisi sur ces mêmes alertes.
  - Sur tout le jeu, le score thématique seul sépare les rejetées des actuelles avec une AUC de 0,93, contre 0,98 pour la comparaison aux publications voisines.
  - 16 des 46 homonymes sont rattachés par un ORCID donné par HAL seul.
  - Les verdicts sont copiés dans `data/experiments/fausses-attributions/embeddings_verdicts/`. Ils forment un premier jeu d'évaluation du modèle.
- Un modèle d'embeddings statiques (`potion-multilingual-128M`) calcule ces 41 699 publications en 3 minutes. Sur 1 394 personnes, il retrouve 5 % des rejetées quand 1 % des actuelles sont signalées. Ses publications les plus isolées sont des titres génériques : actes de colloque, éditoriaux, réponses.

## Décisions

- La méthode se choisit d'après des essais hors pipeline, évalués sur les verdicts humains, comme dans le chantier [alignement des auteurs](archived/2026-10-24_DATA_alignement-auteurs.md).
- Le modèle note des paires (contribution, personne candidate). Résolution : la personne candidate la mieux notée, si l'écart avec la suivante est net. Détection : une contribution rattachée et mal notée pour sa personne rejoint la file des attributions suspectes.
- La création d'une personne pour un nom inconnu reste une règle.
- Modèle discriminant : régression logistique régularisée, puis arbres de gradient s'ils la battent nettement. Probabilités calibrées. Un modèle bayésien naïf comme celui de Splink compte plusieurs fois des indices corrélés : laboratoire, structure HAL, revue, sous-champ, embedding.
- Les identifiants sont hors des indices. Ils fournissent les étiquettes, puis un second signal.
- Évaluation sur un découpage par personne : une personne figure dans l'entraînement ou dans le test, jamais dans les deux. Référence : la cascade de départage et la détection par clusters.

## Phasage

### Phase 1 — Jeu de paires et indices

Scripts et données dans `data/experiments/`, hors pipeline.

- [x] Embeddings des publications, modèle `paraphrase-multilingual-MiniLM-L12-v2`.
- [ ] Positifs : épinglages, confirmations, verdicts « de la personne ». S'y ajoutent les contributions rattachées par un identifiant donné par au moins deux sources, ou par un ORCID de Crossref, DataCite, INSPIRE-HEP ou du `raw_orcid` d'OpenAlex. HAL et ScanR seuls sont exclus : l'ORCID de ScanR seul est faux une fois sur deux.
- [ ] Négatifs : rejets, verdicts « homonyme », autres personnes candidates d'un nom ambigu sur les contributions positives.
- [ ] Indices de chaque paire. La publication notée est exclue du profil de la personne.
  - Réseau : coauteurs partagés pondérés par leur rareté, laboratoire, structure HAL, revue.
  - Contenu : similarité d'embeddings aux publications voisines, score thématique, cosinus des sous-champs.
  - Contexte : écart d'années, nombre d'auteurs de la publication, prénom complet ou initiale, taille du profil, année comprise dans les périodes RH.

### Phase 2 — Régression logistique

- [ ] Entraînement et évaluation face à la cascade de départage (résolution) et aux clusters (détection) : précision des 50 et des 100 alertes les mieux classées, aire sous la courbe précision-rappel, exactitude sur les noms ambigus mis de côté.
- [ ] Ablation par indice.

### Phase 3 — Arbres de gradient

- [ ] Arbres de gradient (`HistGradientBoosting`), comparés à la régression logistique.
- [ ] Calibration des probabilités.

### Phase 4 — Apprentissage actif

- [ ] Tours de jugement dans la page des alertes : paires les plus suspectes et paires les plus incertaines. Les verdicts rejoignent les étiquettes, puis le modèle est réentraîné et remesuré.

### Phase 5 — Intégration

- [ ] Décisions préalables : stockage des embeddings en base, dépendance à scikit-learn, tâche du pipeline qui note les paires.
- [ ] Identifiants comme second signal. Un désaccord entre le modèle et les identifiants signale une erreur d'identifiant ou une fausse attribution, présentée à l'administration.
- [ ] Résolution indépendante de l'ordre d'arrivée des enregistrements sources. Les rattachements non épinglés sont remis en jeu à chaque passage.

## Questions ouvertes

- Écart minimal entre la meilleure personne candidate et la suivante pour rattacher une contribution.
