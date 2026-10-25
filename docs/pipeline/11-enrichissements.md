#  Enrichissements

*À jour le 2026-10-16.*

## Relations entre publications (`relations`)

Peuple la table `publication_relations`. Une relation rattache deux publications apparentées : preprint et version publiée, article et supplément de données, chapitre et ouvrage, article et erratum, data paper et jeu de données…

La table est reconstruite à chaque exécution, à partir de signaux indépendants appliqués dans l'ordre ci-dessous.

**Relations déclarées par les sources.** DataCite et Crossref publient des relations typées entre DOI, que la phase traduit vers un vocabulaire unifié.

**Clés de confirmation partagées.** Deux publications qui partagent un identifiant (HAL, arXiv, PMID, NNT) sans avoir fusionné, leurs DOI étant distincts, sont apparentées — typiquement un preprint et sa version publiée. On déduit la relation à partir des types de document.

**Rapprochement par titre.** Un erratum rejoint l'article dont il reprend le titre, un preprint sa version publiée au titre identique, à condition qu'une seule publication porte ce titre.

## Sujets (`subjects`)

**Étape 1 — Ingestion.**
Les sujets que les sources déclarent sur chaque `source_record` sont rattachés à la publication, dans les tables `subjects` et `publication_subjects`. Le lien garde la source qui a fourni le sujet. Seuls les concepts issus des ontologies des sources entrent dans `subjects` ; les mots-clés libres restent portés par les `source_records`.

Les publications traitées sont celles dont `publications.subjects_ingested_at` est vide : jamais ingérées, ou recalculées depuis leurs sources après la dernière ingestion de leurs sujets. L'ingestion pose cette date, y compris pour une publication sans sujet. Leurs liens existants sont supprimés — sauf ceux marqués `rejected` — puis reconstruits depuis les sources. L'option `--rebuild-subjects` vide cette date sur toutes les publications : la phase re-traite alors le stock entier.

Les sujets qu'aucun lien ne référence plus sont supprimés.

**Étape 2 — Co-occurrences.**
Recalcule depuis `publication_subjects` :
1. `subjects.usage_count` — nombre de publications distinctes par sujet.
2. `subject_cooccurrences` — paires de sujets co-présents sur une même publication, avec leur effectif. Seules les paires co-présentes sur au moins 2 publications sont conservées, pour borner la cardinalité.

Idempotent : le résultat ne dépend que de l'état courant de `publication_subjects`.

## Pays des adresses (`countries`)

Associe des pays aux adresses, aux contributions sources et aux publications, pour l'analyse des collaborations internationales.

- **Pays trouvés.** Chaque moyen de détection propose des pays pour une adresse (`address_country_candidates`) : pays donnés par OpenAlex et ScanR, nom de pays en fin d'adresse, noms d'institutions et de villes (`place_name_forms`), saisie manuelle. Le ROR d'une affiliation ne propose pas de pays pour son adresse : une adresse est partagée par toutes les signatures de même texte, et le ROR d'une seule signature y deviendrait le pays de toutes.
- **Pays retenus.** Une fonction de préséance du domaine (`domain/country_detection.py`) compose `addresses.countries` à partir des pays trouvés.
- **Report.** Le pays d'une contribution source réunit les pays retenus de ses adresses, ceux de ses organisations ROR sans adresse et ceux de ses structures HAL. `source_records.countries` réunit les pays de ses contributions sources, `publications.countries` ceux de ses enregistrements sources.

Seules les adresses et les contributions sources marquées sont retraitées.

Code : `pipeline/transformation/structures/countries/`.

## Statut open access (`oa_status`)

Interroge [Unpaywall](../glossaire.md#unpaywall) par DOI et conserve son verdict dans `sources.unpaywall`. Le statut d'une publication se calcule à partir de ses sources et de ce verdict, ici et à chaque recalcul de la publication.

Incrémentale : chaque exécution est plafonnée (`unpaywall_max_per_run`, 10 000 DOI par défaut) et vérifie seulement les DOI sans verdict, ou dont le verdict date de plus de `unpaywall_recheck_after_days` (15 jours par défaut, réglable dans `admin/config`). Les DOI DataCite, absents d'Unpaywall, sont écartés. Quand Unpaywall est indisponible, le DOI est repris au run suivant.

Code : `pipeline/transformation/publications/oa_status.py`.
