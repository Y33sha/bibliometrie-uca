# Chantier — Qualité des contributions

## Contexte

Une contribution réunit les contributions sources d'un même auteur dans une publication, alignées par la phase `author_grouping`, et désigne sa personne, décidée par la phase `persons`. Les deux mécanismes sont en place. Restent des contrôles de qualité des données et des outils de correction, sans ordre imposé entre eux.

Un jeu d'évaluation tiré des verdicts humains existe depuis le 2026-10-19 (`build_evaluation_set.py`) : 2 373 couples (contribution source, personne) justes, 523 couples (enregistrement source, personne) faux, 23 paires de personnes distinctes. Le schéma `snapshot_20261024_gel` de la base locale garde l'état des personnes et de leurs rattachements avant la bascule sur les contributions.

## Décisions

- Les mesures et les relectures se font sur la base de production. La base locale sert à écrire les règles.

## Phasage

### Phase 1 — Identifiants

- [ ] Neutralisation par partage d'un auteur listé deux fois dans un enregistrement source, sous deux graphies : ses deux contributions sources perdent son identifiant (Polichtchouk et Polishchuk, même ORCID). Mesurer le cas, et marquer plutôt le doublon d'auteur. Au 2026-10-24, 42 130 contributions sources ont une neutralisation par partage.
- [ ] Neutralisation par nom contraire au consensus : effet sur chacun de ses usages (rattachement, arbitrage des identifiants, alignement, attribution des identifiants), face au contrôle de compatibilité des noms que fait déjà le rattachement par identifiant. Au 2026-10-24, 19 070 contributions sources ont une telle neutralisation.
- [ ] Identifiants attribués à tort. 226 personnes ont plusieurs ORCID non rejetés au 2026-10-24, dont Miriam Calvo Gomez, qui a l'ORCID de Marta Calvi sur 192 publications. Un ORCID en attente rattache parfois la contribution d'une autre personne que son titulaire (21 cas dans la relecture du 2026-10-19).
- [ ] Contrôle des identifiants par le nom que déclarent les API d'IdRef et d'ORCID.
- [ ] ORCID d'OpenAlex sans DOI : sur des enregistrements sources OpenAlex sans DOI, `raw_orcid` donne deux fois un ORCID faux (Yannick Chevalier, Bruno Pereira). Provenance de `raw_orcid` hors Crossref à vérifier.

### Phase 2 — Affiliations

- [ ] Affiliation comme critère de départage des homonymes et des identifiants contradictoires : les structures de la contribution confrontées à celles des autres publications de chaque candidat. Mesure du 2026-10-19 (`measure_affiliation.sql`), sur 2 176 contributions au nom ambigu. Une clé spécifique est un laboratoire ou une équipe du référentiel, ou un laboratoire, une équipe ou un département HAL.
  - Avec toutes les clés, établissements et ROR compris, plusieurs candidats concordent dans 1 725 cas. Avec les clés spécifiques, un seul candidat concorde dans 1 631 cas, plusieurs dans 392.
  - Sur ces 1 631 cas, le candidat désigné est la personne rattachée dans 1 151, une autre personne dans 7. 463 contributions sont sans personne.
  - Échantillon de 97 cas à relire (`build_affiliation_review.py`).
- [ ] Désaccords d'affiliation entre les contributions sources d'une même contribution. Les affiliations conflictuelles relèvent du chantier [vérification des affiliations](DATA_verification-affiliations.md).

### Phase 3 — Alignement des listes d'auteurs

- [ ] Revue des appariements du modèle : trois classes selon le score et la marge (lien, non-lien, lien possible). Une file de revue de l'administration confirme ou infirme les liens possibles.
- [ ] Diagnostic de chaque liste d'auteurs avant l'alignement. Il nomme le défaut, écarte les contributions sources concernées et reste stocké pour la relecture et la mesure. Les signaux viennent de l'enregistrement source seul ; la comparaison avec les autres enregistrements sources de la publication sert de confirmation.
- [ ] Fusions erronées probables dans l'onglet Fusions suspectes. L'onglet retient une publication dont moins de la moitié des contributions sources ont un correspondant : un enregistrement source étranger minoritaire lui échappe (12 des 20 fusions erronées probables de l'échantillon du 2026-10-18). Critère à ajouter : un enregistrement source dont presque aucune contribution source n'a de correspondant.

### Phase 4 — Rattachements et corrections

- [ ] Précision et rappel de la résolution par contribution sur le jeu d'évaluation.
- [ ] Relecture des personnes supprimées par la purge, et des contributions laissées sans personne parce que leur personne est déjà dans la publication, au regard du gel du 2026-10-24.
- [ ] Repérage des erreurs des sources révélées par une contribution : des contributions sources d'une même contribution qui désigneraient seules des personnes différentes signalent une erreur de groupement, de nom, d'identifiant ou d'affiliation. Outil de l'administration, comme pour les fusions suspectes de publications.
- [ ] Scission d'une contribution par une décision humaine, quand deux de ses contributions sources désignent deux personnes.

## Questions ouvertes

- Périmètre des publications : il réunit les indices des seules contributions rattachées à une personne non exclue. Une erreur d'affiliation relève de la contribution source, pas de la personne.
- Ancrage des épinglages : `confirmed_source_contributions` vise la contribution source, en `ON DELETE CASCADE`. La renormalisation supprime puis réinsère une contribution source dont les identifiants changent, et l'épinglage disparaît. Ancrer sur l'enregistrement source et la position, ou sur l'enregistrement source et le nom ?
- Recalcul immédiat des contributions invalidées par une décision de l'administration, exposé par le pipeline (`pipeline/public.py`) sur un index réduit aux valeurs de leurs contributions sources.
- Deux idées de ReCiter : enregistrer ce qui a concordé et pas seulement la règle ; réutiliser les confirmations et les rejets d'une personne comme indices pour ses autres contributions.
