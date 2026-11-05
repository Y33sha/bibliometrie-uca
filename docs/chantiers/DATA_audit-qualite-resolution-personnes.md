# Chantier — Audit de la qualité de la résolution des personnes

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
- [ ] Fiabilité des IdRef et des ORCID de ScanR, confrontés aux autres sources de la même contribution. L'IdRef de ScanR sert au rattachement, son ORCID est exclu (`ORCID_MATCH_SOURCES`). La mesure dit aussi si ScanR reste utile comme source.

### Phase 2 — Affiliations

- [ ] Affiliation comme critère de départage des homonymes et des identifiants contradictoires : les structures de la contribution confrontées à celles des autres publications de chaque candidat. Mesure du 2026-10-19 (`measure_affiliation.sql`), sur 2 176 contributions au nom ambigu. Une clé spécifique est un laboratoire ou une équipe du référentiel, ou un laboratoire, une équipe ou un département HAL.
  - Avec toutes les clés, établissements et ROR compris, plusieurs candidats concordent dans 1 725 cas. Avec les clés spécifiques, un seul candidat concorde dans 1 631 cas, plusieurs dans 392.
  - Sur ces 1 631 cas, le candidat désigné est la personne rattachée dans 1 151, une autre personne dans 7. 463 contributions sont sans personne.
  - Échantillon de 97 cas à relire (`build_affiliation_review.py`).

### Phase 3 — Alignement des listes d'auteurs

- [ ] Diagnostic de chaque liste d'auteurs avant l'alignement. Il nomme le défaut, écarte les contributions sources concernées et reste stocké pour la relecture et la mesure. Les signaux viennent de l'enregistrement source seul ; la comparaison avec les autres enregistrements sources de la publication sert de confirmation.
- [ ] Fusions erronées probables dans l'onglet Fusions suspectes. L'onglet retient une publication dont moins de la moitié des contributions sources ont un correspondant : un enregistrement source étranger minoritaire lui échappe (12 des 20 fusions erronées probables de l'échantillon du 2026-10-18). Critère à ajouter : un enregistrement source dont presque aucune contribution source n'a de correspondant.

### Phase 4 — Rattachements et corrections

- [ ] Précision et rappel de la résolution par contribution sur le jeu d'évaluation.
- [ ] Relecture des personnes supprimées par la purge, et des contributions laissées sans personne parce que leur personne est déjà dans la publication, au regard du gel du 2026-10-24.
- [ ] Repérage des erreurs des sources révélées par une contribution : des contributions sources d'une même contribution qui désigneraient seules des personnes différentes signalent une erreur de groupement, de nom, d'identifiant ou d'affiliation. Outil de l'administration, comme pour les fusions suspectes de publications.
- [ ] Scission d'une contribution par une décision humaine, quand deux de ses contributions sources désignent deux personnes.
- [x] Option `--rebuild-persons` : redécision de toutes les contributions hors mode manuel, contre les personnes existantes, par lots de 4 000 publications. Simulation du 2026-11-05 sur 300 185 contributions : 294 155 gardent leur personne, 25 la perdent, 11 en gagnent une, une change de personne. 3282b4515
  - Suppression puis recréation des personnes sans fiche RH et sans décision humaine (`person_without_decision_sql`) : 16 447 personnes supprimées sur 18 869, 88 273 contributions hors périmètre sans personne. Ces contributions sont rattachées par un identifiant à verdict humain, supprimé avec la personne. Les verdicts humains sur les identifiants (1 965) et sur les formes de nom (1 765) sont absents de `person_without_decision_sql`.
  - Variante qui conserve toutes les décisions humaines. Une personne est ancrée par une fiche RH, une décision (`person_without_decision_sql`) ou un verdict humain sur un identifiant ou une forme de nom. 3 280 personnes sur 18 869 sont ancrées. Une personne sans décision, désignée par une même contribution qu'une personne ancrée, est supprimée : 131 personnes. Après redécision, 104 sont recréées à l'identique, 6 absorbées par une personne ancrée, 9 scindées entre une personne ancrée et une personne créée. Les 15 pertes par conflit d'identifiants disparaissent.
  - Deux contributions sont rattachées par le nom à une personne rejetée pour leur publication. Le rejet du 2026-10-23 a détaché seulement les contributions sources.
- [ ] Purge : elle marque à chaque run les contributions rattachées par le nom dont une contribution source a une forme de nom de plusieurs personnes. Le rattachement redonne la même personne quand une autre contribution source désigne une seule personne (225 contributions à chaque run au 2026-11-05). La purge applique la règle du rattachement.
- [ ] Candidats d'une contribution : intersection des candidats non vides de ses contributions sources. Une intersection vide ou multiple laisse la contribution sans personne. Simulation du 2026-11-05 sur 300 240 contributions, face à la règle actuelle :
  - Intersection dans le rattachement par le nom seul : une décision change. « Christian Boyer » dans HAL et ScanR, « Boyer, B » dans OpenAlex.
  - Intersection aussi au niveau des identifiants, les candidats d'une contribution source étant l'union des personnes désignées par ses identifiants : même résultat. Les 14 conflits d'identifiants opposent deux contributions sources, par exemple un ORCID de HAL et un IdRef de ScanR pour deux personnes en doublon (Christelle Richard, Christelle Gremeau-Richard).
  - Intersection des candidats de chaque contribution source, désignés par ses identifiants ou à défaut par son nom : 19 décisions changent. 18 rattachements par identifiant sont perdus face à un nom qui désigne une seule autre personne. Ce nom vient d'un alignement erroné ou d'une erreur de source : « Y. Sano » dans WoS pour Takane Sano, à l'ORCID confirmé.
- [ ] Documentation : `--rebuild-persons` dans `docs/exploitation/03-pipeline.md`.

## Questions ouvertes

- Périmètre des publications : il réunit les indices des seules contributions rattachées à une personne non exclue. Une erreur d'affiliation relève de la contribution source, pas de la personne.
- Recalcul immédiat des contributions invalidées par une décision de l'administration, exposé par le pipeline (`pipeline/public.py`) sur un index réduit aux valeurs de leurs contributions sources.
- Deux idées de ReCiter : enregistrer ce qui a concordé et pas seulement la règle ; réutiliser les confirmations et les rejets d'une personne comme indices pour ses autres contributions.
