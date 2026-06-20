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

/** Libellés courts des sources (badges, colonnes). */
export const sourceLabels: Record<string, string> = {
	hal: 'HAL',
	openalex: 'OpenAlex',
	wos: 'WoS',
	scanr: 'ScanR',
	theses: 'theses.fr',
	crossref: 'Crossref'
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
