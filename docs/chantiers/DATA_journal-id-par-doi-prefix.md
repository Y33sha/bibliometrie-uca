# Chantier — Déduire le journal_id manquant par préfixe DOI

Commencé le 2026-06-28

Rattacher à leur journal les publications qui portent un DOI mais aucun journal_id, lorsque le préfixe de ce DOI désigne sans ambiguïté un journal connu. Ce rattachement répare un manque de rattachement, et — par effet de bord — débloque les corrections de doc_type qui dépendent du type de journal.

## Contexte

### Le constat

Une partie des publications du périmètre portent un DOI mais aucun journal_id : leur source ne fournissait pas d'identifiant de revue exploitable à la normalisation (ni ISSN, ni titre de conteneur rapprochable). Une exploration de la base en dénombre environ 6300 dans le périmètre. Parmi elles, environ 430 ont un DOI dont le préfixe correspond au `doi_prefix` d'un seul journal existant, sans aucun cas multi-journal : elles sont donc rattachables sans ambiguïté. La très grande majorité (plus de 98 %) sont typées `preprint` à tort — des articles ou tribunes dont la source (souvent OpenAlex) a deviné `preprint` faute de mieux.

Le plus gros contributeur est The Conversation France (préfixe `10.64628/aak`), pour environ 270 publications, suivi de revues scientifiques classiques (Atmospheric Chemistry and Physics sous `10.5194/acp`, Atmospheric Measurement Techniques sous `10.5194/amt`, Biogeosciences sous `10.5194/bg`), de Preprints.org (`10.20944/preprints`) et de quelques unités dispersées.

### Où la résolution du journal a lieu aujourd'hui

Le journal_id d'une `source_publication` est résolu en **normalisation** : chaque normalizer appelle `upsert_journal` (rapprochement ou création d'un journal à partir des métadonnées de la source) et pose le journal_id sur la `source_publication`. La phase `publishers_journals` qui suit **enrichit la table journals** (typage via OpenAlex, import DOAJ, résolution des préfixes DOI) mais n'écrit ni dans `publications` ni dans `source_publications.journal_id`. La phase `publications` agrège ensuite le journal_id des sources vers le canonique (`refresh_from_sources`, premier non-nul par priorité de source).

La phase `metadata_correction` corrige les champs d'une `source_publication` — `doc_type`, `journal_id`, `oa_status`, `external_ids` — en repartant du brut reconstruit, de façon idempotente. Le `journal_id` y est **déjà un champ corrigeable** (présent dans les champs unaires gérés, et l'écriture est déjà câblée), mais **aucune règle ne le produit** à ce jour. Cette phase porte déjà des corrections qui s'appuient sur les données du journal (la famille de règles `JOURNAL_TYPE_*`, qui dépend du type du journal rattaché) et des corrections de DOI. Elle tourne après `publishers_journals`, donc les journals et leur `doi_prefix` sont disponibles quand elle s'exécute.

### La granularité de `journals.doi_prefix`

`journals.doi_prefix` n'est pas le registrant nu (`10.5194`, partagé par tout un éditeur) mais le **namespace propre au journal**, sous-chemin inclus (`10.5194/acp`, `10.64628/aak`). C'est ce qui rend le préfixe quasi univoque : sur les journaux qui en portent un, l'écrasante majorité ne désigne qu'un seul journal, une poignée seulement étant partagée. Le rapprochement se fait donc par « le DOI de la publication commence par le `doi_prefix` du journal », et les éditeurs multi-journaux sont désambiguïsés par le sous-chemin.

La valeur est dérivée des DOI des publications déjà rattachées : le script `interfaces/cli/oneshot/seed_journals_doi_prefix.py` calcule leur plus long préfixe commun, retire la queue variable, et n'écrit que les cas sans ambiguïté (filtrage preprint, garde ISBN, refus du publisher-only). Aucune phase du pipeline ne la produit ; elle est donc un **instantané figé**, complété au besoin par édition manuelle. Aucune API externe ne résout un préfixe vers un journal (Crossref/DataCite ne donnent que le publisher), donc cette dérivation par préfixe commun est la seule méthode généralisable. À ne pas confondre avec la table `doi_prefixes` (registrant nu → Registration Agency → publisher).

