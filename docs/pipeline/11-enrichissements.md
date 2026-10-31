# Enrichissements

*À jour le 2026-10-26.*

## Relations entre publications (`relations`)

Peuple la table `publication_relations`. Une relation rattache deux publications apparentées : preprint et version publiée, article et supplément de données, chapitre et ouvrage, article et erratum, data paper et jeu de données…

La table est reconstruite à chaque exécution, à partir de signaux indépendants appliqués dans l'ordre ci-dessous.

**Relations déclarées par les sources.** DataCite et Crossref publient des relations typées entre DOI, traduites vers un vocabulaire unifié.

**Clés de confirmation partagées.** Deux publications aux DOI distincts qui partagent un identifiant (HAL, arXiv, PMID, NNT) sont apparentées, par exemple un preprint et sa version publiée. La relation se déduit de leurs types de document.

**Titre.** Un erratum est relié à l'article cité dans son titre, un preprint à sa version publiée de même titre. Ce titre doit désigner une seule publication.

## Sujets (`subjects`)

**Ingestion.**
Les sujets déclarés par les sources sur chaque `source_record` sont rattachés à la publication, dans les tables `subjects` et `publication_subjects`. Le lien garde la source qui a fourni le sujet. Seuls les termes d'un vocabulaire contrôlé entrent dans `subjects`. Les mots-clés libres restent dans les enregistrements sources.

Les publications aux sources modifiées depuis la dernière ingestion de leurs sujets sont retraitées : leurs liens sont reconstruits, sauf ceux marqués `rejected`. L'option `--rebuild-subjects` retraite toutes les publications.

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

Lit chez doi.org l'URL de résolution de chaque DOI, interroge [Unpaywall](../glossaire.md#unpaywall) par DOI, et conserve les deux réponses dans `sources.dois`. Une URL de résolution donne une copie ouverte de la publication dans deux cas : elle mène à une plateforme en accès libre intégral (arXiv, bioRxiv, medRxiv, PubMed Central), ou son chemin finit par `.pdf`. Le statut d'une publication se déduit de ses copies, du modèle de sa revue et de ce verdict (`domain/publications/open_access.py`), ici et à chaque recalcul de la publication :

1. Copie ouverte chez l'éditeur, sous licence ouverte : `hybrid` dans une revue sur abonnement ou de modèle inconnu, `gold` dans une revue entièrement en open access ou hors revue, `diamond` dans une revue diamant.
2. Sinon, copie ouverte dans une archive ou sur un serveur de preprints : `green`.
3. Sinon, copie ouverte chez l'éditeur sans licence ouverte : `bronze`.
4. Sinon : `embargoed` avec un enregistrement source sous embargo actif (`embargoes`), `closed` avec une copie déclarée fermée, un verdict, ou pour une thèse en cours ou réservée à l'intranet de son établissement, `unknown` sans aucune information.

Le verdict d'Unpaywall relève ces accès, sans les abaisser : `gold`, `hybrid` ou `diamond` vaut une copie ouverte chez l'éditeur sous licence, `bronze` sans licence, `green` une copie d'archive ouverte.

Incrémentale : chaque service reçoit seulement les DOI sans réponse de sa part, ou à réponse plus ancienne que son délai, dans la limite de son plafond par exécution. Ces réglages se modifient dans `admin/config`.

| Service | Plafond | Délai | DOI écartés |
|---|---|---|---|
| doi.org | `doi_resolution_max_per_run`, 10 000 | `doi_resolution_recheck_after_days`, 180 jours | aucun |
| Unpaywall | `unpaywall_max_per_run`, 10 000 | `unpaywall_recheck_after_days`, 15 jours | DOI DataCite, absents d'Unpaywall |

Un DOI inconnu du service reçoit une réponse nulle. Quand le service est indisponible, le DOI est repris au run suivant.
