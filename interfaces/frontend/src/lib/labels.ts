/** Labels pour les voies OA. */
export const oaLabelsMap: Record<string, string> = {
	diamond: 'Diamond',
	gold: 'Gold',
	hybrid: 'Hybrid',
	bronze: 'Bronze',
	green: 'Green',
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

/** Classes CSS associées aux badges de source. */
export const sourceBadgeClasses: Record<string, string> = {
	hal: 'badge-hal',
	openalex: 'badge-oa',
	wos: 'badge-wos',
	scanr: 'badge-scanr',
	theses: 'badge-theses',
	crossref: 'badge-crossref'
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
