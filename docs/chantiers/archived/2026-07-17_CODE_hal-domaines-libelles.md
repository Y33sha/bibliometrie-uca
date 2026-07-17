# Domaines HAL : libellés depuis la source, suppression de la table

## Contexte

La phase `subjects` récupère les domaines HAL d'une publication depuis le champ Solr `domain_s` — une liste de **codes CCSD** (`0.chim`, `1.chim.anal`…) que HAL énumère niveau par niveau, avec doublons. L'extracteur `hal_labels` (`application/pipeline/subjects/extractors.py`) strippe le préfixe `<niveau>.`, déduplique, puis traduit chaque code en libellé via `hal_domain_label` (`domain/sources/hal_domains.py`) : une table en dur d'environ 400 entrées `code → libellé feuille`, régénérée depuis l'API référentiel CCSD par `interfaces/cli/dev/refresh_hal_domain_labels.py`.

HAL est ainsi la **seule source à passer par une table de correspondance** : OpenAlex, WoS, ScanR et theses.fr exposent directement leurs sujets en clair. L'asymétrie est évitable — HAL expose le libellé par document dans le champ `fr_domainAllCodeLabel_fs`, sous la forme `<code>_FacetSep_<niveau 0>/<niveau 1>/…/<feuille>` :

```
domain_s:                 ["0.sdv", "1.sdv.bbm", "2.sdv.bbm.bm"]
fr_domainAllCodeLabel_fs: ["sdv.bbm.bm_FacetSep_Sciences du Vivant [q-bio]/Biochimie, Biologie Moléculaire/Biologie moléculaire"]
```

Le chemin porte tous les niveaux. En le découpant sur `/`, on retrouve la même hiérarchie de libellés que la table produit, sans table.

Deux défauts du dispositif actuel, relevés au passage :

- **Le générateur est cassé.** Sa cible `DEST` pointe vers `domain/hal_domains.py`, chemin obsolète depuis le déplacement du fichier sous `domain/sources/` : une régénération écrirait au mauvais endroit. Et son gabarit `HEADER`/`FOOTER` duplique la docstring du module et `hal_domain_label`. La table ne peut plus être régénérée proprement.
- **Les libellés « Autre » polluent.** Plusieurs feuilles portent le libellé générique « Autre »/« Autres » (`chim.othe`, `info.info-oh`, `spi.other`, `sdv.ot`, `stat.ot`…). Elles se fondent en un unique concept « Autre » qui agrège des feuilles sans rapport. Un document `chim.othe` produit `["Chimie", "Autre"]` : le parent porte déjà le signal, « Autre » n'ajoute que du bruit.

## Décisions

1. **L'extraction HAL passe de `domain_s` à `fr_domainAllCodeLabel_fs`.** Le libellé vient de la source, comme pour toutes les autres sources. `topics.hal_domains` stocke les chaînes `<code>_FacetSep_<chemin>` brutes ; la découpe en libellés est une règle pure appelée par l'extracteur.
2. **Tous les niveaux hiérarchiques sont conservés, à plat.** Le chemin est découpé sur `/`, chaque segment donne un libellé. La profondeur est lue du code (préfixe avant `_FacetSep_`), ce qui borne le découpage et préserve les `/` internes au libellé de feuille. Même traitement que les 4 niveaux OpenAlex à plat.
3. **Les libellés génériques « Autre »/« Autres » sont écartés** à l'extraction. Sans risque de déclassement : le parent est toujours présent dans le chemin. L'exclusion suit le retrait des annotations, certaines feuilles portant `Autre [cs.OH]` ou `Autres [stat.ML]`.
4. **La table et son générateur disparaissent.** `domain/sources/hal_domains.py` et `interfaces/cli/dev/refresh_hal_domain_labels.py` sont supprimés, avec leurs tests. La découpe d'un chemin de domaine HAL devient une règle pure dans `domain/sources/hal.py`.

### Ce que dit le référentiel

Relevé par facette sur `fr_domainAllCodeLabel_fs` (707 valeurs distinctes), qui fonde la règle de découpe :