### Le croisement journal_id → doc_type

Les règles de correction s'appliquent **indépendamment, toutes à partir du brut** : aucune règle ne lit la valeur qu'une autre vient de produire. Aujourd'hui ce découpage est sans conséquence, car le seul champ à la fois corrigé et lu en prédicat est `doc_type`, et les croisements `doc_type → doc_type` ne se matérialisent pas dans le corpus.

Faire du `journal_id` un champ réellement corrigé change cela : plusieurs règles de `doc_type` se déclenchent en fonction du **type du journal rattaché** (`journal_type`, dérivé du journal_id). Rattacher The Conversation (dont le `journal_type` est `media`) devrait ensuite faire basculer ses publications de `preprint` vers `media` via la règle `JOURNAL_TYPE_MEDIA_TO_MEDIA` — un seul rattachement réparant deux défauts. Mais comme les corrections lisent le brut indépendamment, dans une même passe la règle de `doc_type` lirait le `journal_type` joint au **journal_id d'origine** (nul), pas au journal_id fraîchement posé : la reclassification n'aurait pas lieu dans la même passe. C'est le premier cas concret de dépendance inter-champ du moteur de correction.

### Nature de la correction

Le rapprochement par DOI n'est pas un prédicat sur une `source_publication` isolée : c'est une **recherche inverse** (« quel journal a un `doi_prefix` qui préfixe ce DOI »), donc une jointure contre la table journals. Il ne relève pas du mini-DSL des règles unaires (prédicats purs sur la vue d'une source, à cible **constante**), mais d'un traitement à jointure à cible **data-dépendante** — comparable aux corrections relationnelles par cluster de DOI, qui vivent déjà à part dans la phase.

## Décisions

1. **La correction vit dans `metadata_correction`, en sous-step `journal_by_doi`.** Correction d'un journal_id manquant, de même nature que celles déjà portées par la phase, qui dépend des données du journal comme les règles `JOURNAL_TYPE_*`. La normalisation ne convient pas (le `doi_prefix` est construit après elle) ; `publishers_journals` ne convient pas (elle n'écrit ni publications ni journal_id de source).

2. **Un sous-step à jointure, hors DSL unaire.** Le rapprochement se code comme un traitement à part (jointure `source_publications` × `journals` sur « DOI commence par doi_prefix »), à la manière du sous-step cluster, et non comme une entrée du dictionnaire de règles : le DSL unaire ne porte que des cibles constantes, ici la cible est le journal résolu par recherche inverse. Il ne se fond pas non plus dans le sous-step cluster, qui groupe les SP **entre elles** par DOI partagé alors que `journal_by_doi` **joint chaque SP à un journal**.

3. **`journal_by_doi` possède `journal_id`, qui sort de l'unaire.** Le sous-step unaire revendique `journal_id` (dans `_UNARY_FIELDS`) mais ne le corrige jamais : `effective_metadata` n'appelle pas `_correct_field` dessus, et aucune règle ne le produit — tuyauterie morte (`CorrectedFields.journal_id`, `_AppliesCorrection.journal_id`, branche `journal_id` de `compute_update`, écriture de la colonne dans `persist_corrections`). Laissée en place, elle clobberait le rattachement : l'unaire reconstruit `journal_id` depuis le brut, strippe `raw_metadata.journal_id` et réécrit la colonne. La correction propre transfère la propriété de `journal_id` à `journal_by_doi` (et retire le mort de l'unaire), exactement comme `doi` appartient au sous-step cluster.

