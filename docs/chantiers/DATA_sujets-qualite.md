# Chantier — Qualité et cohérence des sujets

## Contexte

Problèmes connexes sur `subjects` / `publication_subjects` repérés à l'usage :

1. **Sujets OpenAlex hors-sujet** : les sujets OpenAlex (`publication_subjects.source = 'openalex'`) sont fréquemment aberrants à l'inspection — bruit de l'algo OA sur les revues généralistes / pluridisciplinaires, ou attribution thématique retenue sans filtrage. Le `score` OpenAlex figure dans `source_publications.topics`, et l'ingestion l'ignore.

2. **Pas de circuit d'édition manuelle** : la colonne `publication_subjects.rejected` (boolean default false) n'est pas exposée à l'admin. Pas de voie ouverte pour marquer manuellement un sujet comme non pertinent.

3. **Couverture sujets variable** : certaines publis sans sujet, origines à inventorier.

4. **Sujets aberrants pour une revue** : signal de cohérence éditoriale non exploité (importé de [METIER_publishers-journals 4d](archived/2026-05-29_METIER_publishers-journals.md)).

5. **Domaines HAL réduits à leurs codes** : 28 186 notices HAL sur 52 500 (base locale) portent seulement des codes de domaine (`0.shs`, `1.shs.hist`). Elles ont été normalisées avant le passage au champ `fr_domainAllCodeLabel_fs`, qui porte les libellés, et jamais renormalisées depuis. L'extracteur n'en tire aucun sujet. Leurs données brutes portent seulement `domain_s` : une renormalisation effacerait leurs domaines. Le référentiel des domaines de l'API HAL (`ref/domain`, 393 codes, chemin complet des libellés) couvre 388 des 400 codes présents ; les 12 autres sont des codes retirés.

6. **Libellés stockés dans chaque notice** : chaque `source_publication` porte le texte de ses sujets. Plusieurs sources donnent pourtant un code : domaines HAL, topics OpenAlex (`T11930`), vedettes sudoc de ScanR (PPN). Changer un libellé demande de renormaliser toutes les notices qui le portent.

7. **Hiérarchie aplatie** : `subjects` contient un libellé par sujet, sans vocabulaire ni parent. Les libellés identiques de deux vocabulaires fusionnent. La chaîne domain → field → subfield → topic d'OpenAlex existe seulement dans `source_publications.topics`.

### Classifieurs ISTEX

La plateforme ISTEX TDM propose des web services de classification gratuits, appelables document par document :

