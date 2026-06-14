# Chantier — Qualité et cohérence des sujets

## Contexte

Quatre problèmes connexes sur `subjects` / `publication_subjects` repérés à l'usage :

1. **Sujets OpenAlex hors-sujet** : les sujets OpenAlex (`publication_subjects.source = 'openalex'`) sont fréquemment aberrants à l'inspection — bruit de l'algo OA sur les revues généralistes / pluridisciplinaires, ou attribution thématique retenue sans filtrage. Le champ `score` existe, aucun seuil n'est appliqué.

2. **Pas de circuit de curation manuelle** : la colonne `publication_subjects.rejected` (boolean default false) n'est pas exposée à l'admin. Pas de voie ouverte pour marquer manuellement un sujet comme non pertinent.

3. **Couverture sujets variable** : certaines publis sans sujet, origines à inventorier.

4. **Sujets aberrants pour une revue** : signal de cohérence éditoriale non exploité (importé de [METIER_publishers-journals 4d](archived/2026-05-29_METIER_publishers-journals.md)).

5. **Prolifération des keywords libres** : sur ~311k sujets, **303k sont des keywords libres** (sans ontologie), dont ~100k singletons (1 seule publication) et de nombreuses variantes non fusionnées (EN/FR, orthographe, pluriels). Bruit qui gonfle le référentiel et les co-occurrences. Réduction = famille du **matching approximatif** : normalisation + trigrammes (`pg_trgm`) / distance d'édition / phonétique / embeddings — pas Aho-Corasick (qui relève du matching de sous-chaînes, ex. détecteur d'adresses). Décision ouverte : faut-il ingérer les keywords libres comme sujets à part entière, ou les fusionner / les traiter à part ?

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

- **Statut** : one-shot bootstrap, pas une phase pipeline. Vocation à disparaître quand Specter2 sera rodé et autonome — pas de dualité d'infrastructure à long terme.
- **Granularité** : domains OpenAlex (level 0, 4 valeurs). Le mapping ontologique reste petit et tractable à ce grain.
- **Arbitres** : `hal_domain`, `wos_subject`, `theses_discipline` (labels des autres `source_publications`) + `journals.doaj_payload->>'Subjects'` (premier niveau LCC du journal DOAJ). Multi-affectation acceptée (un label peut peser pour plusieurs domains OA en cas d'ambiguïté inhérente — ex. « Neurosciences » → health + life).
- **Règle de rejet** : pour une publi avec ≥2 domains OA, un domain est rejeté si son support arbitre vaut 0 **et** qu'au moins un autre domain de la publi a un support > 0. La variante « autre support ≥ 2 » a été testée sur sample : elle perd 12 vrais positifs sur 20 cas exclus (arbitres HAL minimalistes type « Sciences du Vivant » seul ne franchissent jamais le seuil). Trade-off défavorable, on garde le seuil souple.
- **Précision empirique attendue** : ~70-80 % sur sample (sample 15 publis : 10 vrais positifs, 1 faux positif clair, 4 borderline).
- **Cascade obligatoire** : le rejet d'un domain entraîne le rejet en cascade des descendants OpenAlex sur la publi (field / subfield / topic dont la chaîne `parent` remonte à ce domain). OA insère toujours les 4 niveaux de la chaîne, donc tous les descendants sont présents en base au moment du rejet.

**Specter2 — couche fine par similarité sémantique**, à prototyper après le bootstrap :

- **Granularité** : topics feuille OA (level 3) — là où le cleanup grain domain est aveugle.
- **Représentation** : embedding Specter2 sur titre + abstract de chaque publi ; centroïde par sujet calculé sur le corpus déjà nettoyé par le bootstrap.
- **Score** : cosine entre embedding publi et centroïde sujet → seuil à calibrer empiriquement (bottom-up sur cas validés à l'œil).
- **Ordre** : bootstrap d'abord, Specter2 ensuite. Justification : le bootstrap retire les aberrations grossières grain domain avant calcul des centroïdes → centroïdes plus propres pour le grain topic. Les deux couches sont complémentaires (grains différents), pas redondantes.
- **Cible long terme** : Specter2 autonome remplace le bootstrap. Aucune intégration permanente côté code applicatif pour la couche bootstrap.

**Contraintes UI** : tous les sujets `rejected = TRUE` doivent être exclus des décomptes et des listings — pages `/subjects`, `/subjects/[id]`, dashboards `/persons/[id]` et `/laboratories/[id]`. Seule la page `/publications/[id]` continue à les afficher (temporairement), avec un style barré + grisé pour permettre un contrôle visuel des rejets au fil de l'eau.

**Pistes mises de côté** : seuil de score OA seul (invalidé empiriquement), lift cooccurrence sujets feuille (invalidé : les aberrations sont récurrentes), seuil « autre support ≥ 2 » sur cleanup (trade-off rappel/précision défavorable). UI curation manuelle des rejets : utile en complément ponctuel, traitée hors de ce chantier.

## Phasage

- [ ] **Phase 1 — One-shot `cleanup_oa_subjects`** : `interfaces/cli/oneshot/cleanup_oa_subjects.py`. Mapping arbitre en data du script (dict Python). SQL set-based : détection des rejets candidats + cascade descendants via la chaîne `parent`. UPDATE `publication_subjects SET rejected = TRUE`. Tests sur cas tirés du prototype SQL. `--dry-run` pour itération.
- [ ] **Phase 2 — Ajustements UI** : filtrer `rejected = TRUE` partout sauf `/publications/[id]`. Style barré + grisé sur `/publications/[id]`. Vérifier que `recompute_usage_counts` et `recompute_cooccurrences` filtrent bien (déjà OK côté SQL au moment de la rédaction).
- [ ] **Phase 3 — Prototype Specter2** : extraction embeddings (Specter2 base via HuggingFace, batch sur titres + abstracts existants). Persistance vecteurs (pgvector ou fichier numpy + lookup).
- [ ] **Phase 4 — Centroïdes par topic + score similarité** : calcul des centroïdes sur publis nettoyées par le bootstrap, score cosine pour chaque lien `publication_subjects`. Vue admin temporaire pour calibration manuelle du seuil.
- [ ] **Phase 5 — Rejet Specter2 autonome** : application du seuil calibré, en remplacement du bootstrap.

## Questions ouvertes

- **Réversibilité du bootstrap** : un re-run de `cleanup_oa_subjects` doit-il reset les rejets précédents avant de recalculer ? (idempotence) Penche oui — sinon évolution du mapping arbitre = rejets fantômes persistants.
- **Spécifications Specter2** : variante du modèle (`allenai/specter2_base` vs `proximity` vs `classification`), backend (HuggingFace local CPU/GPU vs hébergement), persistance vecteurs (pgvector vs fichier numpy + lookup).
- **Volume corpus** : 46k publis × Specter2 embedding. CPU acceptable mais lent ; GPU bienvenu si disponible.

## Liens

- Table `publication_subjects` (`score`, `rejected`) — infrastructure partielle déjà en place.
- Table `subject_cooccurrences` — produit du chantier précédent « Exploiter sujets et mots-clés » (cf. [0_INDEX](0_INDEX.md)).
