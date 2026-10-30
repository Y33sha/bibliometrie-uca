# Enrichissements

*À jour le 2026-10-26.*

## Relations entre publications (`relations`)

Peuple la table `publication_relations`. Une relation rattache deux publications apparentées : preprint et version publiée, article et supplément de données, chapitre et ouvrage, article et erratum, data paper et jeu de données…

La table est reconstruite à chaque exécution, à partir de signaux indépendants appliqués dans l'ordre ci-dessous.

**Relations déclarées par les sources.** DataCite et Crossref publient des relations typées entre DOI, que la phase traduit vers un vocabulaire unifié.

**Clés de confirmation partagées.** Deux publications aux DOI distincts qui partagent un identifiant (HAL, arXiv, PMID, NNT) sont apparentées, par exemple un preprint et sa version publiée. La relation se déduit de leurs types de document.

**Titre.** Un erratum est relié à l'article cité dans son titre, un preprint à sa version publiée de même titre. Ce titre doit désigner une seule publication.

## Sujets (`subjects`)

**Ingestion.**
Les sujets que les sources déclarent sur chaque `source_record` sont rattachés à la publication, dans les tables `subjects` et `publication_subjects`. Le lien garde la source qui a fourni le sujet. Seuls les termes d'un vocabulaire contrôlé entrent dans `subjects`. Les mots-clés libres restent dans les enregistrements sources.

Les publications dont les sources ont changé depuis la dernière ingestion de leurs sujets sont retraitées : leurs liens sont reconstruits, sauf ceux marqués `rejected`. L'option `--rebuild-subjects` retraite toutes les publications.

Les sujets sans lien sont supprimés.

**Co-occurrences.** Recalcule depuis `publication_subjects` :

- `subjects.usage_count` — nombre de publications distinctes par sujet ;
- `subject_cooccurrences` — paires de sujets présents ensemble sur au moins deux publications, avec leur effectif.

## Pays des adresses (`countries`)

Associe des pays aux adresses, aux contributions sources et aux publications, pour l'analyse des collaborations internationales.

- **Pays trouvés.** Chaque moyen de détection propose des pays pour une adresse (`address_country_candidates`) : pays donnés par OpenAlex et ScanR, nom de pays en fin d'adresse, noms d'institutions et de villes (`place_name_forms`), saisie manuelle.
- **Pays retenus.** Une fonction de préséance du domaine (`domain/country_detection.py`) compose `addresses.countries` à partir des pays trouvés.
- **Report.** Le pays d'une contribution source réunit les pays retenus de ses adresses, ceux de ses organisations ROR sans adresse et ceux de ses structures HAL. `source_records.countries` réunit les pays de ses contributions sources, `publications.countries` ceux de ses enregistrements sources.

Seules les adresses et les contributions sources marquées sont retraitées.

## Statut open access (`oa_status`)

Interroge [Unpaywall](../glossaire.md#unpaywall) par DOI et conserve son verdict dans `sources.unpaywall`. Le statut d'une publication se calcule à partir de ses sources et de ce verdict, ici et à chaque recalcul de la publication.

Incrémentale : chaque exécution est plafonnée (`unpaywall_max_per_run`, 10 000 DOI par défaut) et vérifie seulement les DOI sans verdict, ou dont le verdict date de plus de `unpaywall_recheck_after_days` (15 jours par défaut, réglable dans `admin/config`). Les DOI DataCite, absents d'Unpaywall, sont écartés. Quand Unpaywall est indisponible, le DOI est repris au run suivant.
