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
2. **Tous les niveaux hiérarchiques sont conservés, à plat.** Le chemin est découpé sur `/`, chaque segment donne un libellé. La profondeur est lue du code (préfixe avant `_FacetSep_`), ce qui borne le découpage et préserve les `/` internes à un libellé (« Chimie théorique et/ou physique »). Même traitement que les 4 niveaux OpenAlex à plat.
3. **Les libellés génériques « Autre »/« Autres » sont écartés** à l'extraction. Sans risque de déclassement : le parent est toujours présent dans le chemin.
4. **La table et son générateur disparaissent.** `domain/sources/hal_domains.py` et `interfaces/cli/dev/refresh_hal_domain_labels.py` sont supprimés, avec leurs tests. La découpe d'un chemin de domaine HAL devient une règle pure dans `domain/sources/hal.py`.

## Phasage

### Phase 1 — Extraction et règle de découpe

- [ ] `domain/sources/hal.py` : fonction pure `hal_domain_labels(facet_entry)` → liste des libellés de niveaux (découpe `_FacetSep_` puis `/` bornée par la profondeur du code, retrait des annotations `[…]`, exclusion « Autre »/« Autres »). Constante `_GENERIC_DOMAIN_LABELS`.
- [ ] `infrastructure/sources/hal/fields.py` : remplacer `domain_s` par `fr_domainAllCodeLabel_fs` dans `HAL_FIELDS`.
- [ ] `application/pipeline/normalize/normalize_hal.py` : lire `fr_domainAllCodeLabel_fs`, le stocker tel quel dans `topics.hal_domains`.
- [ ] `application/pipeline/subjects/extractors.py` : `hal_labels` déduplique les entrées puis délègue à `hal_domain_labels` ; retrait de `_strip_level_prefix` (obsolète) et de l'import `hal_domain_label`.

### Phase 2 — Suppressions

- [ ] Supprimer `domain/sources/hal_domains.py`.
- [ ] Supprimer `interfaces/cli/dev/refresh_hal_domain_labels.py`.
- [ ] Supprimer `tests/unit/domain/test_hal_domains.py` ; couvrir `hal_domain_labels` par un test dédié (multi-niveaux, `/` interne à un libellé, exclusion « Autre », entrée mal formée).

### Phase 3 — Tests et documentation

- [ ] `tests/integration/pipeline/test_subjects_ingest.py` : fixtures `hal_domains` au format `fr_domainAllCodeLabel_fs` ; ajouter un cas multi-niveaux et un cas « Autre » exclu.
- [ ] `tests/unit/application/pipeline/normalize/test_normalize_hal.py` : entrée `fr_domainAllCodeLabel_fs`, assertion `topics` mise à jour.
- [ ] `tests/integration/pipeline/test_dedup_publications.py` : fixtures `hal_domains` au format libellé.
- [ ] `docs/sources/02-hal.md` : recaler le champ domaines ; balayer `docs/pipeline` et `docs/donnees` pour les mentions de la table.

### Phase 4 — Reprise du stock (production)

- [ ] Re-fetch HAL (le champ `fr_domainAllCodeLabel_fs` n'est pas dans les `raw_data` existantes) → re-normalize → re-run `subjects`.

## Questions ouvertes

- **Interaction avec la qualité des sujets** : le chantier `METIER_sujets-qualite` se sert des libellés `hal_domain` comme arbitres du nettoyage OpenAlex. Le changement les enrichit (parents remontés) et les assainit (« Autre » retiré) sans casser l'usage — à garder en tête au calibrage des arbitres.
