# Pertinence des sujets

## Contexte

Base locale au 2026-10-25 : 74 585 publications, 734 400 liens publication–sujet, dont 566 967 (77 %) viennent d'OpenAlex.

- **Sujets OpenAlex aberrants.** Ils sont fréquents à l'inspection, surtout sur les revues généralistes et pluridisciplinaires. Le `score` OpenAlex est stocké dans `source_records.topics`. L'ingestion des sujets l'ignore.
- **Rejet inutilisé.** La colonne `publication_subjects.rejected` existe, mais aucun code ne l'écrit. L'ingestion conserve les liens rejetés. `usage_count` et `subject_cooccurrences` les écartent, donc les pages `/subjects` et `/subjects/[id]` aussi. Les nuages de sujets (`entity_subjects_sql`), le filtre par sujet et la fiche d'une publication les montrent.
- **Publications sans sujet** : 1 626.
- **Sujet incohérent avec la revue** : signal inexploité. Les sujets DOAJ sont connus pour 2 325 revues sur 10 860 (`serials.doaj_payload`).
- **Hiérarchie.** `subjects` porte un libellé, sans parent. La chaîne domain → field → subfield → topic d'OpenAlex et le chemin des domaines HAL existent seulement dans `source_records.topics`.

### Constats de l'exploration (corpus de 46 000 publications)

**Score OpenAlex des topics feuille.** Distribution bimodale : 52 000 liens à 0,9 ou plus (65 %), 16 000 sous 0,1. Qualification à l'œil :

| Score | Aberrations | Vrais positifs |
|---|---|---|
| ≥ 0,9 | 15 à 20 % | 80 à 85 % |
| < 0,1 | 25 % | 50 à 60 %, topics secondaires pertinents |

Le score n'est pas une mesure de pertinence. Un seuil bas écarte des topics légitimes. Un seuil haut laisse le bruit.

**Paires de domains OpenAlex.** Health × Life est sur-représentée (lift 1,34), les cinq autres paires sous-représentées (0,27 à 0,62). Sur 15 publications Health × Physical (1 070 au total), 10 portent un domain manifestement aberrant. Les libellés HAL, WoS et theses.fr des autres enregistrements sources suffisent à trancher.

**Mécanisme des aberrations.** OpenAlex semble évaluer chaque topic indépendamment, puis rattacher au topic retenu toute sa chaîne de parents. Un topic plausible entraîne ainsi un domain absurde : « Competency Development and Evaluation » pour un référentiel de compétences en pharmacie clinique, avec le field « Psychology ».

**Co-occurrences de sujets.** Les aberrations OpenAlex sont récurrentes : un même sujet mal attribué produit la même paire sur de nombreuses publications. Les paires rares ne les repèrent donc pas.

### Pistes

Les trois pistes n'opèrent pas au même grain. Elles peuvent se combiner.

**Classifieurs ISTEX.** La plateforme ISTEX TDM propose des web services de classification gratuits, appelables document par document. Aucun ne rend de score. Chacun propose une seule classe par document : il ne confirme pas le second domain d'une publication pluridisciplinaire. Les services reçoivent des lots `[{id, value}]`. Grain : domaine HAL, ou domain et field OpenAlex.