4. **Ne corriger que les journal_id manquants, et sans ambiguïté.** N'agir que lorsque la `source_publication` n'a pas de journal_id, et seulement quand le préfixe désigne un **unique** journal (le plus spécifique en cas de préfixes emboîtés). Ne pas écraser un journal résolu par la normalisation.

5. **Tracer comme toute correction.** Stasher le brut écrasé et la provenance dans `raw_metadata.journal_id.corrected_by`, sous un identifiant de règle dédié, pour la réversibilité, l'audit et l'auto-cicatrisation (re-dérivation du brut à chaque run, restauration du NULL si le préfixe ne matche plus).

6. **Ordre des sous-steps : `journal_by_doi` → unaire → cluster ; convergence en un seul run.** `journal_by_doi` commit le `journal_id` ; l'unaire re-fetch frais, joint `journal_type` depuis la colonne vivante, et `JOURNAL_TYPE_MEDIA_TO_MEDIA` reclasse `doc_type` (The Conversation : `preprint` → `media`) le même run ; le cluster suit, lisant le `doc_type` canonique. Le croisement inter-champ se résout par l'**ordre**, pas par un feed-forward dans la fonction pure : le canal de feed est la colonne committée qu'un sous-step aval re-lit. `effective_metadata` reste sans feed-forward interne.

### Vérification : aucun conflit de règle sur un brut censé être corrigé

Croisement, pour chaque champ corrigible, des règles qui le **lisent** en prédicat et du sous-step qui le **corrige**, selon l'ordre :

