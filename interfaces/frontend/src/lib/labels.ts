import type { components } from './api/schema';

type PersonExclusion = components['schemas']['PersonExclusion'];
type SubjectVocabulary = components['schemas']['SubjectVocabulary'];

/** Licences dans l'ordre d'affichage. Chacune a sa couleur dans la variable CSS `--license-<clé>` de `shared.css`. `none` désigne une publication sans licence connue. */
export const licenseOrder = [
	'public-domain',
	'cc-by',
	'licence-ouverte',
	'open-source',
	'cc-by-sa',
	'cc-by-nd',
	'cc-by-nc',
	'cc-by-nc-sa',
	'cc-by-nc-nd',
	'publisher-open',
	'other-oa',
	'repository-distribution',
	'other',
	'all-rights-reserved',
	'none',
];

/** Libellés FR des types de relation entre publications, lus depuis la publication courante (sujet). Miroir de l'enum PG `relation_type` / `RelationType` du domain backend. */
export const relationTypeLabel: Record<string, string> = {
	is_preprint_of: 'Préprint de',
	has_preprint: 'A pour préprint',
	is_supplement_to: 'Supplément à',
	has_supplement: 'A pour supplément',
	is_part_of: 'Partie de',
	has_part: 'Contient',
	is_correction_of: 'Correction de',
	has_correction: 'Corrigé par',
	is_retraction_of: 'Rétractation de',
	has_retraction: 'Rétracté par',
	is_concern_about: 'Avis de préoccupation sur',
	has_concern: "Visé par un avis de préoccupation",
	is_translation_of: 'Traduction de',
	has_translation: 'A pour traduction',
	describes: 'Décrit les données',
	is_described_by: 'Décrit par',
	is_related_to: 'Apparenté à'
};

/** Niveau de signalement d'une relation, vu depuis la publication courante : décide sa couleur et son ordre dans le bandeau du header (le plus critique en premier).
 *  - `danger`    : rétractation — l'œuvre est invalidée (rouge) ;
 *  - `warning`   : correction/erratum, avis de préoccupation — à lire avec réserve (ambre) ;
 *  - `parent`    : la publi est une pièce rattachée à une œuvre principale (préprint, supplément, partie, traduction…) — teal ;
 *  - `secondary` : pièces dépendantes (la publi a un préprint, des données…) et apparentées — gris.
 * Les types absents tombent en `secondary`. */
export type RelationTier = 'danger' | 'warning' | 'parent' | 'secondary';
export const relationTier: Record<string, RelationTier> = {
	is_retraction_of: 'danger',
	has_retraction: 'danger',
	is_correction_of: 'warning',
	has_correction: 'warning',
	is_concern_about: 'warning',
	has_concern: 'warning',
	is_preprint_of: 'parent',
	is_supplement_to: 'parent',
	is_part_of: 'parent',
	is_translation_of: 'parent',
	is_described_by: 'parent',
	has_preprint: 'secondary',
	has_supplement: 'secondary',
	has_part: 'secondary',
	has_translation: 'secondary',
	describes: 'secondary',
	is_related_to: 'secondary'
};
/** Ordre d'affichage des niveaux dans le bandeau : le plus critique d'abord. */
export const relationTierRank: Record<RelationTier, number> = {
	danger: 0,
	warning: 1,
	parent: 2,
	secondary: 3
};

/** Libellés des voies OA : terme d'usage anglais pour les voies ouvertes, français pour l'embargo, la fermeture et l'absence d'information. */
export const oaLabelsMap: Record<string, string> = {
	diamond: 'Diamond',
	gold: 'Gold',
	hybrid: 'Hybrid',
	bronze: 'Bronze',
	green: 'Green',
	embargoed: 'Sous embargo',
	closed: 'Fermé',
	unknown: 'Indéterminé'
};

/** Explication de chaque voie OA, affichée au survol de son libellé. */
export const oaStatusDescriptions: Record<string, string> = {
	diamond: 'Revue ouverte, sans frais de publication',
	gold: 'Revue ouverte, avec frais de publication',
	hybrid: 'Article sous licence ouverte dans une revue sur abonnement',
	bronze: "Lecture libre chez l'éditeur, sans licence ouverte",
	green: 'Copie en archive ouverte ou sur un serveur de preprints',
	embargoed: 'Copie sous embargo',
	closed: 'Aucune copie ouverte',
	unknown: "Aucune information sur l'accès"
};

/** Libellé d'un statut OA, sinon la valeur brute. */
export function oaStatusLabel(oaStatus: string): string {
	return oaLabelsMap[oaStatus] ?? oaStatus;
}

/** Libellés des types d'identifiant d'une personne. */
export const identifierTypeLabels: Record<string, string> = {
	orcid: 'ORCID',
	idhal: 'idHAL',
	idref: 'IdRef',
	hal_person_id: 'Compte HAL'
};

