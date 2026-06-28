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

L'origine exacte de la valeur de `journals.doi_prefix` n'est pas tracée dans ce chantier (point d'écriture non localisé) ; elle paraît dérivée des DOI des publications déjà rattachées au journal, ce qui fonderait la déduction (les publications non rattachées partagent le namespace des rattachées). À objectiver.

### Le croisement journal_id → doc_type

Les règles de correction s'appliquent **indépendamment, toutes à partir du brut** : aucune règle ne lit la valeur qu'une autre vient de produire. Aujourd'hui ce découpage est sans conséquence, car le seul champ à la fois corrigé et lu en prédicat est `doc_type`, et les croisements `doc_type → doc_type` ne se matérialisent pas dans le corpus.

Faire du `journal_id` un champ réellement corrigé change cela : plusieurs règles de `doc_type` se déclenchent en fonction du **type du journal rattaché** (`journal_type`, dérivé du journal_id). Rattacher The Conversation (dont le `journal_type` est `media`) devrait ensuite faire basculer ses publications de `preprint` vers `media` via la règle `JOURNAL_TYPE_MEDIA_TO_MEDIA` — un seul rattachement réparant deux défauts. Mais comme les corrections lisent le brut indépendamment, dans une même passe la règle de `doc_type` lirait le `journal_type` joint au **journal_id d'origine** (nul), pas au journal_id fraîchement posé : la reclassification n'aurait pas lieu dans la même passe. C'est le premier cas concret de dépendance inter-champ du moteur de correction.

### Nature de la correction

Le rapprochement par préfixe n'est pas un prédicat sur une `source_publication` isolée : c'est une **recherche inverse** (« quel journal a un `doi_prefix` qui préfixe ce DOI »), donc une jointure contre la table journals. Il ne relève pas du mini-DSL des règles unaires (prédicats purs sur la vue d'une source), mais d'un traitement à jointure — comparable aux corrections relationnelles par cluster de DOI, qui vivent déjà à part dans la phase.

## Décisions

Ces orientations sont proposées et restent à confirmer ou amender ; seul le contexte ci-dessus est factuel.

1. **La correction vit dans `metadata_correction`.** C'est une correction d'un journal_id manquant, de même nature que les corrections déjà portées par la phase, qui dépend des données du journal comme les règles `JOURNAL_TYPE_*`, et dont la tuyauterie d'écriture du journal_id existe déjà. La normalisation ne convient pas (le `doi_prefix` est construit plus tard, après la normalisation) ; `publishers_journals` ne convient pas (elle n'écrit ni publications ni journal_id de source).

2. **Un sous-step à jointure, hors DSL unaire.** Le rapprochement par préfixe se code comme un traitement à part (jointure `source_publications` × `journals` sur « DOI commence par doi_prefix »), à la manière de la correction relationnelle existante, et non comme une entrée du dictionnaire de règles.

3. **Ne corriger que les journal_id manquants, et sans ambiguïté.** N'agir que lorsque la `source_publication` n'a pas de journal_id, et seulement quand le préfixe désigne un unique journal. Ne pas écraser un journal résolu par la normalisation.

4. **Tracer comme toute correction.** Stasher le brut écrasé et la provenance dans `raw_metadata.journal_id.corrected_by`, sous un identifiant de règle dédié, pour la réversibilité et l'audit.

5. **Traiter le croisement journal_id → doc_type par la convergence sur deux runs, en première intention.** Le journal_id corrigé à un run est relu au run suivant (la phase repart du brut, avec le journal_id désormais persisté et son `journal_type` joint), où la règle de doc_type se déclenche. Cela respecte le caractère auto-cicatrisant de la phase, sans introduire de feed-forward. Un ordonnancement intra-phase ou un feed-forward explicite ne sont à envisager que si la convergence différée se révèle gênante.

## Phasage

### Phase 0 — Cadrer la dérivation de `journals.doi_prefix`

- [ ] Localiser le point d'écriture de `journals.doi_prefix` et sa logique (dérivé des DOI des publications rattachées, ou d'une autre source).
- [ ] Évaluer la robustesse : comportement pour un journal à faible volume rattaché, mise à jour à mesure que des publications s'attachent, risque de préfixe trompeur.
- [ ] Statuer sur le périmètre de préfixes retenus (uniquement les préfixes à un seul journal, ou aussi les partagés avec une règle de départage).

### Phase 1 — Sous-step de rattachement par préfixe

- [ ] Implémenter le traitement à jointure : pour chaque `source_publication` à DOI sans journal_id, rattacher le journal dont le `doi_prefix` préfixe le DOI, si et seulement s'il est unique.
- [ ] Gérer le cas d'un préfixe qui en préfixe un autre (registrant nu vs namespace) par le rapprochement le plus spécifique.
- [ ] Stasher brut et provenance dans `raw_metadata.journal_id`.
- [ ] Couvrir par des tests (rattachement déductible, abstention sur préfixe partagé, non-écrasement d'un journal_id existant, idempotence).

### Phase 2 — Croisement journal_id → doc_type

- [ ] Vérifier que la convergence sur deux runs produit bien la reclassification attendue (The Conversation : `preprint` → `media`).
- [ ] Trancher si la convergence différée suffit, ou s'il faut ordonner les sous-steps de la phase, ou introduire un feed-forward.

### Phase 3 — Application au stock

- [ ] Appliquer la correction au stock existant par la re-passe la plus légère atteignant la phase `metadata_correction` (re-marquer les `source_publications` concernées et rejouer la phase), sans réimport.
- [ ] Mesurer l'effet : journal_id rattachés, publications reclassées, résiduel.

## Questions ouvertes

- **Dérivation de `doi_prefix`** : d'où vient la valeur, et tient-elle pour les journaux à faible volume ? C'est le socle de la fiabilité du rapprochement.
- **Préfixes partagés** : faut-il traiter les rares préfixes désignant plusieurs journaux, et selon quel signal de départage (ISSN, titre de conteneur de la source) ? Ou les laisser hors périmètre ?
- **Stratégie de chaînage** : convergence sur deux runs, ordonnancement intra-phase, ou feed-forward explicite ? Cette décision dépasse ce seul cas : c'est le premier croisement inter-champ du moteur de correction, et le choix fait ici sert de précédent. Vaut-il mieux un mécanisme général de chaînage, ou rester sur le cas par cas tant qu'un seul croisement existe ?
- **Périmètre des publications** : restreindre au périmètre, ou rattacher aussi hors périmètre (même logique, mais volume et utilité différents) ?
- **Typage de Preprints.org** : la plateforme est typée `journal` plutôt que `preprint_server` ; ses publications restent `preprint`, donc neutre ici, mais c'est un défaut de typage à corriger à part. Dans ce chantier ou ailleurs ?
- **Place du sous-step** : adjoindre au traitement relationnel existant (corrections par cluster de DOI) ou en faire un sous-step de résolution de journal distinct ?
