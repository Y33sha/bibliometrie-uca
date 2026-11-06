import { describe, it, expect, beforeEach } from 'vitest';

import {
	activeColumns,
	activeCount,
	appendFilterParams,
	checkboxSummary,
	clearValue,
	coreRange,
	encodePresence,
	facetDefs,
	filterGroups,
	initialValues,
	isShown,
	presenceSummary,
	rangeBounds,
	rangeSelection,
	restoreValues,
	summarizeParts,
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
	group: 'publication',
	facet: { type: 'simple', apiKey: 'years' },
};
const types: CheckboxFilter = {
	key: 'types',
	control: 'checkbox',
	label: 'Types',
	param: 'doc_type',
	group: 'publication',
	facet: { type: 'simple', apiKey: 'doc_types' },
	groups: [{ label: 'Publications', values: ['article', 'book'] }],
	showColumns: ['type'],
};
const labs: CheckboxFilter = {
	key: 'labs',
	control: 'checkbox',
	label: 'Laboratoires',
	param: 'lab_id',
	group: 'affiliations',
	facet: { type: 'labeled', apiKey: 'labs' },
	fixed: () => fixedLab,
};
const perimeter: CheckboxFilter = {
	key: 'perimeter',
	control: 'checkbox',
	label: 'Périmètre',
	param: 'in_perimeter',
	facet: { type: 'labeled', apiKey: 'in_perimeter' },
	group: 'authors',
	enabled: () => perimeterEnabled,
	showColumns: ['corr'],
};
const serial: EntityChoiceFilter = {
	key: 'serial',
	control: 'entity',
	label: 'Revue',
	param: 'serial_id',
	entity: 'serial',
	group: 'venue',
	showColumns: ['serial'],
};
const subjects: EntityChoiceFilter = {
	key: 'subjects',
	control: 'entity',
	label: 'Sujets',
	param: 'subject',
	entity: 'subject',
	multiple: true,
	group: 'content',
};
const sources: PresenceFilter = {
	key: 'sources',
	control: 'presence',
	label: 'Sources',
	param: 'source_filter',
	group: 'sources',
	items: [
		{ key: 'hal', label: 'HAL' },
		{ key: 'wos', label: 'WoS' },
		{ key: 'openalex', label: 'OpenAlex' },
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
		values.entity.subjects = ['chimie', 'physique'];
		values.presence.sources = { hal: 'yes', wos: 'no', oa: 'all' };
		const params = new URLSearchParams();
		appendFilterParams(FILTERS, values, params);
		expect(Object.fromEntries(params)).toEqual({
			year: '2024,2023',
			serial_id: '12',
			subject: 'chimie,physique',
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
		expect(isShown(labs, values, () => 1, {})).toBe(false);
	});

	it("n'écrit pas dans la requête un filtre que la page ne propose pas", () => {
		perimeterEnabled = false;
		const values = initialValues(FILTERS);
		values.checkbox.perimeter = ['yes'];
		const params = new URLSearchParams();
		appendFilterParams(FILTERS, values, params);
		expect(params.has('in_perimeter')).toBe(false);
	});

	it('masque un filtre que la page ne propose pas, ou sans option de décompte non nul, sauf actif', () => {
		const values = initialValues(FILTERS);
		expect(isShown(perimeter, values, () => 0, {})).toBe(false);
		expect(isShown(perimeter, values, () => 2, {})).toBe(true);
		values.checkbox.perimeter = ['yes'];
		expect(isShown(perimeter, values, () => 0, {})).toBe(true);
		perimeterEnabled = false;
		expect(isShown(perimeter, values, () => 2, {})).toBe(false);
	});

	it('masque un filtre de présence dont aucun élément ne départage les publications', () => {
		const values = initialValues(FILTERS);
		const none = { hal: { yes: 10, no: 0 }, wos: { yes: 0, no: 10 }, openalex: { yes: 10, no: 0 } };
		expect(isShown(sources, values, () => 0, none)).toBe(false);
		expect(isShown(sources, values, () => 0, { ...none, wos: { yes: 3, no: 7 } })).toBe(true);
		values.presence.sources = { hal: 'yes' };
		expect(isShown(sources, values, () => 0, none)).toBe(true);
	});

	it('borne la plage aux valeurs qui concentrent les décomptes', () => {
		const counts: [number, number][] = [[1976, 1], [2000, 5], [2016, 100], [2017, 7000], [2018, 7000], [2026, 5800], [2027, 50]];
		expect(coreRange(counts)).toEqual([2017, 2026]);
		expect(coreRange([[2020, 3]])).toEqual([2020, 2020]);
		expect(coreRange([[2020, 1], [2021, 1]])).toEqual([2020, 2021]);
	});

	it('résume un intervalle par ses bornes', () => {
		const range: CheckboxFilter = { ...years, range: true };
		expect(checkboxSummary(range, ['2023', '2021', '2022'], [])).toBe('2021–2023');
		expect(checkboxSummary(range, ['2024'], [])).toBe('2024');
		const options = ['1990', '2021', '2022', '2023', '2024'].map((v) => ({ value: v, text: v, count: 5 }));
		expect(checkboxSummary(range, rangeSelection(1990, 2022), options)).toBe("Jusqu'à 2022");
		expect(checkboxSummary(range, ['2022', '2023', '2024'], options)).toBe('Depuis 2022');
		expect(checkboxSummary(range, ['2022', '2023'], options)).toBe('2022–2023');
		expect(rangeBounds(['2021', '2023'])).toBeNull();
		expect(rangeSelection(2021, 2023)).toEqual(['2021', '2022', '2023']);
	});

	it("range les filtres par rubrique, dans l'ordre des rubriques, sans rubrique vide", () => {
		const groups = [
			{ key: 'publication', label: 'Publication' },
			{ key: 'access', label: 'Accès' },
			{ key: 'affiliations', label: 'Affiliations' },
			{ key: 'venue', label: 'Revue et éditeur' },
			{ key: 'authors', label: 'Auteurs' },
			{ key: 'content', label: 'Sujets' },
			{ key: 'sources', label: 'Sources' },
		];
		expect(filterGroups(FILTERS, groups).map((g) => [g.group.key, g.filters.map((f) => f.key)])).toEqual([
			['publication', ['years', 'types']],
			['affiliations', ['labs']],
			['venue', ['serial']],
			['authors', ['perimeter']],
			['content', ['subjects']],
			['sources', ['sources']],
		]);
	});

	it("refuse un filtre dont la rubrique n'est pas déclarée", () => {
		expect(() => filterGroups(FILTERS, [{ key: 'publication', label: 'Publication' }])).toThrow(/labs/);
	});

	it('compte les filtres actifs proposés dans la page', () => {
		const values = initialValues(FILTERS);
		values.checkbox.years = ['2024'];
		values.presence.sources = { hal: 'all' };
		values.checkbox.perimeter = ['yes'];
		expect(activeCount(FILTERS, values)).toBe(2);
		perimeterEnabled = false;
		expect(activeCount(FILTERS, values)).toBe(1);
	});

	it("écrit la sélection dans l'URL, et la relit", () => {
		const defs = urlFilterDefs(FILTERS);
		expect(defs.types).toEqual({ type: 'string_array', urlKey: 'doc_type' });
		expect(defs.years).toEqual({ type: 'string_array', urlKey: 'year' });
		expect(defs.serial).toEqual({ type: 'string_array', urlKey: 'serial_id' });
		expect(defs.sources).toEqual({ type: 'source_states', urlKey: 'source_filter' });

		const values = initialValues(FILTERS);
		values.checkbox.types = ['article'];
		expect(urlState(FILTERS, values).types).toEqual(['article']);

		restoreValues(
			FILTERS,
			{ types: ['book'], years: ['2024'], serial: ['12'], subjects: ['3', '5'], sources: { hal: 'no' } },
			values,
		);
		expect(values.checkbox.types).toEqual(['book']);
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

	describe('sélection par défaut', () => {
		const rh: CheckboxFilter = {
			key: 'rh',
			control: 'checkbox',
			label: 'Base RH',
			param: 'has_rh',
			group: 'people',
			facet: { type: 'boolean', apiKey: 'rh', yesLabel: 'Oui', noLabel: 'Non' },
			defaultSelection: () => ['yes'],
			serialize: (selected) => (selected.length === 1 ? selected[0] : null),
		};

		it("part de la sélection par défaut, que l'URL omet, et écrit `all` une sélection vidée", () => {
			const values = initialValues([rh]);
			expect(values.checkbox.rh).toEqual(['yes']);
			expect(urlFilterDefs([rh]).rh).toEqual({ type: 'single', urlKey: 'has_rh', defaultValue: 'yes' });
			expect(urlState([rh], values).rh).toBe('yes');
			values.checkbox.rh = [];
			expect(urlState([rh], values).rh).toBe('all');
			restoreValues([rh], { rh: 'all' }, values);
			expect(values.checkbox.rh).toEqual([]);
			restoreValues([rh], { rh: 'no' }, values);
			expect(values.checkbox.rh).toEqual(['no']);
		});

		it('écrit dans la requête la valeur choisie par `serialize`', () => {
			const values = initialValues([rh]);
			const params = new URLSearchParams();
			appendFilterParams([rh], values, params);
			expect(params.get('has_rh')).toBe('yes');
			values.checkbox.rh = ['yes', 'no'];
			const both = new URLSearchParams();
			appendFilterParams([rh], values, both);
			expect(both.has('has_rh')).toBe(false);
		});
	});

	it('écrit un paramètre par élément filtré pour un filtre de présence à `itemParams`', () => {
		const ids: PresenceFilter = {
			key: 'ids',
			control: 'presence',
			label: 'Identifiants',
			param: 'id_filter',
			group: 'people',
			items: [
				{ key: 'orcid', label: 'ORCID' },
				{ key: 'idhal', label: 'idHAL' },
			],
			itemParams: { orcid: 'has_orcid', idhal: 'has_idhal' },
		};
		const values = initialValues([ids]);
		values.presence.ids = { orcid: 'yes', idhal: 'no' };
		const params = new URLSearchParams();
		appendFilterParams([ids], values, params);
		expect(Object.fromEntries(params)).toEqual({ has_orcid: 'yes', has_idhal: 'no' });
	});
});
