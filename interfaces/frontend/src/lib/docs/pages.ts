export const DOC_SLUGS = [
	'architecture',
	'donnees',
	'sources',
	'pipeline',
	'exploitation',
	'guide-utilisateur',
	'glossaire'
] as const;

export type DocSlug = (typeof DOC_SLUGS)[number];
