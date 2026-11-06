/**
 * Filtres communs à plusieurs listes.
 */
import type { CheckboxFilter } from '#lib/filterRegistry.js';
import { filterLabels } from '#lib/labels.js';

/** Filtre des années, choisies par un intervalle. */
export function yearsFilter(group: string): CheckboxFilter {
	return {
		key: 'years',
		control: 'checkbox',
		label: filterLabels.years,
		param: 'year',
		group,
		facet: { type: 'simple', apiKey: 'years' },
		range: true,
	};
}

/** Filtre des entrées avec ou sans publication (éditeurs, publications en série). Par défaut, celles qui en ont ; hors `editable`, la liste les retient seules. */
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
