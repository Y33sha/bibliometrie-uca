import { describe, it, expect, beforeEach } from 'vitest';

import {
	activeColumns,
	appendFilterParams,
	encodePresence,
	facetDefs,
	initialValues,
	isShown,
	restoreValues,
	urlFilterDefs,
	urlState,
	type ListFilter,
} from './filterRegistry';

let fixedLab: string | null = null;
let perimeterEnabled = true;

const years: ListFilter = {
	key: 'years',
	control: 'checkbox',
	label: 'Années',
	param: 'year',
	facet: { type: 'simple', apiKey: 'years' },
	column: 'year',
};
const types: ListFilter = {
	key: 'types',
	control: 'checkbox',
	label: 'Types',
	param: 'doc_type',
	facet: { type: 'simple', apiKey: 'doc_types' },
	url: {
		encode: (selected) => (selected.length ? selected.join(',') : 'all'),
		decode: (raw) => (raw === 'all' ? [] : raw.split(',')),
		defaultValue: 'article',
	},
	showColumns: ['type'],
};
const labs: ListFilter = {
	key: 'labs',
	control: 'checkbox',
	label: 'Laboratoires',
	param: 'lab_id',
	facet: { type: 'labeled', apiKey: 'labs' },
	fixed: () => fixedLab,
};
const perimeter: ListFilter = {
	key: 'perimeter',
	control: 'checkbox',
	label: 'Périmètre',
	param: 'in_perimeter',
	facet: { type: 'labeled', apiKey: 'in_perimeter' },
	enabled: () => perimeterEnabled,
	hideWhenEmpty: true,
	showColumns: ['corr'],
};
const journal: ListFilter = {
	key: 'journal',
	control: 'entity',
	label: 'Revue',
	param: 'journal_id',
	entity: 'journal',
	showColumns: ['journal'],
};
const sources: ListFilter = {
	key: 'sources',
	control: 'presence',
	label: 'Sources',
	param: 'source_filter',
	items: [],
};
const FILTERS = [years, types, labs, perimeter, journal, sources];

describe('filterRegistry', () => {
	beforeEach(() => {
		fixedLab = null;
		perimeterEnabled = true;
	});

	it('écrit dans la requête les seuls filtres qui filtrent', () => {
		const values = initialValues(FILTERS);
		values.checkbox.years = ['2024', '2023'];
		values.entity.journal = '12';
		values.presence.sources = { hal: 'yes', wos: 'no', oa: 'all' };
		const params = new URLSearchParams();
		appendFilterParams(FILTERS, values, params);
		expect(Object.fromEntries(params)).toEqual({
			year: '2024,2023',
			journal_id: '12',
			source_filter: 'hal_yes,wos_no',
		});
	});

	it('une valeur fixée par la page remplace la sélection et masque le contrôle', () => {
		fixedLab = '7';
		const values = initialValues(FILTERS);
		values.checkbox.labs = ['3'];
		const params = new URLSearchParams();
		appendFilterParams(FILTERS, values, params);
		expect(params.get('lab_id')).toBe('7');
		expect(isShown(labs, () => true, () => 1)).toBe(false);
	});

	it('masque un contrôle dont la colonne est cachée, ou qui attend des options', () => {
		expect(isShown(years, (column) => column !== 'year', () => 1)).toBe(false);
		expect(isShown(perimeter, () => true, () => 0)).toBe(false);
		expect(isShown(perimeter, () => true, () => 2)).toBe(true);
		perimeterEnabled = false;
		expect(isShown(perimeter, () => true, () => 2)).toBe(false);
	});

	it("écrit la sélection dans l'URL sous sa forme propre, et la relit", () => {
		const defs = urlFilterDefs(FILTERS);
		expect(defs.types).toEqual({ type: 'single', urlKey: 'doc_type', defaultValue: 'article' });
		expect(defs.years).toEqual({ type: 'string_array', urlKey: 'year' });
		expect(defs.journal).toEqual({ type: 'single', urlKey: 'journal_id' });
		expect(defs.sources).toEqual({ type: 'source_states', urlKey: 'source_filter' });

		const values = initialValues(FILTERS);
		expect(urlState(FILTERS, values).types).toBe('all');

		restoreValues(FILTERS, { types: 'all', years: ['2024'], journal: '12', sources: { hal: 'no' } }, values);
		expect(values.checkbox.types).toEqual([]);
		expect(values.checkbox.years).toEqual(['2024']);
		expect(values.entity.journal).toBe('12');
		expect(values.presence.sources).toEqual({ hal: 'no' });
	});

	it('déclare les décomptes des seules cases à cocher', () => {
		expect(Object.keys(facetDefs(FILTERS))).toEqual(['years', 'types', 'labs', 'perimeter']);
	});

	it('rend les colonnes des filtres actifs proposés dans la page', () => {
		const values = initialValues(FILTERS);
		values.checkbox.types = ['article'];
		values.entity.journal = '12';
		values.checkbox.perimeter = ['yes'];
		perimeterEnabled = false;
		expect(activeColumns(FILTERS, values).sort()).toEqual(['journal', 'type']);
	});

	it("ignore l'état « tous » d'un filtre de présence", () => {
		expect(encodePresence({ hal: 'all' })).toBe('');
	});
});