| Service | Entrée | Sortie | Performance annoncée |
|---|---|---|---|
| [halClass](https://services.istex.fr/classification-dans-les-domaines-hal/) | titre + résumé, français ou anglais | 1 domaine HAL parmi 13 : code, libellés fr et en | exactitude 0,87 |
| [openAlexClass](https://services.istex.fr/classification-en-domaines-scientifiques-openalex/) | résumé anglais | domain + field OpenAlex, libellés | F-mesure 0,88 sur domain |
| [sciencemetrixClass](https://services.istex.fr/classification-en-domaines-scientifiques-science-metrix/) | résumé anglais, 100 caractères minimum | 3 niveaux Science-Metrix, libellés | exactitude 0,85 |
| [pascalFrancisClass](https://services.istex.fr/classification-en-domaines-scientifiques/) | texte anglais | plan Pascal ou Francis, profondeur 1 à 3 | — |

Aucun ne rend de score par document.

### Constats empiriques de la session d'exploration

**Distribution du `score` OpenAlex sur topics feuille (level 3)** : bimodale, 52k liens à ≥0.9 (65 %) et 16k à <0.1. Échantillons qualifiés à l'œil :

| Bucket score | Aberrations | Vrais positifs |
|---|---|---|
| ≥0.9 (52k liens) | ~15-20 % | ~80-85 % |
| <0.1 (16k liens) | ~25 % | ~50-60 % de bons topics secondaires |

Conséquence : **le score OpenAlex n'est pas un proxy linéaire de pertinence**. Couper bas perd des topics légitimes (faux négatifs massifs). Couper haut ne nettoie pas le bruit injecté par surfaccrochage lexical de l'algo OA. → Piste « seuil de score » seule abandonnée.

**Lift entre domains OpenAlex (level 0)** : 6 paires possibles entre Health / Life / Physical / Social. La paire Health × Life est sur-attendue (1.34) ; toutes les autres sous-attendues (0.27 à 0.62). Sur la paire la plus suspecte (Health × Physical, 1070 publis), validation à l'œil de 15 publis : **~67 % ont au moins un domain manifestement aberrant**, et l'arbitrage est **lisible directement sur les labels HAL / WoS / theses_discipline** des autres source_publications (Neurosciences, Chimie, Sciences Terre, etc.) sans mapping ontologique sophistiqué.

**Co-occurrences sujet-sujet** : la piste « paire unique entre deux sujets fréquents » a été écartée — les aberrations OpenAlex sont **récurrentes** (un sujet `Health Sciences` mal accroché à des publis hors-santé reproduit la même co-occurrence souvent), donc les paires uniques ratent précisément les vrais bruits.

## Décisions

**Cleanup par vote d'arbitres haut niveau — bootstrap transitoire**, validé par prototypage SQL (3 itérations sur sample) :

- **Statut** : one-shot bootstrap, pas une phase pipeline. Vocation à disparaître quand une classification autonome sera rodée.
- **Granularité** : domains OpenAlex (level 0, 4 valeurs). Le mapping ontologique reste petit et tractable à ce grain.
- **Arbitres** : `hal_domain`, `wos_subject`, `theses_discipline` (labels des autres `source_publications`) + `journals.doaj_payload->>'Subjects'` (premier niveau LCC du journal DOAJ). Multi-affectation acceptée (un label peut peser pour plusieurs domains OA en cas d'ambiguïté inhérente — ex. « Neurosciences » → health + life).
- **Règle de rejet** : pour une publi avec ≥2 domains OA, un domain est rejeté si son support arbitre vaut 0 **et** qu'au moins un autre domain de la publi a un support > 0. La variante « autre support ≥ 2 » a été testée sur sample : elle perd 12 vrais positifs sur 20 cas exclus (arbitres HAL minimalistes type « Sciences du Vivant » seul ne franchissent jamais le seuil). Trade-off défavorable, on garde le seuil souple.
- **Précision empirique attendue** : ~70-80 % sur sample (sample 15 publis : 10 vrais positifs, 1 faux positif clair, 4 borderline).
- **Cascade obligatoire** : le rejet d'un domain entraîne le rejet en cascade des descendants OpenAlex sur la publi (field / subfield / topic rattachés à ce domain). Chaque entrée de `source_publications.topics` contient les 4 niveaux de la chaîne : la cascade y lit la hiérarchie.

**Classifieurs ISTEX avant Specter2.** Les classifieurs ISTEX donnent un arbitre indépendant de l'algorithme OpenAlex, et des sujets aux publications qui n'en ont aucun. Specter2 se prototype seulement si leur évaluation montre qu'ils ne suffisent pas.

**Specter2 — couche fine par similarité sémantique**, à prototyper après le bootstrap et l'évaluation des classifieurs ISTEX :

- **Granularité** : topics feuille OA (level 3) — là où le cleanup grain domain est aveugle.
- **Représentation** : embedding Specter2 sur titre + abstract de chaque publi ; centroïde par sujet calculé sur le corpus déjà nettoyé par le bootstrap.
- **Score** : cosine entre embedding publi et centroïde sujet → seuil à calibrer empiriquement (bottom-up sur cas validés à l'œil).
- **Ordre** : bootstrap d'abord, Specter2 ensuite. Justification : le bootstrap retire les aberrations grossières grain domain avant calcul des centroïdes → centroïdes plus propres pour le grain topic. Les deux couches sont complémentaires (grains différents), pas redondantes.
- **Cible long terme** : Specter2 autonome remplace le bootstrap.

**Codes plutôt que libellés.** La refonte du traitement des sujets s'appuie sur une table de correspondance code → sujet, commune aux sources qui donnent un code. Les notices stockent les codes ; la table donne les libellés. Les notices HAL réduites à leurs codes redeviennent exploitables sans nouvel import.

**Contraintes UI** : tous les sujets `rejected = TRUE` doivent être exclus des décomptes et des listings — pages `/subjects`, `/subjects/[id]`, dashboards `/persons/[id]` et `/laboratories/[id]`. Seule la page `/publications/[id]` continue à les afficher (temporairement), avec un style barré + grisé pour permettre un contrôle visuel des rejets au fil de l'eau.

**Pistes mises de côté** : seuil de score OA seul (invalidé empiriquement), lift cooccurrence sujets feuille (invalidé : les aberrations sont récurrentes), seuil « autre support ≥ 2 » sur cleanup (trade-off rappel/précision défavorable). UI d'édition manuelle des rejets : utile en complément ponctuel, traitée hors de ce chantier.

## Phasage

- [ ] **Phase 0 — Correspondance code → sujet** : schéma de la table (source, code, sujet) ; normalisation des codes par source (domaines HAL depuis `domain_s`, topics OpenAlex, vedettes sudoc ScanR) ; remplissage depuis les référentiels des sources (API HAL `ref/domain`…) ; ingestion par la table. Les 28 186 notices HAL réduites à leurs codes retrouvent leurs sujets.
- [ ] **Phase 1 — One-shot `cleanup_oa_subjects`** : `interfaces/cli/oneshot/cleanup_oa_subjects.py`. Mapping arbitre en data du script (dict Python). SQL set-based : détection des rejets candidats + cascade descendants via la hiérarchie de `source_publications.topics`. UPDATE `publication_subjects SET rejected = TRUE`. Tests sur cas tirés du prototype SQL. `--dry-run` pour itération.
- [ ] **Phase 2 — Ajustements UI** : filtrer `rejected = TRUE` partout sauf `/publications/[id]`. Style barré + grisé sur `/publications/[id]`. Vérifier que `recompute_usage_counts` et `recompute_cooccurrences` filtrent bien (déjà OK côté SQL au moment de la rédaction).
- [ ] **Phase 3 — Évaluation des classifieurs ISTEX** : appeler halClass et openAlexClass sur un échantillon de publications dont les sujets HAL, WoS ou theses.fr sont connus. Mesurer l'accord avec ces sujets et avec les domains OpenAlex. Mesurer la couverture : part des publications pourvues d'un résumé, et d'un résumé anglais. Trancher l'usage : arbitre du bootstrap, source de sujets pour les publications sans sujet, ou rien.
- [ ] **Phase 4 — Prototype Specter2**, si la phase 3 conclut que les classifieurs ISTEX ne suffisent pas : extraction embeddings (Specter2 base via HuggingFace, batch sur titres + abstracts existants). Persistance vecteurs (pgvector ou fichier numpy + lookup).
- [ ] **Phase 5 — Centroïdes par topic + score similarité** : calcul des centroïdes sur publis nettoyées par le bootstrap, score cosine pour chaque lien `publication_subjects`. Vue admin temporaire pour calibration manuelle du seuil.
- [ ] **Phase 6 — Rejet Specter2 autonome** : application du seuil calibré, en remplacement du bootstrap.
- [ ] **Redondance `topics.theses.discipline`** (connexe, hors flux OA/Specter2) : `meta.discipline` fait foi pour la discipline d'une thèse ; `topics.theses.discipline` en garde une copie. Décider d'arrêter d'écrire la copie (normalizer theses) et de purger l'existant.

## Questions ouvertes

- **Réversibilité du bootstrap** : un re-run de `cleanup_oa_subjects` doit-il reset les rejets précédents avant de recalculer ? (idempotence) Penche oui — sinon évolution du mapping arbitre = rejets fantômes persistants.
- **Spécifications Specter2** : variante du modèle (`allenai/specter2_base` vs `proximity` vs `classification`), backend (HuggingFace local CPU/GPU vs hébergement), persistance vecteurs (pgvector vs fichier numpy + lookup).
- **Volume corpus** : 46k publis × Specter2 embedding. CPU acceptable mais lent ; GPU bienvenu si disponible.
- **Sources sans code** : WoS et la discipline theses.fr donnent-elles un code ? À défaut, leur libellé sert-il de code ?
- **Codes retirés** : les 12 codes HAL absents du référentiel (`spi.energ`, `shs.info.*`…) gardent-ils un libellé repris de l'historique, ou seulement leurs niveaux parents ?
- **Sujets ISTEX** : un sujet produit par un classifieur ISTEX demande une provenance distincte des sources, que l'énumération `source_type` de `publication_subjects.source` ne prévoit pas. Quelle forme lui donner ?
- **Hiérarchie** : la table de correspondance de la phase 0 contient-elle le vocabulaire et le parent de chaque code ?
- **Ordre** : la phase 0 change les libellés que le bootstrap prend pour arbitres. La mener avant la phase 1 évite de calibrer deux fois.

## Liens

- Table `publication_subjects` (`rejected`).
- Table `subject_cooccurrences` — produit du chantier précédent « Exploiter sujets et mots-clés » (cf. [0_INDEX](0_INDEX.md)).
