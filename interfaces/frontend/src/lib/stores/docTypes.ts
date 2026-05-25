import { writable, derived } from 'svelte/store';

export type DocTypeLabel = { singular: string; plural: string };
export type DocTypeLabels = Record<string, DocTypeLabel>;

/** Labels FR canoniques chargés au boot par `+layout.ts` depuis `/api/doc-types`. */
export const docTypeLabels = writable<DocTypeLabels>({});

/** Dictionnaire `value → singulier` pour les badges/colonnes. */
export const docTypeSingular = derived(docTypeLabels, ($labels) => {
	const out: Record<string, string> = {};
	for (const [value, { singular }] of Object.entries($labels)) out[value] = singular;
	return out;
});

/** Dictionnaire `value → pluriel` pour les facettes/dropdowns. */
export const docTypePlural = derived(docTypeLabels, ($labels) => {
	const out: Record<string, string> = {};
	for (const [value, { plural }] of Object.entries($labels)) out[value] = plural;
	return out;
});
