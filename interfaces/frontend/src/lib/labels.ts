/** Libellés FR (singulier) des types de documents, codés en dur.
 * Source de vérité de la liste canonique : l'enum PG `doc_type` /
 * `DOC_TYPES` du domain backend. La cohérence des clés est vérifiée
 * par un test pytest (tests/unit/domain/publications/test_doc_types.py)
 * qui lit ce fichier et casse si une valeur de l'enum n'a pas son libellé. */
export const docTypeSingular: Record<string, string> = {
	article: 'Article',
	conference_paper: 'Conference paper',
	book: 'Ouvrage',
	book_chapter: 'Chapitre',
	thesis: 'Thèse',
	ongoing_thesis: 'Thèse en cours',
	preprint: 'Preprint',
	review: 'Article de synthèse',
	editorial: 'Éditorial',
	report: 'Rapport',
	peer_review: 'Peer review',
	other: 'Autre',
	dataset: 'Données',
	software: 'Logiciel',
	patent: 'Brevet',
	hdr: 'HDR',
	memoir: 'Mémoire',
	poster: 'Poster',
	letter: "Lettre à l'éditeur",
	erratum: 'Erratum',
	retraction: 'Rétractation',
	book_review: 'Recension',
	data_paper: 'Data paper',
	proceedings: 'Proceedings',
	media: 'Intervention média'
};

/** Libellés FR (pluriel) des types de documents — cf. docTypeSingular. */
export const docTypePlural: Record<string, string> = {
	article: 'Articles',
	conference_paper: 'Conference papers',
	book: 'Ouvrages',
	book_chapter: 'Chapitres',
	thesis: 'Thèses',
	ongoing_thesis: 'Thèses en cours',
	preprint: 'Preprints',
	review: 'Articles de synthèse',
	editorial: 'Éditoriaux',
	report: 'Rapports',
	peer_review: 'Peer reviews',
	other: 'Autres',
	dataset: 'Données',
	software: 'Logiciels',
	patent: 'Brevets',
	hdr: 'HDR',
	memoir: 'Mémoires',
	poster: 'Posters',
	letter: "Lettres à l'éditeur",
	erratum: 'Errata',
	retraction: 'Rétractations',
	book_review: 'Recensions',
	data_paper: 'Data papers',
	proceedings: 'Proceedings',
	media: 'Interventions média'
};

/** Familles de doc_types : un niveau grossier au-dessus du `doc_type` fin, pour grouper et filtrer
 * les listes (distinguer les publications au sens strict des autres objets). Couvre exhaustivement
 * l'enum `doc_type` ; l'ordre est celui d'affichage. Découpage de première intention, ajustable.
 * Mémoires exclus des listes par ailleurs et thèses en cours invisibles → la famille académique
 * s'intitule « Thèses » (ses membres visibles sont thèses + HDR). */
export const docTypeFamilies: { key: string; label: string; types: string[] }[] = [
	{
		key: 'publications',
		label: 'Publications',
		types: ['article', 'conference_paper', 'book', 'book_chapter', 'review', 'data_paper']
	},
	{ key: 'preprints', label: 'Prépublications', types: ['preprint'] },
	{ key: 'theses', label: 'Thèses', types: ['thesis', 'ongoing_thesis', 'hdr', 'memoir'] },
	{ key: 'data', label: 'Données & logiciels', types: ['dataset', 'software', 'patent'] },
	{
		key: 'misc',
		label: 'Annexes & divers',
		types: [
			'other',
			'media',
			'poster',
			'report',
			'erratum',
			'retraction',
			'peer_review',
			'editorial',
			'letter',
			'book_review',
			'proceedings'
		]
	}
];
/** Famille (clé) d'un `doc_type`, dérivée de `docTypeFamilies`. */
export const docTypeFamilyOf: Record<string, string> = Object.fromEntries(
	docTypeFamilies.flatMap((f) => f.types.map((t) => [t, f.key]))
);

export const docTypeGroupedColors: Record<string, string> = {
	article: '#2f7ed8',
	review: '#1f5c9e',
	preprints: '#b3d9f5',
	conference_paper: '#b18fcf',
	book: '#ffa93b',
	book_chapter: '#f4c430',
	data_paper: '#66bb6a',
	theses: '#c0392b',
	data: '#43a047',
	misc: '#cfd3d6'
};

/** Libellés FR des types de relation entre publications, lus depuis la publication courante
 * (sujet). Miroir de l'enum PG `relation_type` / `RelationType` du domain backend. */
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

/** Niveau de signalement d'une relation, vu depuis la publication courante : décide sa couleur et
 * son ordre dans le bandeau du header (le plus critique en premier).
 *  - `danger`    : rétractation — l'œuvre est invalidée (rouge) ;
 *  - `warning`   : correction/erratum, avis de préoccupation — à lire avec réserve (ambre) ;
 *  - `parent`    : la publi est une pièce rattachée à une œuvre principale (préprint, supplément,
 *                  partie, traduction…) — teal ;
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

/** Accès générique pour la fiche détail, sans le jargon OA (gold/green/diamond/…) : on ne dit que
 * « ouvert / fermé / sous embargo ». Retourne `null` si indéterminé (rien à afficher). Le cas
 * « thèse en cours » est porté par le `doc_type`, pas ici. `cls` = classe de pastille colorée. */
export function accessTag(oaStatus: string | null | undefined): { label: string; cls: string } | null {
	if (!oaStatus || oaStatus === 'unknown') return null;
	if (oaStatus === 'closed') return { label: 'Fermé', cls: 'access-closed' };
	if (oaStatus === 'embargoed') return { label: 'Sous embargo', cls: 'access-embargo' };
	return { label: 'Ouvert', cls: 'access-open' }; // diamond/gold/hybrid/green/bronze
}

/** Labels pour les voies OA. */
export const oaLabelsMap: Record<string, string> = {
	diamond: 'Diamond',
	gold: 'Gold',
	hybrid: 'Hybrid',
	bronze: 'Bronze',
	green: 'Green',
	embargoed: 'Sous embargo',
	closed: 'Closed',
	unknown: 'Indéterminé'
};


/** Classes CSS associées aux statuts d'identifiant personne. */
export const identifierStatusClasses: Record<string, string> = {
	confirmed: 'id-confirmed',
	rejected: 'id-rejected',
	pending: 'id-pending'
};

/** Classes CSS associées aux statuts de détection d'une structure
 * dans le tableau de bord feedback. Le statut est dérivé de
 * `is_confirmed` + `is_detected` via `deriveStructDetectionStatus`. */
export const structDetectionClasses: Record<string, string> = {
	confirmed: 'struct-tag struct-confirmed',
	rejected: 'struct-tag struct-rejected',
	detected: 'struct-tag struct-detected',
	manual: 'struct-tag struct-manual'
};

/** Libellés courts des statuts de détection d'une structure
 * (tooltip des badges feedback). */
export const structDetectionLabels: Record<string, string> = {
	confirmed: 'confirmé',
	rejected: 'rejeté',
	detected: 'détecté auto',
	manual: 'ajouté manuellement'
};
