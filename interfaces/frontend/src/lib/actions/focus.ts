import type { Action } from 'svelte/action';

/**
 * Focuse le nœud dès son montage. Pour les champs rendus conditionnellement
 * (édition en place, picker, ligne ajoutée) où l'attribut natif `autofocus`
 * ne se redéclenche pas : il n'agit qu'au chargement initial de la page, pas
 * à l'apparition d'un bloc `{#if}`.
 *
 * Avec `{ select: true }`, sélectionne aussi le texte présent (champ texte ou
 * zone multiligne) — pratique pour remplacer une valeur en édition en place :
 * la frappe écrase, une flèche désélectionne pour corriger.
 */
export const autofocus: Action<HTMLElement, { select?: boolean } | undefined> = (node, param) => {
	node.focus();
	if (param?.select && (node instanceof HTMLInputElement || node instanceof HTMLTextAreaElement)) {
		node.select();
	}
};