/** Libellé d'un type d'identifiant d'une personne, sinon la valeur brute. */
export function identifierTypeLabel(idType: string): string {
	return identifierTypeLabels[idType] ?? idType;
}


/** Libellés FR des motifs d'exclusion d'une personne — enum PG `person_exclusion`. */
export const personExclusionLabels: Record<PersonExclusion, string> = {
	not_a_person: 'Fausse entité',
	out_of_perimeter: 'Hors périmètre'
};

/** Libellés FR des catégories de personnel de l'export RH (`hr_records.staff_category`). Une catégorie absente s'affiche telle quelle. */
export const staffCategoryLabels: Record<string, string> = {
	ENSEIG: 'Enseignants',
	BIATSS: 'BIATSS'
};

/** Libellés FR des vocabulaires de sujets — enum PG `subject_vocabulary`. */
export const subjectVocabularyLabels: Record<SubjectVocabulary, string> = {
	openalex: 'OpenAlex',
	hal_domain: 'Domaines HAL',
	rameau: 'RAMEAU',
	theses_discipline: 'Disciplines de thèse'
};

/** Classes CSS des statuts de détection d'une structure, dérivés de `is_confirmed` et `is_detected` par `deriveStructDetectionStatus`. */
export const structDetectionClasses: Record<string, string> = {
	confirmed: 'tag tag-pill tag-success',
	rejected: 'tag tag-pill tag-struck',
	detected: 'tag tag-pill tag-warning',
	manual: 'tag tag-pill tag-accent struct-manual'
};

/** Libellés courts des statuts de détection d'une structure (tooltip des badges feedback). */
export const structDetectionLabels: Record<string, string> = {
	confirmed: 'confirmé',
	rejected: 'rejeté',
	detected: 'détecté auto',
	manual: 'ajouté manuellement'
};

/** Désignation d'un ISSN selon son support, pour la fiche d'une revue. */
const issnPrefixes: Record<string, string> = {
	print: 'ISSN',
	electronic: 'eISSN',
	other: 'ISSN (autre support)'
};

/** Libellés FR des relations entre revues — `SerialRelation.kind`. */
export const serialRelationLabels: Record<string, string> = {
	previous_title: 'Titre précédent',
	next_title: 'Titre suivant',
	supplement: 'Supplément',
	main_serial: 'Supplément de'
};

/** Étiquette d'un ISSN : son support, et la mention ISSN-L. */
export function issnLabel(issn: { support: string | null; linking: boolean }): string {
	const support = issn.support ? issnPrefixes[issn.support] : null;
	if (issn.linking) return support ? `${support} · ISSN-L` : 'ISSN-L';
	return support ?? 'ISSN';
}

/** Rôles d'une contribution source dans leur ordre d'affichage. Valeurs de `ContributionRole` côté backend. */
export const CONTRIBUTION_ROLE_ORDER = [
	'author',
	'speaker',
	'editor',
	'scientific_editor',
	'translator',
	'contributor',
	'thesis_director',
	'rapporteur',
	'jury_president',
	'jury_member',
	'other',
];

/** Libellés FR des rôles d'une contribution source. */
export const contributionRoleLabels: Record<string, string> = {
	author: 'Auteur',
	speaker: 'Orateur',
	editor: 'Éditeur',
	scientific_editor: 'Éditeur scientifique',
	translator: 'Traducteur',
	contributor: 'Contributeur',
	thesis_director: 'Direction',
	rapporteur: 'Rapporteur',
	jury_president: 'Président du jury',
	jury_member: 'Examinateur',
	other: 'Autre rôle',
};

/** En-têtes des colonnes communes à plusieurs listes. */
export const columnLabels = {
	type: 'Type',
	year: 'Année',
	title: 'Titre',
	doi: 'DOI',
	author: 'Auteur',
	labs: 'Laboratoires',
	serial: 'Revue',
	publisher: 'Éditeur',
	country: 'Pays',
	address: 'Adresse',
	apc: 'APC',
	oaStatus: 'Voie OA',
	license: 'Licence',
	citationTop: 'Top citations',
	sources: 'Sources',
	access: 'Accès',
	publications: 'Publications',
} as const;

/** Seuils de citation (`CitationTop` côté API). */
export const citationTopLabels: Record<string, string> = {
	top_1_percent: 'Top 1 %',
	top_10_percent: 'Top 10 %',
};

/** Noms des filtres communs à plusieurs listes : au pluriel pour un choix multiple, au singulier pour un choix unique. */
export const filterLabels = {
	types: 'Types',
	years: 'Années',
	labs: 'Laboratoires',
	serial: 'Revues',
	publisher: 'Éditeurs',
	author: 'Auteurs',
	partner: 'Organisations partenaires',
	countries: 'Pays',
	apc: 'APC',
	oaStatuses: 'Voies OA',
	licenses: 'Licences',
	citationTops: 'Top citations',
	access: 'Accès',
	sources: 'Sources',
	lists: 'Listes',
} as const;
