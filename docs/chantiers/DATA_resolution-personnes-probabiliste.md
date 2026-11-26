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
- Modèle discriminant : régression logistique régularisée, puis arbres de gradient s'ils la battent nettement. Un modèle bayésien naïf comme celui de Splink compte plusieurs fois des indices corrélés : laboratoire, structure HAL, revue, sous-champ, embedding.
- Les identifiants sont hors des indices. Ils fournissent les étiquettes, puis un second signal.
- Évaluation sur un découpage par personne : une personne figure dans l'entraînement ou dans le test, jamais dans les deux. Référence : la cascade de départage et la détection par clusters.
- Embeddings des publications stockés en base dans un tableau de réels (`real[]`), 384 dimensions. Le type `vector` de l'extension pgvector reste possible pour une recherche des plus proches voisins dans tout le stock.

## Phasage

### Phase 1 — Jeu de paires et indices

Scripts et données dans `data/experiments/resolution-probabiliste/` (`paires.py`, `indices.py`), hors pipeline. Les personnes sont celles du jeu des embeddings. Les contributions aux seuls rôles de jury de thèse sont écartées, du jeu comme des profils. Jeu du 2026-11-25 : 29 433 paires avec indices, de 1 099 personnes, dont 1 263 négatives. Négatives avant le calcul des indices : rejets 857, homonymes par le nom 283, autres candidates d'une forme ambiguë 126, verdicts 14.

- [x] Embeddings des publications, modèle `paraphrase-multilingual-MiniLM-L12-v2`.
- [x] Positifs : épinglages, confirmations, verdicts « de la personne ». S'y ajoutent les contributions rattachées par un identifiant donné par au moins deux sources, ou par un ORCID de Crossref, DataCite, INSPIRE-HEP ou du `raw_orcid` d'OpenAlex. HAL et ScanR seuls sont exclus : l'ORCID de ScanR seul est faux une fois sur deux.
- [x] Négatifs : rejets, verdicts « homonyme », autres personnes candidates d'un nom ambigu sur les contributions positives, autres personnes de même nom de famille et de même initiale. Un prénom complet identique compte seulement entre personnes déclarées distinctes.
- [x] Indices de chaque paire. La publication notée est exclue du profil de la personne.
  - Réseau : coauteurs partagés pondérés par leur rareté, laboratoire, structure HAL, revue.
  - Contenu : similarité d'embeddings aux publications voisines, score thématique, cosinus des sous-champs.
  - Contexte : écart d'années, nombre d'auteurs de la publication, prénom complet ou initiale, taille du profil, année comprise dans les périodes RH.

### Phase 2 — Régression logistique

- [x] Entraînement et évaluation en cinq plis groupés par personne (`modele_logistique.py`), le 2026-11-25.
  - Détection : AUC de 0,992, aire sous la courbe précision-rappel des négatifs de 0,91. Les 100 paires les moins bien notées sont toutes négatives.
  - Tranche difficile, publications de 100 contributions au plus, hors des 6 personnes à plus de 50 négatifs (21 105 paires, 212 négatives) : AUC de 0,991, aire de 0,82, 95 négatives parmi les 100 paires les moins bien notées. Au seuil qui signale 1 % des positives, 189 négatives sur 212 sont signalées : rejets 75 sur 83, homonymes par le nom 66 sur 66, verdicts 11 sur 12, autres candidates 37 sur 51.
  - Résolution, sur 349 contributions disputées entre la personne juste et au moins une autre candidate : le modèle désigne la personne juste dans 348 cas. La cascade de départage rejouée sur les indices décide 338 cas, dont 336 justes.
  - Le nombre de contributions de la publication a un coefficient de −2,6 : les rejets viennent souvent des grandes collaborations. Les positifs, rattachés par identifiant, en comptent moins.
- [x] Ablation par famille d'indices : sans le contenu (embeddings, thèmes, sous-champs), l'aire tombe de 0,91 à 0,73 ; sans le réseau, à 0,86 ; sans le contexte, elle reste à 0,90. Seuls, la similarité d'embeddings donne une AUC de 0,988, les coauteurs pondérés 0,853.
- [x] Évaluation hors entraînement (`echantillon_phase2.py`, `analyse_phase2.py`), le 2026-11-25. 33 647 contributions rattachées des personnes du jeu, hors des paires d'entraînement, notées par le modèle entraîné sur tout le jeu. Verdicts de l'administration sur 60 d'entre elles, présentées sans note dans un ordre mélangé (`verdicts_phase2/`).

  | Strate | Homonymes | De la personne | Incertaines |
  |---|---|---|---|
  | 30 contributions les moins bien notées | 12 | 14 | 4 |
  | 30 contributions tirées au hasard | 0 | 30 | 0 |

  - Précision des alertes : 12 sur 26 tranchées. AUC de 0,87 sur les 56 contributions tranchées.
  - Les 30 contributions basses ont une note de 0,001 au plus : les probabilités ne sont pas calibrées pour le stock.
  - 11 des 18 contributions basses rattachées par le nom sont de la personne : publications éloignées de ses autres publications, sans coauteur partagé. Les positifs d'entraînement, rattachés par ORCID, comptent peu de cas de ce genre.
  - Le modèle sans le nombre de contributions de la publication donne une AUC de 0,85.
