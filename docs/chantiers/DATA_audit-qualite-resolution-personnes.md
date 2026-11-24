# Chantier — Audit de la qualité de la résolution des personnes

## Contexte

Une contribution réunit les contributions sources d'un même auteur dans une publication, alignées par la phase `author_grouping`, et désigne sa personne, décidée par la phase `persons`. Les deux mécanismes sont en place. Restent des contrôles des identifiants et des outils de correction.

Mesures du 2026-11-24 (`data/experiments/resolution-personnes/audit_rapide*.py`), sans suite :

- Neutralisation par nom contraire au consensus : 38 508 contributions sources, dont 503 du périmètre.
- ORCID d'OpenAlex sur un enregistrement source sans DOI : 77 529 contributions sources. Quand une autre source de la contribution donne un ORCID, il diffère dans 58 cas sur 1 705.
- Auteurs collectifs non reconnus, au nom d'un organisme : environ 500 contributions sources, dont 10 du périmètre.

## Décisions

- Les mesures et les relectures se font sur la base de production. La base locale sert à écrire les règles.

## Phasage

### Phase 1 — Identifiants

- [ ] Neutralisation par partage d'un auteur listé deux fois dans un enregistrement source : ses deux contributions sources perdent son identifiant (Polichtchouk et Polishchuk, même ORCID). Au 2026-11-24, 70 724 contributions sources ont une neutralisation par partage, dont 514 du périmètre. 403 de ces 514 sont en doublon d'auteur (`duplicate_of`). La neutralisation a lieu à la normalisation, avant la détection des doublons d'auteur par l'alignement.
- [ ] Identifiants attribués à tort, au 2026-11-24 :
  - 106 personnes ont plusieurs ORCID non rejetés, dont 17 à fiche RH ;
  - 289 contributions sont rattachées par un IdRef autre que l'IdRef confirmé de leur personne ;
  - 530 paires rejetées de 14 personnes comportent seulement des identifiants de l'homonyme, attribués à la personne puis rejetés : surtout des ORCID de Crossref et d'INSPIRE-HEP dans des grandes collaborations (chantier [détection des fausses attributions](archived/2026-11-24_DATA_detection-fausses-attributions.md)).
- [ ] Contrôle des identifiants par le nom déclaré dans IdRef et dans ORCID.
- [x] File des doublons par nom : noms de famille comparés aussi sans espaces ni tirets (Le Roy et Leroy, N'Sambu et Nsambu). 14 paires au 2026-11-24. 5e1f0a9b3

### Phase 2 — Rattachements et corrections

- [ ] Repérage des erreurs des sources révélées par une contribution : des contributions sources d'une même contribution qui désigneraient seules des personnes différentes signalent une erreur de groupement, de nom, d'identifiant ou d'affiliation. Outil de l'administration, comme pour les fusions suspectes de publications.
- [ ] Scission d'une contribution par une décision humaine, quand deux de ses contributions sources désignent deux personnes.
- [ ] File d'administration des contributions aux affiliations conflictuelles : certaines contributions sources donnent un indice de périmètre, d'autres une affiliation hors périmètre. L'administration décide.
- [x] Option `--rebuild-persons` : redécision de toutes les contributions hors mode manuel, contre les personnes existantes, par lots de 4 000 publications. Simulation du 2026-11-05 sur 300 185 contributions : 294 155 gardent leur personne, 25 la perdent, 11 en gagnent une, une change de personne. 3282b4515
  - Suppression puis recréation des personnes sans fiche RH et sans décision humaine (`person_without_decision_sql`) : 16 447 personnes supprimées sur 18 869, 88 273 contributions hors périmètre sans personne. Ces contributions sont rattachées par un identifiant à verdict humain, supprimé avec la personne. Les verdicts humains sur les identifiants (1 965) et sur les formes de nom (1 765) sont absents de `person_without_decision_sql`.
  - Variante qui conserve toutes les décisions humaines. Une personne est ancrée par une fiche RH, une décision (`person_without_decision_sql`) ou un verdict humain sur un identifiant ou une forme de nom. 3 280 personnes sur 18 869 sont ancrées. Une personne sans décision, désignée par une même contribution qu'une personne ancrée, est supprimée : 131 personnes. Après redécision, 104 sont recréées à l'identique, 6 absorbées par une personne ancrée, 9 scindées entre une personne ancrée et une personne créée. Les 15 pertes par conflit d'identifiants disparaissent.
  - Deux contributions sont rattachées par le nom à une personne rejetée pour leur publication. Le rejet du 2026-10-23 a détaché seulement les contributions sources.
- [x] Purge : elle redécide avec la règle du rattachement les contributions rattachées par le nom dont une contribution source a une forme de nom d'une autre personne. Elle marque celles dont la décision change : 3 contributions au 2026-11-05, contre 225 à chaque run avec le marquage par forme ambiguë. e9f3075c8
- [x] Candidats d'une contribution : intersection des candidats non vides de ses contributions sources, aux identifiants puis au nom. Les candidats d'une contribution source par identifiant réunissent les personnes désignées par chacun de ses identifiants. Une intersection vide ou multiple laisse la contribution sans personne. a1597efbd. Simulation du 2026-11-05 sur 300 240 contributions, face à la règle où une contribution source univoque l'emporte sur une contribution source ambiguë :
  - Intersection dans le rattachement par le nom seul : une décision change. « Christian Boyer » dans HAL et ScanR, « Boyer, B » dans OpenAlex.
  - Intersection aussi au niveau des identifiants, les candidats d'une contribution source étant l'union des personnes désignées par ses identifiants : même résultat. Les 14 conflits d'identifiants opposent deux contributions sources, par exemple un ORCID de HAL et un IdRef de ScanR pour deux personnes en doublon (Christelle Richard, Christelle Gremeau-Richard).
  - Intersection des candidats de chaque contribution source, désignés par ses identifiants ou à défaut par son nom : 19 décisions changent. 18 rattachements par identifiant sont perdus face à un nom qui désigne une seule autre personne. Ce nom vient d'un alignement erroné ou d'une erreur de source : « Y. Sano » dans WoS pour Takane Sano, à l'ORCID confirmé.
- [x] Documentation : `--rebuild-persons` dans `docs/exploitation/03-pipeline.md`.

## Questions ouvertes

- Périmètre des publications : il réunit les indices des seules contributions rattachées à une personne non exclue. Une erreur d'affiliation relève de la contribution source, pas de la personne.
- Recalcul immédiat des contributions invalidées par une décision de l'administration, exposé par le pipeline (`pipeline/public.py`) sur un index réduit aux valeurs de leurs contributions sources.
- Deux coauteurs homonymes de même graphie dans un enregistrement source : critère qui les distingue d'un auteur listé deux fois.
- Adresse concaténée comme indice du document : la publication entre dans le périmètre, la contribution se rattache par le nom ou l'identifiant sans créer de personne. Étude du 2026-11-16 (`doc_evidence.py`, chantier [vérification des affiliations](archived/2026-11-24_DATA_verification-affiliations.md)).
  - Mise en œuvre : un indice `concatenated_address` parmi les indices liés au document, hors des structures des contributions et de l'union des indices de la contribution, et un troisième état de la décision du rattachement.
  - 103 publications recevraient l'indice. 93 contributions sans personne se rattacheraient par le nom à une personne existante, souvent une fausse personne du périmètre à une, deux ou trois contributions, ou un homonyme. Garde-fou possible : rattachement limité aux personnes à fiche RH ou à identifiant confirmé.
