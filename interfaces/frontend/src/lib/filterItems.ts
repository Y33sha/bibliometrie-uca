/** Facettes des toggles de filtre par présence : items `{ key, label }` fournis au composant de filtre pour les sources (listes des publications et des thèses), les identifiants et les éléments de curation en attente (annuaire et admin des personnes). La `key` indexe l'état du filtre et les comptes de facettes renvoyés par le backend. */
import { identifierTypeLabel, PERSON_IDENTIFIER_TYPES } from '#lib/labels.js';
import { sourceLabel } from '#lib/sources.svelte.js';

/** Item d'une source, libellé par l'API une fois les sources chargées. */
function sourceItem(key: string): { key: string; label: string } {
	return {
		key,
		get label() {
			return sourceLabel(key);
		},
	};
}

export const SOURCE_ITEMS = ['hal', 'openalex', 'scanr', 'wos'].map(sourceItem);

export const THESIS_SOURCE_ITEMS = ['hal', 'openalex', 'scanr', 'theses'].map(sourceItem);

export const IDENTIFIER_ITEMS = PERSON_IDENTIFIER_TYPES.map((key) => ({ key, label: identifierTypeLabel(key) }));

export const PENDING_ITEMS = [
	{ key: 'pending_forms', label: 'Formes de nom' },
	{ key: 'pending_identifiers', label: 'Identifiants' },
];
