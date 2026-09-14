# Chantier — Identifiants d'auteur mal placés dans un enregistrement source

## Contexte

**Un identifiant partagé au sein d'un enregistrement est requalifié.** `mark_shared_identifiers_dubious` ([identifiers.py](../../domain/persons/identifiers.py)) s'applique au normalize, dans les six extracteurs. Une valeur portée par au moins deux positions d'auteur d'un même enregistrement est une corruption : un identifiant désigne une seule signature par document. Toute position portant une valeur partagée voit ses identifiants suffixés `_dubious`. Ils restent en base, invisibles au matching, qui lit les clés nues. Le rattachement par nom reste ouvert.

**Le consensus d'une valeur d'identifiant se déduit des voix de ses signatures.** `fetch_identifier_votes` ([matching.py](../../infrastructure/pipeline/persons/matching.py)) compte, pour les seules valeurs disputées, les signatures qui portent la valeur sous chaque nom, et `consensus_name` ([matching.py](../../domain/persons/matching.py)) en tire le consensus. L'étape d'arbitrage des conflits d'identifiant s'en sert pour trancher à qui appartient une valeur disputée. Elle précède la cascade dans la phase `persons` ([phase.py](../../application/pipeline/persons/phase.py)).

**Une attribution `pending` naît de la cascade.** La cascade attribue à une personne, en `pending`, les identifiants des signatures qu'elle lui rattache. Une valeur déjà attribuée à une autre personne n'est pas écrasée : le conflit passe à l'arbitrage de l'exécution suivante. Un identifiant mal placé sur une signature rattachée par son nom est ainsi attribué à la mauvaise personne.

**Des identifiants isolés contredisent le nom qu'ils accompagnent.** Audit sur 3 486 317 positions de 126 226 enregistrements sources : 8 235 positions portent un identifiant dont le nom de consensus ne partage aucun mot avec le nom local, réparties sur 2 409 enregistrements. Par source : DataCite 3 660, HAL 2 137, OpenAlex 1 246, Crossref 1 152, ScanR 40. La contradiction est ponctuelle — 1 249 enregistrements n'en portent qu'une seule — et les enregistrements les plus touchés sont des articles de collaboration de deux à trois mille auteurs, avec 5 à 28 positions fausses.

Exemple : sur `10.1140/epjc/s10052-021-09775-5`, la signature « bogdan malaescu » porte l'ORCID de Stefan Raimund Maschek, que 56 autres signatures attestent.

**Le décalage est local.** Sur les 54 087 enregistrements portant au moins trois ORCID, aucun ne s'explique par un décalage uniforme de la suite des identifiants de −3 à +3 positions. Mais sur 2 385 signatures contredisant un consensus, le nom du consensus signe le même document dans 1 346 cas : à la position voisine dans 561 cas, à deux positions dans 101 cas. Les listes de collaboration étant alphabétiques, l'identifiant se retrouve sur un voisin alphabétique (Dado / Dahbi, Varol / Varouchas, McMahon / McNamara).

**Deux limites de la mesure.** 15 045 des 68 646 valeurs d'ORCID apparaissent dans un seul enregistrement source : leur consensus est leur propre nom local, donc une erreur y est invisible. Le test de compatibilité valide dès qu'un mot d'au moins trois lettres est commun, donc 8 235 est un minorant.

**L'effet sur le rattachement des personnes.** Une signature dont l'identifiant désigne quelqu'un d'autre attribue la publication à cette autre personne. Le rejet de la forme de nom, qui est le geste de correction disponible, écarte alors la forme pour la personne entière : le verdict `rejected` refuse même la corroboration par identifiant ([matching.py](../../domain/persons/matching.py)). Sur 8 348 paires (personne, publication) dont une signature détachée porte un ORCID enregistré pour cette personne, 2 325 ont perdu tout lien.

**La table des identités.** `author_identifying_keys` est unique sur `(author_name_normalized, person_identifiers)` et référencée par `source_authorships.identity_id`. Deux lignes de même nom, dont l'une porte le suffixe, sont deux identités distinctes.

**Trois verdicts portent sur trois objets.** Le statut `rejected` en désigne deux, d'où une collision de vocabulaire.

| Verdict | Objet | Portée |
|---|---|---|
| `person_identifiers.status` | valeur d'identifiant ↔ personne | la valeur n'appartient pas à cette personne |
| `person_name_forms.status` | forme de nom ↔ personne | la graphie ne désigne pas cette personne |
| carte des neutralisations | nom ↔ identifiant, sur une signature | l'appariement des deux est cassé sur cet enregistrement |

Les deux premiers portent sur une personne, le troisième sur un enregistrement source. Toutes les requêtes de la cascade excluent déjà les attributions rejetées.

## Décisions

