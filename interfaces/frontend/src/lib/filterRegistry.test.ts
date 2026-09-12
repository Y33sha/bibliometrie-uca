import { describe, it, expect, beforeEach } from 'vitest';

import {
	activeColumns,
	appendFilterParams,
	checkboxSummary,
	clearValue,
	encodePresence,
	facetDefs,
	filterSections,
	initialValues,
	isShown,
	presenceSummary,
	restoreValues,
	urlFilterDefs,
	urlState,
	type CheckboxFilter,
	type EntityChoiceFilter,
	type ListFilter,
	type PresenceFilter,
} from './filterRegistry';

let fixedLab: string | null = null;
let perimeterEnabled = true;

const years: CheckboxFilter = {
	key: 'years',
	control: 'checkbox',
	label: 'Années',
	param: 'year',
	facet: { type: 'simple', apiKey: 'years' },
};
const types: CheckboxFilter = {
	key: 'types',
	control: 'checkbox',
	label: 'Types',
	param: 'doc_type',
	facet: { type: 'simple', apiKey: 'doc_types' },
	groups: [{ label: 'Publications', values: ['article', 'book'] }],
	url: {
		encode: (selected) => (selected.length ? selected.join(',') : 'all'),
		decode: (raw) => (raw === 'all' ? [] : raw.split(',')),
		defaultValue: 'article',
	},
	showColumns: ['type'],
};
const labs: CheckboxFilter = {
	key: 'labs',
	control: 'checkbox',
	label: 'Laboratoires',
	param: 'lab_id',
	facet: { type: 'labeled', apiKey: 'labs' },
	fixed: () => fixedLab,
};
const perimeter: CheckboxFilter = {
	key: 'perimeter',
	control: 'checkbox',
	label: 'Périmètre',
	param: 'in_perimeter',
	facet: { type: 'labeled', apiKey: 'in_perimeter' },
	group: 'Auteurs',
	enabled: () => perimeterEnabled,
	hideWhenEmpty: true,
	showColumns: ['corr'],
};
const journal: EntityChoiceFilter = {
	key: 'journal',
	control: 'entity',
	label: 'Revue',
	param: 'journal_id',
	entity: 'journal',
	group: 'Revue et éditeur',
	showColumns: ['journal'],
};
const sources: PresenceFilter = {
	key: 'sources',
	control: 'presence',
	label: 'Sources',
	param: 'source_filter',
	group: 'Auteurs',
	items: [
		{ key: 'hal', label: 'HAL' },
		{ key: 'wos', label: 'WoS' },
		{ key: 'oa', label: 'OpenAlex' },
	],
};
const FILTERS: ListFilter[] = [years, types, labs, perimeter, journal, sources];

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
		expect(isShown(labs, () => 1)).toBe(false);
	});

	it('masque un contrôle que la page ne propose pas, ou qui attend des options', () => {
		expect(isShown(perimeter, () => 0)).toBe(false);
		expect(isShown(perimeter, () => 2)).toBe(true);
		perimeterEnabled = false;
		expect(isShown(perimeter, () => 2)).toBe(false);
	});

	it('range les contrôles sans rubrique dans la barre principale, les autres par rubrique', () => {
		const { primary, groups } = filterSections(FILTERS);
		expect(primary.map((f) => f.key)).toEqual(['years', 'types', 'labs']);
		expect(groups.map((g) => [g.label, g.filters.map((f) => f.key)])).toEqual([
			['Auteurs', ['perimeter', 'sources']],
			['Revue et éditeur', ['journal']],
		]);
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

	it('vide la sélection de chaque type de filtre', () => {
		const values = initialValues(FILTERS);
		values.checkbox.years = ['2024'];
		values.entity.journal = '12';
		values.presence.sources = { hal: 'yes' };
		for (const f of FILTERS) clearValue(f, values);
		expect(values).toEqual(initialValues(FILTERS));
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

	it('résume une sélection en nommant les groupes entièrement cochés', () => {
		const options = [
			{ value: 'article', text: 'Articles' },
			{ value: 'book', text: 'Ouvrages' },
			{ value: 'thesis', text: 'Thèses' },
		];
		expect(checkboxSummary(types, ['article', 'book', 'thesis'], options)).toBe('Publications, Thèses');
		expect(checkboxSummary(types, ['article'], options)).toBe('Articles');
		expect(checkboxSummary(years, ['2024', '2023', '2022', '2021'], [])).toBe('2024, 2023 +2');
	});

	it('résume un filtre de présence', () => {
		expect(presenceSummary(sources, { hal: 'yes', wos: 'no', oa: 'all' })).toBe('avec HAL, sans WoS');
	});
});
