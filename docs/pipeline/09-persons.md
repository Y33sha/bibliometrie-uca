# Résolution et création des personnes

*À jour le 2026-10-26.*

La phase `persons` rattache chaque [contribution](../donnees/04-contributions.md) à une [personne](../donnees/05-persons.md). Elle décide la personne à partir de toutes les contributions sources alignées dans la contribution.

Une contribution du périmètre au nom inconnu fonde une personne, d'après le nom d'une de ses contributions sources. Le nom vient de préférence d'une source qui sépare nom et prénom, puis d'un prénom complet. L'ordre des sources départage ensuite : theses.fr, Crossref, DataCite, OpenAlex, ScanR, HAL, WoS. Les contributions au même nom, dans d'autres publications, la rejoignent dans le même passage.

## Rattacher une contribution à une personne

Les critères sont interrogés dans l'ordre, du plus fiable au moins fiable. Le premier qui désigne une personne l'emporte. Deux personnes désignées par le même critère laissent la contribution sans personne.

1. **Épinglage** : une contribution source alignée est épinglée à une personne par l'administration.

2. **ORCID déposé par l'auteur** : ORCID présent dans les métadonnées Crossref ou DataCite de la publication, dans le `raw_orcid` d'OpenAlex, ou dans le TEI HAL (`label_xml`). Les ORCID que la source a devinés sont écartés : `author.orcid` dans OpenAlex, distingué de `raw_orcid` ; dans WoS, où les deux sont indiscernables, `PreferredORCID` est ignoré en entier.

3. **Compte HAL** : `hal_person_id`, attaché à la contribution source dans le TEI. Vient après l'ORCID déposé : le rattachement de la contribution source au compte peut être faux, du fait de l'identification automatisée au dépôt et des homonymies sur les publications à nombreux auteurs.

4. **Identifiant IdRef** : PPN SUDOC (HAL TEI, ScanR, theses.fr), référentiel personnes de l'ESR.

5. **Forme de nom** : le nom normalisé d'une contribution source désigne une seule personne dans `person_name_forms`, ou, à défaut, une seule personne aux initiales compatibles (« Abdellah Tnourji » rejoint « Tnourji A. »). Ce référentiel de formes est régénéré à chaque exécution, à partir du nom de chaque personne — « prénom nom » et « initiales nom » — et du nom des contributions sources de ses contributions. Une contribution source est cherchée sous la forme « prénom nom », puis « nom prénom », ce qui rattrape un nom et un prénom inversés par la source. Un nom qui désigne plusieurs personnes laisse la contribution sans personne, pour traitement manuel via `admin/orphan-contributions`.

Dans une publication, une personne revient à une seule contribution : la mieux appuyée (épinglage, puis identifiant, puis nom).

> **Corroboration par le nom.** Un rattachement par identifiant (ORCID, `hal_person_id`, IdRef) n'est retenu que si le nom de la contribution source qui le contient est compatible avec celui du titulaire de la valeur : un identifiant recopié sur le mauvais co-auteur est refusé.

> **Garde de rejet.** À chaque critère, les personnes rejetées manuellement pour la publication (une publication est rejetée pour une personne dès qu'un de ses enregistrements sources l'est, `rejected_contributions`) sont **éliminées des candidats** : un rattachement ne peut pas recréer une paire rejetée. L'élimination peut aussi **désambiguïser** une recherche par nom : si une forme ambiguë correspond à 2 personnes dont l'une est rejetée pour cette publication, il ne reste qu'une candidate et le rattachement devient univoque.

### Contributions hors périmètre

Une contribution sans contribution source du périmètre est rattachée seulement par épinglage ou par identifiant. Le critère de nom vaut seulement pour les contributions du périmètre.

### Contributions sources non alignées

Les contributions sources collectives, les doublons d'auteur et les contributions sources des enregistrements sources écartés de l'alignement ne sont dans aucune contribution. Elles n'ont pas de personne et ne comptent pas dans l'arbitrage des identifiants.

## Rattachements conservés d'un run à l'autre

La phase décide les contributions sans personne. Une contribution rattachée garde sa personne d'un run à l'autre. Elle entre dans une file de redécision dans quatre cas :

- ses contributions sources alignées changent (phase `author_grouping`) ;
- l'arbitrage des identifiants neutralise l'identifiant qui l'a rattachée, ou le transfère à une autre personne ;
- l'administration rejette l'identifiant ou la forme de nom qui l'a rattachée ;
- la forme de nom qui fonde un rattachement par nom désigne plusieurs personnes (purge).

La phase redécide les contributions de la file, sauf les contributions épinglées. Une contribution qui désigne encore sa personne la garde, sans écriture. Une contribution qui en désigne une autre en change. Une contribution que rien ne soutient plus perd sa personne. Une contribution perd aussi sa personne quand celle-ci est supprimée.

## Données préservées

Les saisies manuelles (épinglage d'une contribution source, formes de nom confirmées ou rejetées, personnes déclarées distinctes) et les données importées (fiches du référentiel RH) sont des entrées fixes, jamais réinitialisées.

Une personne sans contribution du périmètre est supprimée, sauf si elle est présente dans le référentiel RH ou fait l'objet d'une décision humaine. Ses contributions perdent leur personne.
