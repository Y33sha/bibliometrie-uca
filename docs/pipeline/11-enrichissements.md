# Enrichissements

*À jour le 2026-11-17.*

## Relations entre publications (`relations`)

Peuple la table `publication_relations`. Une relation rattache deux publications apparentées : preprint et version publiée, article et supplément de données, chapitre et ouvrage, data paper et jeu de données… Les errata et les avis de rétractation, hors des publications, sont désignés par leur DOI. La phase pose aussi l'indicateur « Rétracté » des publications.

La table est reconstruite à chaque exécution, à partir de signaux indépendants appliqués dans l'ordre ci-dessous.

**Relations déclarées par les sources.** DataCite et Crossref publient des relations typées entre DOI, traduites vers un vocabulaire unifié.

**Clés de confirmation partagées.** Deux publications aux DOI distincts qui partagent un identifiant (HAL, PMID, NNT, CDS) ou un DOI arXiv sont apparentées. La relation se déduit de leurs types de document.

**Titre.** Un erratum ou un avis est relié à l'article cité dans son titre, un preprint à sa version publiée de même titre. Ce titre doit désigner une seule publication.

## Sujets (`subjects`)

**Ingestion.**
La normalisation lie chaque enregistrement source aux sujets donnés par sa source (`source_record_subjects`). La phase lie la publication à ces sujets et à leurs ancêtres, dans `publication_subjects`. Le lien garde la source qui a fourni le sujet.

Les publications aux sources modifiées depuis la dernière ingestion de leurs sujets sont retraitées : leurs liens sont reconstruits, sauf ceux marqués `rejected`. L'option `--rebuild-subjects` retraite toutes les publications.

Les sujets liés à aucun enregistrement source ni à aucune publication sont supprimés, sauf les ancêtres d'un sujet lié.

**Co-occurrences.** Recalcule depuis `publication_subjects` :

- `subjects.usage_count` — nombre de publications distinctes par sujet ;
- `subject_labels` — sujets regroupés par libellé normalisé, tous vocabulaires confondus, avec leur nombre de publications ;
- `subject_cooccurrences` — paires de libellés normalisés présents ensemble sur au moins deux publications, avec leur effectif.
