/** Facettes des toggles de filtre par présence : items `{ key, label }` fournis au composant
 * de filtre pour les sources (liste des publications), les identifiants et les éléments de
 * curation en attente (annuaire et admin des personnes). La `key` indexe l'état du filtre et
 * les comptes de facettes renvoyés par le backend — d'où `oa` pour OpenAlex, distinct du
 * `openalex` d'affichage de `sources.ts`. */
export const SOURCE_ITEMS = [
	{ key: 'hal', label: 'HAL' },
	{ key: 'oa', label: 'OpenAlex' },
	{ key: 'scanr', label: 'ScanR' },
	{ key: 'wos', label: 'WoS' },
];

export const IDENTIFIER_ITEMS = [
	{ key: 'orcid', label: 'ORCID' },
	{ key: 'idhal', label: 'idHAL' },
	{ key: 'idref', label: 'IdRef' },
];

export const PENDING_ITEMS = [
	{ key: 'pending_forms', label: 'Formes de nom' },
	{ key: 'pending_identifiers', label: 'Identifiants' },
];