- **671 entrées bien formées**, dont le code répond à `[a-z0-9]+([-.][a-z0-9]+)*`. Les 36 autres portent un chemin de libellés en guise de code (`Informatique [cs]/Biotechnologie_FacetSep_domain_Informatique [cs]/Biotechnologie`), certaines franchement corrompues ; elles n'apparaissent que sur une centaine de documents et ne donnent aucun libellé.
- **Quatre domaines portent un `/` dans leur libellé de feuille**, ce qui interdit un découpage libre : `chim.theo` (« Chimie théorique et/ou physique »), `spi.opti` (« Optique / photonique »), `spi.auto` (« Automatique / Robotique ») et `spi.nano` (« Micro et nanotechnologies/Microélectronique »). Chacun pèse 20 000 à 32 000 documents. Le dernier n'est pas une tournure de langue mais deux niveaux tassés dans un code de profondeur 2 : aucune liste d'expressions ne le couvrirait, là où la profondeur annoncée par le code le borne.
- **Les seuls libellés génériques sont « Autre » et « Autres »**, annotations retirées.
- Partout ailleurs, le nombre de segments du chemin égale la profondeur du code.

## Phasage

### Phase 1 — Extraction et règle de découpe

- [x] `domain/sources/hal.py` : fonction pure `hal_domain_labels(facet_entry)` → liste des libellés de niveaux (découpe `_FacetSep_` puis `/` bornée par la profondeur du code, retrait des annotations `[…]`, exclusion « Autre »/« Autres »). Constantes `_DOMAIN_CODE`, `_DOMAIN_ANNOTATION`, `_GENERIC_DOMAIN_LABELS`.
- [x] `infrastructure/sources/hal/fields.py` : remplacer `domain_s` par `fr_domainAllCodeLabel_fs` dans `HAL_FIELDS`.
- [x] `application/pipeline/normalize/normalize_hal.py` : lire `fr_domainAllCodeLabel_fs`, le stocker tel quel dans `topics.hal_domains`.
- [x] `application/pipeline/subjects/extractors.py` : `hal_labels` déduplique les entrées puis délègue à `hal_domain_labels` ; retrait de `_strip_level_prefix` et de l'import `hal_domain_label`.

### Phase 2 — Suppressions

- [x] Supprimer `domain/sources/hal_domains.py`.
- [x] Supprimer `interfaces/cli/dev/refresh_hal_domain_labels.py`.
- [x] Supprimer `tests/unit/domain/test_hal_domains.py` ; `hal_domain_labels` couvert par `tests/unit/domain/sources/test_hal_domain_labels.py`, dont les entrées sont des valeurs réelles du référentiel.

### Phase 3 — Tests et documentation

- [x] `tests/integration/pipeline/test_subjects_ingest.py` : fixtures au format `fr_domainAllCodeLabel_fs`, avec un cas multi-niveaux et un cas « Autre » exclu.
- [x] `tests/unit/application/pipeline/normalize/test_normalize_hal.py` : entrée `fr_domainAllCodeLabel_fs`, assertion `topics` mise à jour.
- [x] `tests/integration/pipeline/test_dedup_publications.py` : fixtures `hal_domains` au format source.
- [x] `docs/sources/02-hal.md` : champ domaines recalé. `docs/pipeline` et `docs/donnees` ne mentionnaient pas la table.

### Phase 4 — Reprise du stock (production)

Le champ `fr_domainAllCodeLabel_fs` est absent des `raw_data` déjà en base : les documents HAL extraits avant ce chantier n'ont pas de domaines exploitables tant que le stock n'est pas repris.

- [ ] Re-fetch HAL → re-normalize → re-run `subjects`. Exécution laissée à l'administratrice de la base.

## Questions ouvertes

- **Interaction avec la qualité des sujets** : le chantier `METIER_sujets-qualite` se sert des libellés `hal_domain` comme arbitres du nettoyage OpenAlex. Le changement les enrichit (parents remontés) et les assainit (« Autre » retiré) sans casser l'usage — à garder en tête au calibrage des arbitres.
- **Limite de la règle de découpe** : la profondeur du code ne protège que le **dernier** segment. Un `/` dans un libellé intermédiaire scinderait à tort. Aucune des 671 entrées bien formées n'est dans ce cas, mais c'est une propriété des données du référentiel, pas une garantie de son schéma.