- **Le consensus se calcule sur les clés nues.** Une valeur recopiée sur trois mille positions d'un même enregistrement y porte trois mille noms différents, donc trois mille voix d'une signature chacune : elle ne déplace pas le consensus. L'inclure n'apporte rien.
- **Le consensus est le nom qui porte strictement plus de voix que tous les autres.** Aucun seuil : une signature seule ne peut pas se contredire, et deux voix sur deux tranchent. Une égalité ne désigne aucun nom. Une faible majorité signale plutôt un doublon de personne, que la fusion de personnes règle dans l'administration.
- **Un seul consensus sert la requalification et les transferts.** Il se calcule pour toutes les valeurs. Les transferts adoptent la règle d'égalité : une égalité ne produit aucun transfert.
- **La contradiction se teste avec `same_person_name`**, la comparaison qui corrobore déjà un rattachement par identifiant.
- **Une passe par exécution suffit.** La requalification retire des voix aux seuls noms qui contredisent le consensus, jamais au nom majoritaire : le consensus en sort inchangé ou renforcé. Aucune itération jusqu'au point fixe.
- **La requalification s'intègre à l'étape d'arbitrage des conflits d'identifiant**, avant la cascade personnes. Le consensus est un agrégat de tout le stock, incalculable au normalize, qui traite un document à la fois.
- **La requalification précède la détection des conflits.** Une signature dont l'identifiant est neutralisé sort des porteurs de la valeur, et les conflits qu'elle créait disparaissent avant l'arbitrage.
- **Une signature résolue par identifiant et portant un identifiant neutralisé repasse à NULL**, comme une signature captée lors d'un transfert. La cascade la re-résout.
- **L'identité garde les identifiants bruts.** `person_identifiers` porte la forme d'origine, et l'unicité reste sur `(author_name_normalized, person_identifiers)`. Les identifiants exploitables se déduisent : ceux du brut dont la clé est absente de la carte des neutralisations.
- **La carte des neutralisations vit sur la signature.** `source_authorships` porte une colonne jsonb, `{"orcid": "shared"}`, vide dans le cas courant. Deux signatures de documents différents peuvent porter le même nom et les mêmes identifiants bruts, l'une partageant son identifiant avec une autre signature de son document et l'autre non : une identité unique sur le brut ne peut pas porter ces deux verdicts.
- **`shared` prime sur `misplaced`.** Un identifiant partagé est douteux avant tout examen du consensus, et les conflits qu'il produit ne valent pas d'être tranchés.
- **Aucune colonne de repointage.** L'identité reste stable quand un verdict change, donc rien à repointer en régime courant. La fusion des identités que le suffixe sépare relève de la migration.
- **Un identifiant mal placé est neutralisé, sans être réattribué.** Dans un décalage local, la signature propriétaire porte l'identifiant de son voisin, lui aussi neutralisé : les deux signatures se rattachent par leur nom. Réattribuer exigerait de porter des identifiants ajoutés en plus des neutralisés, de départager les cibles ambiguës et de suivre les décalages en chaîne.
- **La neutralisation porte sur l'identifiant, jamais sur le nom.** Un appariement cassé laisse ignorer lequel des deux éléments est fautif. Neutraliser l'identifiant retire un raccourci, et le rattachement par nom reste ouvert ; garder l'identifiant rattache la signature au propriétaire du consensus avec l'autorité d'un identifiant. Le canal le plus autoritaire cède.
- **Une attribution rejetée ne produit pas de neutralisation.** Elle porte sur le lien entre une valeur et une personne, pas sur la place de cette valeur dans un enregistrement.
- **La règle du consensus vaut pour tous les types d'identifiant.**
- **La reprise du stock est automatique.** Les deux motifs se déduisent des données, donc se recalculent à chaque exécution. La passe balaye tout le stock : un consensus bascule sans que le document concerné change.

## Questions ouvertes

Aucune.

## Phasage

### 1. Déplacer la neutralisation hors de l'identité

- [x] Sauvegarde CSV de `author_identifying_keys` et des liens des signatures vers les identités suffixées, repérées par `(source_publication_id, author_position)` (`data/backups/`).
- [x] Fragment SQL unique pour lire un identifiant non neutralisé d'une signature (`infrastructure/db/sql_fragments.py`).
- [x] Colonne `neutralized_identifiers` sur `source_authorships`. Les lecteurs de `person_identifiers` passent par le fragment : cascade personnes, problèmes HAL, files de l'administration.
- [x] Le writer partagé du normalize inscrit `shared` dans la colonne, une fois par document, au lieu de suffixer les clés dans chaque extracteur.
- [x] Migration, dans une transaction et livrée avec le code qui lit la colonne : carte `shared` sur les 61 714 signatures, repointage des signatures des 3 916 identités qui rejoignent une identité nue existante, suppression de ces identités, retrait du suffixe des 3 463 autres. Le retour arrière reconstruit les identités suffixées depuis la carte.

### 2. Requalification par consensus

- [x] Règle du consensus (`consensus_name`) : majorité stricte, égalité sans effet. Les transferts la lisent.
- [ ] Requalification `misplaced` dans l'étape d'arbitrage, avant la détection des conflits, sur tout le stock, avec un consensus calculé pour toutes les valeurs et partagé avec les transferts.
- [ ] Remise à NULL des signatures résolues par identifiant qui portent un identifiant neutralisé.
- [ ] Levée de la neutralisation quand l'identifiant rejoint le consensus.

## Liens

- [Gestion des publications dans l'administration](METIER_gestion-admin-des-publications.md) — le volet qui confronte les enregistrements sources d'une publication.
- [Gestion et dédoublonnage assistés de la base personnes](DATA_personnes-dedoublonnage-assiste.md)
