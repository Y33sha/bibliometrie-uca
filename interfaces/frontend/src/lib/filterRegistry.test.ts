import { describe, it, expect, beforeEach } from 'vitest';

import {
	activeColumns,
	appendFilterParams,
	checkboxSummary,
	clearValue,
	encodePresence,
	explicitSelectionUrl,
	facetDefs,
	filterSections,
	initialValues,
	isShown,
	presenceSummary,
	restoreValues,
	summarizeParts,
	ignoredFilters,
	transferParams,
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
const serial: EntityChoiceFilter = {
	key: 'serial',
	control: 'entity',
	label: 'Revue',
	param: 'serial_id',
	entity: 'serial',
	group: 'Revue et éditeur',
	showColumns: ['serial'],
};
const subjects: EntityChoiceFilter = {
	key: 'subjects',
	control: 'entity',
	label: 'Sujets',
	param: 'subject_id',
	entity: 'subject',
	multiple: true,
	group: 'Sujets',
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
const FILTERS: ListFilter[] = [years, types, labs, perimeter, serial, subjects, sources];

describe('filterRegistry', () => {
	beforeEach(() => {
		fixedLab = null;
		perimeterEnabled = true;
	});

	it('écrit dans la requête les seuls filtres qui filtrent', () => {
		const values = initialValues(FILTERS);
		values.checkbox.years = ['2024', '2023'];
		values.entity.serial = ['12'];
		values.entity.subjects = ['3', '5'];
		values.presence.sources = { hal: 'yes', wos: 'no', oa: 'all' };
		const params = new URLSearchParams();
		appendFilterParams(FILTERS, values, params);
		expect(Object.fromEntries(params)).toEqual({
			year: '2024,2023',
			serial_id: '12',
			subject_id: '3,5',
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

	it("n'écrit pas dans la requête un filtre que la page ne propose pas", () => {
		perimeterEnabled = false;
		const values = initialValues(FILTERS);
		values.checkbox.perimeter = ['yes'];
		const params = new URLSearchParams();
		appendFilterParams(FILTERS, values, params);
		expect(params.has('in_perimeter')).toBe(false);
	});

	it("transmet à une autre page la valeur fixée comme une sélection, et la forme d'URL explicite", () => {
		fixedLab = '7';
		const values = initialValues(FILTERS);
		values.checkbox.years = ['2024'];
		values.presence.sources = { hal: 'yes' };
		expect(Object.fromEntries(transferParams(FILTERS, values))).toEqual({
			year: '2024',
			doc_type: 'all',
			lab_id: '7',
			source_filter: 'hal_yes',
		});
	});

	it('écrit une sélection explicite, `all` pour une sélection vide', () => {
		const url = explicitSelectionUrl('all');
		expect(url.encode([])).toBe('all');
		expect(url.encode(['2023', '2024'])).toBe('2023,2024');
		expect(url.decode('all')).toEqual([]);
		expect(url.decode('2023,2024')).toEqual(['2023', '2024']);
	});

	it('signale les filtres sélectionnés que la page ne propose pas', () => {
		const values = initialValues(FILTERS);
		values.checkbox.years = ['2024'];
		values.checkbox.perimeter = ['yes'];
		expect(ignoredFilters(FILTERS, values)).toEqual([]);
		perimeterEnabled = false;
		expect(ignoredFilters(FILTERS, values).map((f) => f.key)).toEqual(['perimeter']);
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
			['Revue et éditeur', ['serial']],
			['Sujets', ['subjects']],
		]);
	});

	it("écrit la sélection dans l'URL sous sa forme propre, et la relit", () => {
		const defs = urlFilterDefs(FILTERS);
		expect(defs.types).toEqual({ type: 'single', urlKey: 'doc_type', defaultValue: 'article' });
		expect(defs.years).toEqual({ type: 'string_array', urlKey: 'year' });
		expect(defs.serial).toEqual({ type: 'string_array', urlKey: 'serial_id' });
		expect(defs.sources).toEqual({ type: 'source_states', urlKey: 'source_filter' });

		const values = initialValues(FILTERS);
		expect(urlState(FILTERS, values).types).toBe('all');

		restoreValues(
			FILTERS,
			{ types: 'all', years: ['2024'], serial: ['12'], subjects: ['3', '5'], sources: { hal: 'no' } },
			values,
		);
		expect(values.checkbox.types).toEqual([]);
		expect(values.checkbox.years).toEqual(['2024']);
		expect(values.entity.serial).toEqual(['12']);
		expect(values.entity.subjects).toEqual(['3', '5']);
		expect(values.presence.sources).toEqual({ hal: 'no' });
	});

	it('vide la sélection de chaque type de filtre', () => {
		const values = initialValues(FILTERS);
		values.checkbox.years = ['2024'];
		values.entity.serial = ['12'];
		values.presence.sources = { hal: 'yes' };
		for (const f of FILTERS) clearValue(f, values);
		expect(values).toEqual(initialValues(FILTERS));
	});

	it('déclare les décomptes des seules cases à cocher', () => {
		expect(Object.keys(facetDefs(FILTERS))).toEqual(['years', 'types', 'labs', 'perimeter']);
	});

	it('renvoie les colonnes des filtres actifs proposés dans la page', () => {
		const values = initialValues(FILTERS);
		values.checkbox.types = ['article'];
		values.entity.serial = ['12'];
		values.checkbox.perimeter = ['yes'];
		perimeterEnabled = false;
		expect(activeColumns(FILTERS, values).sort()).toEqual(['serial', 'type']);
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
		expect(summarizeParts(['2024', '2023', '2022', '2021'])).toBe('2024, 2023 +2');
	});

	it('affiche « … » à la place de la valeur brute tant que les options chargent', () => {
		expect(checkboxSummary(types, ['article', 'book'], [])).toBe('Publications');
		expect(checkboxSummary(types, ['thesis'], [])).toBe('…');
		expect(checkboxSummary(types, ['inconnu'], [{ value: 'article', text: 'Articles' }])).toBe('inconnu');
	});

	it('résume un filtre de présence', () => {
		expect(presenceSummary(sources, { hal: 'yes', wos: 'no', oa: 'all' })).toBe('avec HAL, sans WoS');
	});
});