| Service | Entrée | Sortie | Performance annoncée |
|---|---|---|---|
| [halClass](https://services.istex.fr/classification-dans-les-domaines-hal/) | titre + résumé, français ou anglais | 1 domaine HAL parmi 13 : code, libellés fr et en | exactitude 0,87 |
| [openAlexClass](https://services.istex.fr/classification-en-domaines-scientifiques-openalex/) | résumé anglais | domain + field OpenAlex, libellés | F-mesure 0,88 sur domain |
| [sciencemetrixClass](https://services.istex.fr/classification-en-domaines-scientifiques-science-metrix/) | résumé anglais, 100 caractères minimum | 3 niveaux Science-Metrix, libellés | exactitude 0,85 |
| [pascalFrancisClass](https://services.istex.fr/classification-en-domaines-scientifiques/) | texte anglais | plan Pascal ou Francis, profondeur 1 à 3 | — |

**Vote des arbitres**, au grain des domains OpenAlex (4 valeurs) :

- arbitres : domaines HAL, disciplines theses.fr de la même publication, sujets DOAJ de sa revue (premier niveau de la classification LCC) ;
- un arbitre peut soutenir plusieurs domains (« Neurosciences » soutient Health et Life) ;
- sur une publication à plusieurs domains, un domain sans soutien est rejeté si un autre domain a au moins un soutien. Le seuil « au moins deux soutiens » perd 12 vrais positifs sur 20 cas : les arbitres HAL réduits à « Sciences du Vivant » ne le franchissent jamais ;
- le rejet d'un domain s'étend aux field, subfield et topics qui en descendent sur la publication ;
- précision mesurée sur 15 publications, WoS compris : 10 vrais positifs, 1 faux positif, 4 cas limites.

**Embeddings** (Specter2), au grain des topics feuille : embedding du titre et du résumé, centroïde par topic calculé sur ses publications, similarité cosinus entre chaque publication et le centroïde de chacun de ses topics, seuil de rejet. Chaque libellé porte le chemin de tous ses ancêtres. L'évaluation descend la hiérarchie : les sous-sujets d'un sujet écarté ne sont pas évalués.

## Décisions

- **Auditer avant de coder.** Les trois pistes sont évaluées sur un même échantillon qualifié à l'œil, de la moins coûteuse à la plus coûteuse : classifieurs ISTEX, vote des arbitres, embeddings. Le choix d'une piste ou d'une combinaison suit les bilans.
- **Un libellé est inclus dans son parent.** Un libellé pertinent rend ses ancêtres pertinents. Un libellé aberrant rend ses descendants aberrants. La qualification de l'échantillon et chaque piste respectent cette inclusion.
- **WoS est exclu des arbitres** : l'abonnement va être résilié.
- **Un rejet automatique se recalcule. Un rejet manuel est une décision humaine durable.**
- **Affichage des rejets.** Les liens rejetés sont exclus des décomptes et des listes : `/subjects`, `/subjects/[id]`, nuages de sujets des personnes, structures, revues et éditeurs, filtre par sujet. La fiche `/publications/[id]` les affiche barrés et grisés, pour le contrôle visuel des rejets.
- **Pistes écartées** : seuil sur le score OpenAlex, co-occurrences rares entre topics feuille, seuil « au moins deux soutiens », identification des sujets par code.

## Phasage

### Discipline des thèses

- [x] Une seule copie de la discipline, `topics.discipline`, lue par l'extracteur de sujets et par la fiche de la thèse ; le normalizer theses.fr cesse d'écrire `source_extras.discipline`
- [ ] Stock : renormalisation des enregistrements theses.fr depuis `staging`

### Phase 1 — Échantillon de référence

- [x] Tirage stratifié de 100 publications (`sample_subject_relevance`) : revues généralistes, publications sans domaine HAL ni discipline theses.fr, paires de domains rares, Health × Life, un seul domain ; 907 libellés OpenAlex. feeb8f8d1
- [x] Préqualification par Claude, sur le titre, le résumé et la revue
- [x] Relecture à l'œil d'une partie des publications : la préqualification sert de référence
- [x] Taux d'aberration par grain : 13 % des domains, 15 % des fields, 28 % des subfields, 34 % des topics. 79 des 100 topics aberrants sont sous un domain pertinent ou limite, 69 sous un field pertinent ou limite : une piste au grain domain ou field en écarte au plus 31 %

### Phase 2 — Classifieurs ISTEX

- [ ] Débit et limites d'usage de halClass et openAlexClass
- [ ] Couverture : part des publications pourvues d'un résumé, d'un résumé anglais ; même mesure sur les publications sans sujet
- [ ] Appels sur l'échantillon (`evaluate_istex_classifiers`) ; accord avec la qualification au grain domain et field
- [ ] Bilan : précision et rappel des rejets qui en découleraient, couverture, coût d'un passage sur le stock et sur chaque run

### Phase 3 — Vote des arbitres

- [x] Correspondance des arbitres vers les domains OpenAlex : codes de domaine HAL, codes LCC des revues DOAJ, mots-clés des disciplines theses.fr (libellés libres, 471 distincts)
- [x] Prototype sur l'échantillon, cascade comprise (`prototype_subject_vote`)
- [x] Variante : profil de la revue (domains de ses autres publications) et profil des laboratoires (domains de leurs autres publications), calculés sur les domaines HAL, les disciplines theses.fr et les revues DOAJ. Un profil vote à partir de 20 publications, soutient les domains qui pèsent au moins 15 %, et s'abstient s'il soutient les quatre
- [x] Bilan. Sur les 52 publications à plusieurs domains, l'échantillon compte 20 domains aberrants : les effectifs sont faibles.

  | Arbitres | Publications où le vote s'applique | Domains rejetés : aberrants / pertinents / limites | Précision et rappel, tous niveaux |
  |---|---|---|---|
  | Publication (HAL, theses.fr, DOAJ) | 32 | 8 / 14 / 7 | 48 %, 23 % |
  | Profil de la revue | 10 | 0 / 1 / 1 | 60 %, 3 % |
  | Profil des laboratoires | 39 | 7 / 4 / 4 | 72 %, 17 % |
  | Publication + laboratoires | 43 | 8 / 5 / 5 | 70 %, 20 % |

  Les arbitres de la publication rejettent à tort surtout à la frontière Health/Life : un seul code HAL (`sdv`, `sdv.mhep`) soutient l'un des deux domains quand la publication relève des deux. Confondre Health et Life dans le vote n'améliore pas la précision. Le vote au grain domain plafonne bas : la plupart des aberrations sont des topics sous un domain correct.
- [ ] Variante : classifieur ISTEX comme arbitre supplémentaire

### Phase 4 — Embeddings

- [x] Décision de mener la phase : les pistes au grain domain ou field n'atteignent pas les topics aberrants sous un domain correct
- [x] Prototype sans centroïdes, modèle multilingue `intfloat/multilingual-e5-base` : similarité entre la publication (titre et résumé) et le chemin complet de chaque libellé, règle descendante.

  | Score | AUC domain / field / subfield / topic |
  |---|---|
  | Similarité cosinus | 0,67 / 0,71 / 0,72 / 0,71 |
  | Rang parmi tous les libellés du niveau | 0,72 / 0,80 / 0,83 / 0,77 |
  | Écart au meilleur libellé de la publication au même niveau | 0,71 / 0,71 / 0,71 / 0,69 |

  Meilleurs points de fonctionnement, tous niveaux : écart ≤ −0,03, précision 70 %, rappel 32 % ; rang dans la moitié basse du niveau, précision 59 %, rappel 35 %. À précision égale, le rappel dépasse celui du vote (20 %). Le modèle `BAAI/bge-m3`, deux fois plus gros, ne fait pas mieux (AUC du rang : 0,77 / 0,77 / 0,77 / 0,75). Le libellé seul, quelques mots, décrit mal un sujet : les centroïdes devraient faire mieux
- [x] Prototype à centroïdes, `multilingual-e5-base` : centroïde de chaque libellé sur 20 autres publications qui le portent, de préférence en premier topic (7 326 publications encodées). Score : typicité, part des publications du libellé moins proches du centroïde que la publication évaluée.

  | Score | AUC domain / field / subfield / topic |
  |---|---|
  | Similarité cosinus au centroïde | 0,79 / 0,67 / 0,63 / 0,59 |
  | Typicité | 0,84 / 0,66 / 0,60 / 0,58 |

  Les centroïdes font mieux que les libellés au grain domain, moins bien en dessous. Règle descendante sur la typicité : précision 47 %, rappel 52 %. Un topic aberrant est textuellement plausible : OpenAlex attribue ses topics d'après le titre et le résumé, et une similarité de texte reproduit son signal. L'incohérence se voit au grain domain
- [ ] Coût d'un passage sur le stock et sur chaque run

### Phase 5 — Choix et mise en œuvre

- [ ] Choix de la piste ou de la combinaison, d'après les bilans des phases 2 à 4
- [ ] Forme du stockage des rejets automatiques et manuels
- [ ] Phasage de la mise en œuvre dans la phase `subjects`

### Phase 6 — Rejets dans l'interface

- [ ] Nuages de sujets (`entity_subjects_sql`), filtre et facette par sujet (`infrastructure/read_models/filters.py`, `entity_facet.py`) : liens rejetés écartés
- [ ] `/publications/[id]` : `get_publication_subjects` rend le statut de rejet ; `SubjectsBlock.svelte` barre et grise les sujets rejetés
- [ ] Guide utilisateur : sens d'un sujet barré

## Questions ouvertes

- **Stockage des rejets.** Le booléen `rejected` confond rejet automatique et rejet manuel. Un rejet manuel accroché à `publication_id` disparaît avec la publication. Quelle forme donner aux deux ?
- **Édition manuelle des rejets** : dans ce chantier ou dans [la gestion des publications dans l'administration](METIER_gestion-admin-des-publications.md) ?
- **Provenance des sujets ISTEX**, si les classifieurs donnent des sujets aux publications qui n'en ont pas : l'énumération `source_type` de `publication_subjects.source` ne la prévoit pas.
- **Specter2** : variante du modèle (`allenai/specter2_base`, `proximity`, `classification`), exécution (locale sur CPU ou GPU, ou hébergée), persistance des vecteurs (pgvector ou fichier numpy). 74 600 publications à encoder.