- **`journal_id` / `journal_type`** (corrigé par `journal_by_doi`, en premier) : lu par l'unaire (`journal_id_present`, `journal_type`) — qui voit donc la valeur corrigée.
- **`doc_type`** (corrigé par l'unaire) : lu par l'unaire (cascade first-match, whitelists quasi-disjointes, design acté) et par le cluster (canonique, après l'unaire).
- **`doi`** (corrigé par le cluster, en dernier) : lu en brut par l'unaire (`doi_contains`, `doi_prefix_not_in`) et par `journal_by_doi` — mais le brut **est** le signal voulu (marqueur figshare, préfixe registre-thèse, namespace journal) ; la substitution cluster est une dédup en aval, orthogonale.
- **`oa_status`** : lecteur unique = correcteur unique (embargo).
- **`external_ids`** : aucun lecteur.

Aucune règle ne consomme un brut qu'une autre est censée avoir corrigé avant elle. Le feed-forward explicite est donc enterré. Cas-limite bénin connu : un `book_chapter` orphelin portant le DOI de son ouvrage peut se voir rattacher le journal de l'ouvrage (`journal_by_doi` tourne avant le nullage cluster du DOI) — rare, hors cible, et défendable.

## Phasage

### Phase 0 — Cadrer la dérivation de `journals.doi_prefix`

- [x] Point d'écriture localisé : oneshot `seed_journals_doi_prefix.py` (LCP des DOI rattachés), plus édition manuelle ; aucune phase pipeline. Cf. Contexte.
- [x] Robustesse cadrée : instantané figé, jamais rafraîchi ; seul risque la sous-couverture, pas le préfixe trompeur (la LCP sur un sous-ensemble est toujours plus spécifique, donc sous-rattache au pire). Seuil de publications abaissé de 10 à 5 (couverture 291 → 1035 journaux) : en deçà, les préfixes deviennent trop spécifiques par accident d'échantillon pour un gain de rattachement négligeable (journaux à très faible volume). Seed rejoué sur le stock après l'abaissement.
- [x] Périmètre retenu : uniquement les préfixes désignant un seul journal — la cible étant des publications sans aucun signal de départage, un préfixe partagé serait indécidable pour elles.

### Phase 1 — Sortir `journal_id` de l'unaire

- [x] Tuyauterie morte `journal_id` retirée de l'unaire : `_UNARY_FIELDS`, colonne de `persist_corrections`, `CorrectionUpdate`, `CorrectedFields.journal_id`, `_AppliesCorrection.journal_id`, branche `compute_update`.
- [x] Non-régression vérifiée (tests unaires + intégration `metadata_correction` verts ; comportement inchangé, l'unaire ne touchait déjà plus `journal_id`).

### Phase 2 — Sous-step `journal_by_doi`

- [x] Fonction domaine pure `resolve_journal_by_doi` : longest-unique-prefix match d'un DOI contre la carte `doi_prefix` → `journal_id` (chargée en mémoire), abstention si non unique.
- [x] Orchestrateur `journal_by_doi.py` : fetch des orphelines à DOI (+ déjà rattachées, pour l'auto-cicatrisation), décision domaine, stash du brut et de la provenance dans `raw_metadata.journal_id`, persistance dédiée (possède `journal_id` + `raw_metadata.journal_id`, marque `keys_dirty` pour propager au canonique via la réconciliation).
- [x] Ordre `journal_by_doi` → unaire → cluster câblé dans `phase_metadata_correction`.
- [x] Tests : déductible, abstention sur partagé, plus-spécifique sur emboîtés, non-écrasement, idempotence et auto-cicatrisation (unitaires), reclassification `doc_type` en un run et auto-cicatrisation (intégration).

### Phase 3 — Application au stock

- [x] Correction appliquée par un passage de `metadata_correction` puis `publications` (le sous-step scanne toutes les orphelines à DOI, pas de re-dirty préalable).
- [x] Effet mesuré : **7 145 source_publications rattachées** (5 272 in_perimeter), **+1 541 SP** basculées en `doc_type=media` et **+274 publications canoniques** retypées `media`. Idempotence confirmée en réel (re-simulation : 0 rattachable restant). Résiduel : ~24 000 orphelines in_perimeter sans préfixe-journal correspondant, hors de portée par construction.

## Items TODO liés (à traiter en passant ou recaser dans un autre chantier)
* [ ] faux preprints: retyper en fonction du DOI (theConversation => media)
* [ ] détection d'incohérences `doi_prefix`/`publisher_id`/`journal_id`: auditer d'abord, classifier les cas de divergence selon leur cause
* [ ] créer circuit pour correction automatisée du `journal_type` (titre terminé par ` eBooks` => plateforme d'ebooks)
* [ ] recensions: "Comptes rendus :", "Compte rendu :"; type = article + titre contient "(dir.)"
* [ ] typage data_paper automatisé par journal (ex. *Scientific Data*; créer un journal_type dédié?); chercher aussi "dataset" dans les titres
* [ ] règle à créer: si DOI de forme ISBN + _n => conference_paper ou chapitre / si forme ISBN: proceedings ou book (trancher selon type du "journal")
* [ ] 107270 et 869915 Computing Pivot-Minors: un article faussement typé preprint par openalex; + question des arxiv_id (déduire le DOI et vice-versa)
* [ ] noms de containers OpenAlex aberrants ("SPIRE - Sciences Po Institutional REpository") => faire quelque chose; de manière générale il faut interroger la pertinence du champ container relativement au journal_id

## Questions ouvertes

- **Rafraîchissement du `doi_prefix`** : la valeur est un instantané figé (291 → 1035 journaux après le re-seed à seuil 5). Laisser en oneshot rejoué à la demande, ou promouvoir en étape pipeline idempotente ? Décision d'architecture distincte de ce chantier, non bloquante : `journal_by_doi` tourne sur le stock figé.
- **Périmètre des publications** : restreindre au périmètre, ou rattacher aussi hors périmètre (même logique, mais volume et utilité différents) ?
- **Typage de Preprints.org** : la plateforme est typée `journal` plutôt que `preprint_server` ; ses publications restent `preprint`, donc neutre ici, mais c'est un défaut de typage à corriger à part. Dans ce chantier ou ailleurs ?
- **Place du sous-step** : adjoindre au traitement relationnel existant (corrections par cluster de DOI) ou en faire un sous-step de résolution de journal distinct ?