- [x] Verdicts versés à l'entraînement, avec les 76 verdicts des alertes par embeddings (`tour.py`). 97 paires jugées dans le jeu, dont 27 négatives ; les autres homonymes jugés figurent parmi les rejets. Une paire jugée pèse 20 fois plus qu'une autre.
- [x] Indices supplémentaires : nombre de coauteurs à fiche RH dans la publication, adresse rattachée à un laboratoire RH de la personne (structures des périodes RH, leurs descendantes et leurs ascendantes de type laboratoire). Sur les paires jugées, notées hors pli, l'AUC passe de 0,913 à 0,957 ; sur tout le jeu, de 0,989 à 0,996.
- [x] Calibration de Platt sur les notes hors pli des paires jugées. Sur 33 583 contributions hors entraînement, 162 ont une probabilité sous 0,5, 39 sous 0,2.
- [x] Tour 2 : les 30 contributions les moins bien notées (`tour2.json`), jugées à l'aveugle (`analyse_tour.py`, `verdicts_tour2/`), le 2026-11-25. 10 homonymes, 17 publications de la personne, 2 incertaines : précision de 10 sur 27 tranchées.
  - Calibration : 11 % de publications de la personne prédites, 63 % observées. Les paires jugées sont trop peu nombreuses et trop riches en alertes pour calibrer.
  - Rattachement par le nom : 9 publications de la personne sur 10 tranchées. Rattachement par un ORCID donné par HAL seul : 6 homonymes sur 8 tranchées. Rattachement par IdRef : 3 homonymes sur 9.
  - Une personne à la production dispersée fournit 5 alertes, toutes de la personne. La similarité d'embeddings du modèle n'est pas normalisée par personne.
  - Restreintes aux contributions signalables, titres génériques écartés, les alertes du tour comptent 9 homonymes sur 15.
- [x] Indices : contributions du périmètre et contributions rattachées au CHU dans la publication, similarité normalisée par la dispersion du profil de la personne, similarité normalisée et score thématique croisés avec le nombre de contributions.
- [x] Banc d'essais hors ligne (`essais.py`), le 2026-11-25 : variantes notées hors pli sur les paires jugées restreintes aux alertes possibles (contribution signalable, titres et types génériques écartés). 79 paires, 28 homonymes, 51 publications de la personne.

  | Fonction de décision | AUC | Homonymes parmi les 10 / 20 / 30 moins bien notées |
  |---|---|---|
  | Similarité normalisée par personne | 0,78 | 6 / 13 / 19 |
  | Similarité brute aux voisines | 0,84 | 7 / 14 / 21 |
  | Règle des alertes par embeddings | 0,84 | 8 / 15 / 20 |
  | Régression logistique, indices du tour 2 | 0,93 | 8 / 18 / 23 |
  | Régression logistique, tous les indices | 0,93 | 9 / 16 / 25 |
  | Arbres de gradient, tous les indices | 0,94 | 10 / 17 / 23 |

  - Les modèles battent nettement les règles. Les indices ajoutés ne changent pas le résultat de façon mesurable sur 79 paires.
  - Les paires évaluées comptent 35 % d'homonymes. La précision des alertes dans le stock est plus basse.
  - Coauteurs dans la publication, homonymes contre publications de la personne : à fiche RH, 4 contre 24 dès un coauteur, 0 contre 8 à partir de trois ; du périmètre, 0 contre 10 à partir de cinq ; rattachés au CHU, 1 contre 8 à partir de deux.
  - L'écart de similarité normalisée entre publications de la personne et homonymes se réduit avec la taille de la publication : 2,1 points sous 10 contributions, 0,6 au-delà de 100.
- [x] Règle du groupe de coauteurs écartée : une contribution à au moins 3 coauteurs à fiche RH ou 5 coauteurs du périmètre, dans une publication de 100 contributions au plus, est retirée des alertes. Sur les paires évaluées, elle retire une fausse alerte des 30 premières. Sur tout le jeu, elle protège 235 paires négatives, dont 71 rejets : homonymes de l'établissement, entourés eux aussi de coauteurs du périmètre.

### Phase 3 — Arbres de gradient

- [ ] Arbres de gradient (`HistGradientBoosting`), comparés à la régression logistique.

### Phase 4 — Apprentissage actif

- [ ] Tours de jugement dans la page des alertes : paires les plus suspectes et paires les plus incertaines. Les verdicts rejoignent les étiquettes, puis le modèle est réentraîné et remesuré.

### Phase 5 — Intégration

Décisions du 2026-11-26 : embeddings dans une table à part (publication, modèle, empreinte du texte encodé, vecteur `real[]`), encodage plafonné en nombre de publications par run comme les interrogations d'API, dépendances fastembed et scikit-learn. Texte encodé : titre, puis résumé. Le modèle lit 128 tokens, soit environ 520 caractères en médiane. L'empreinte porte sur les 1 000 premiers caractères.

- [x] Dépendance fastembed. c1761acdc
- [ ] Dépendance scikit-learn, avec la tâche de notation des paires.
- [x] Migration : table `publication_embeddings`, clé `embeddings_max_per_run` (3 000 par défaut). c1761acdc
- [x] Phase `embeddings`, après `subjects` : publications sans embedding, ou dont l'empreinte du texte ou le modèle diffère, dans la limite du plafond. c1761acdc
- [x] Commande `encode_publications` pour remplir le stock hors run. c1761acdc
- [x] Modèle intégré à l'image Docker (241 Mo), dans une couche gardée en cache tant que le modèle ne change pas. e5b4f22d4
- [ ] Remplissage du stock : 78 715 publications.
- [ ] Tâche de notation des paires et motif « modèle » de la file des attributions suspectes, limité aux contributions signalables.
- [ ] Identifiants comme second signal. Un désaccord entre le modèle et les identifiants signale une erreur d'identifiant ou une fausse attribution, présentée à l'administration.
- [ ] Résolution indépendante de l'ordre d'arrivée des enregistrements sources. Les rattachements non épinglés sont remis en jeu à chaque passage.

## Questions ouvertes

- Écart minimal entre la meilleure personne candidate et la suivante pour rattacher une contribution.
