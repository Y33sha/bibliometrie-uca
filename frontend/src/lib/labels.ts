/** Labels pour les facettes doc_type (pluriel, pour les dropdowns). */
export const docTypeLabelsMap: Record<string, string> = {
	article: 'Articles',
	review: 'Reviews',
	conference_paper: 'Conférences',
	book: 'Ouvrages',
	book_chapter: 'Chapitres',
	thesis: 'Thèses',
	preprint: 'Preprints',
	editorial: 'Éditoriaux',
	report: 'Rapports',
	other: 'Autres'
};

/** Labels pour les doc_type (singulier, pour les tableaux). */
export const typeLabels: Record<string, string> = {
	article: 'Article',
	review: 'Review',
	conference_paper: 'Conf.',
	book: 'Ouvrage',
	book_chapter: 'Chapitre',
	thesis: 'Thèse',
	preprint: 'Preprint',
	editorial: 'Éditorial',
	report: 'Rapport',
	other: 'Autre'
};

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
