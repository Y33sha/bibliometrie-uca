# Chantier — Identifiants d'auteur mal placés dans un enregistrement source

## Contexte

**Un identifiant partagé au sein d'un enregistrement est requalifié.** `mark_shared_identifiers_dubious` ([identifiers.py](../../domain/persons/identifiers.py)) s'applique au normalize, dans les six extracteurs. Une valeur portée par au moins deux positions d'auteur d'un même enregistrement est une corruption : un identifiant désigne une seule signature par document. Toute position portant une valeur partagée voit ses identifiants suffixés `_dubious`. Ils restent en base, invisibles au matching, qui lit les clés nues. Le rattachement par nom reste ouvert.

**Le consensus d'une valeur d'identifiant est le nom que portent le plus de signatures.** `fetch_identifier_consensus` ([matching.py](../../infrastructure/pipeline/persons/matching.py)) le calcule sur les clés nues, donc hors des `_dubious`. `resolve_identifier_transfers` s'en sert après la cascade personnes pour arbitrer à qui appartient une valeur disputée.

**Des identifiants isolés contredisent le nom qu'ils accompagnent.** Audit sur 3 486 317 positions de 126 226 enregistrements sources : 8 235 positions portent un identifiant dont le nom de consensus ne partage aucun mot avec le nom local, réparties sur 2 409 enregistrements. Par source : DataCite 3 660, HAL 2 137, OpenAlex 1 246, Crossref 1 152, ScanR 40. La contradiction est ponctuelle — 1 249 enregistrements n'en portent qu'une seule — et les enregistrements les plus touchés sont des articles de collaboration de deux à trois mille auteurs, avec 5 à 28 positions fausses.

Exemple : sur `10.1140/epjc/s10052-021-09775-5`, la signature « bogdan malaescu » porte l'ORCID de Stefan Raimund Maschek, que 56 autres signatures attestent.

**Aucun décalage d'indice systématique.** Sur les 54 087 enregistrements portant au moins trois ORCID, 10 sont majoritairement contradictoires, et aucun ne s'explique par un décalage uniforme de la suite des identifiants de −3 à +3 positions.

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
- **Le consensus tranche à partir de deux voix sur trois.** En deçà, il ne désigne personne.
- **Une passe par exécution suffit.** La requalification retire des voix aux seuls noms qui contredisent le consensus, jamais au nom majoritaire : le consensus en sort inchangé ou renforcé. Aucune itération jusqu'au point fixe.
- **La passe lit le consensus avant la cascade personnes.** Le consensus est un agrégat de tout le stock, incalculable au normalize, qui traite un document à la fois.
- **L'identité garde les identifiants bruts.** `person_identifiers` porte la forme d'origine, et l'unicité reste sur `(author_name_normalized, person_identifiers)`. Les identifiants exploitables se déduisent : ceux du brut dont la clé est absente de la carte des neutralisations.
- **La carte des neutralisations vit sur la signature.** `source_authorships` porte une colonne jsonb, `{"orcid": "shared"}`, vide dans le cas courant. Deux signatures de documents différents peuvent porter le même nom et les mêmes identifiants bruts, l'une partageant son identifiant avec une autre signature de son document et l'autre non : une identité unique sur le brut ne peut pas porter ces deux verdicts.
- **`shared` prime sur `misplaced`.** Un identifiant partagé est douteux avant tout examen du consensus, et les conflits qu'il produit ne valent pas d'être tranchés.
- **Aucune colonne de repointage.** L'identité reste stable quand un verdict change, donc rien à repointer en régime courant. La fusion des identités que le suffixe sépare relève de la migration.
- **La neutralisation porte sur l'identifiant, jamais sur le nom.** Un appariement cassé laisse ignorer lequel des deux éléments est fautif. Neutraliser l'identifiant retire un raccourci, et le rattachement par nom reste ouvert ; garder l'identifiant rattache la signature au propriétaire du consensus avec l'autorité d'un identifiant. Le canal le plus autoritaire cède.
- **Une attribution rejetée ne produit pas de neutralisation.** Elle porte sur le lien entre une valeur et une personne, pas sur la place de cette valeur dans un enregistrement.
- **La règle du consensus vaut pour tous les types d'identifiant.**
- **La reprise du stock est automatique.** Les deux motifs se déduisent des données, donc se recalculent à chaque exécution. La passe balaye tout le stock : un consensus bascule sans que le document concerné change.

## Questions ouvertes

Aucune.

## Phasage

### 1. Cadrage

- [x] Trancher les questions ouvertes.
- [ ] Mesurer la précision de la règle de consensus sur un échantillon relu.

### 2. Déplacer la neutralisation hors de l'identité

- [ ] Colonne des neutralisations sur `source_authorships`, lue par le matching et le consensus.
- [ ] Le normalize y inscrit `shared` au lieu de suffixer les clés.
- [ ] Migration : retirer le suffixe des 7 379 identités concernées, fusionner les 3 916 qui rejoignent une identité existante, repointer leurs 61 714 signatures, supprimer les identités vidées.

### 3. Requalification par consensus

- [ ] Passe de requalification, avant la cascade personnes, balayant tout le stock.
- [ ] Levée de la neutralisation quand l'identifiant rejoint le consensus.

## Liens

- [Gestion des publications dans l'administration](METIER_gestion-admin-des-publications.md) — le volet qui confronte les enregistrements sources d'une publication.
- [Gestion et dédoublonnage assistés de la base personnes](DATA_personnes-dedoublonnage-assiste.md)
