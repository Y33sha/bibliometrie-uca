/**
 * Filtres communs aux listes des référentiels de l'édition (éditeurs, publications en série).
 */
import type { CheckboxFilter } from '#lib/filterRegistry.js';

/** Filtre des entrées avec ou sans publication. Par défaut, celles qui en ont ; hors `editable`, la liste les retient seules. */
export function hasPublicationsFilter(group: string, editable: () => boolean): CheckboxFilter {
	return {
		key: 'publications',
		control: 'checkbox',
		label: 'Publications',
		param: 'has_publications',
		group,
		facet: { type: 'boolean', apiKey: 'publications', yesLabel: 'Avec', noLabel: 'Sans' },
		defaultSelection: () => ['yes'],
		// Une seule valeur filtre ; les deux cochées retiennent toutes les entrées.
		serialize: (selected) => (selected.length === 1 ? selected[0] : null),
		fixed: () => (editable() ? null : 'yes'),
	};
}
