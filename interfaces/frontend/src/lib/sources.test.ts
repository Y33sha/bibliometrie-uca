import { describe, it, expect } from 'vitest';
import { crossrefMemberIds, crossrefMemberUrl, sourceExternalUrl } from './sources';

describe('sourceExternalUrl', () => {
	it('délègue à halDocUrl pour HAL', () => {
		expect(sourceExternalUrl('hal', 'hal-04579115')).toBe('https://hal.science/hal-04579115');
	});

	it('construit une URL OpenAlex', () => {
		expect(sourceExternalUrl('openalex', 'W12345')).toBe('https://openalex.org/W12345');
	});

	it('construit une URL WoS', () => {
		expect(sourceExternalUrl('wos', 'WOS:000123')).toBe(
			'https://www.webofscience.com/wos/woscc/full-record/WOS:000123'
		);
	});

	it('construit une URL ScanR', () => {
		expect(sourceExternalUrl('scanr', 'hal123')).toBe(
			'https://scanr.enseignementsup-recherche.gouv.fr/publications/hal123'
		);
	});

	it('construit une URL theses.fr', () => {
		expect(sourceExternalUrl('theses', '2024UCFA0001')).toBe('https://theses.fr/2024UCFA0001');
	});

	it('construit une URL DOI pour Crossref', () => {
		expect(sourceExternalUrl('crossref', '10.1111/jpm.70007')).toBe(
			'https://doi.org/10.1111/jpm.70007'
		);
	});

	it('construit une URL DOI pour DataCite', () => {
		expect(sourceExternalUrl('datacite', '10.5281/zenodo.123')).toBe(
			'https://doi.org/10.5281/zenodo.123'
		);
	});

	it('retourne # pour une source inconnue', () => {
		expect(sourceExternalUrl('mystery', 'abc')).toBe('#');
	});
});

describe('membres Crossref', () => {
	it('construit le lien vers le rapport de participation', () => {
		expect(crossrefMemberUrl(297)).toBe('https://www.crossref.org/members/prep/297');
	});

	it('dédoublonne les membres des préfixes et ignore ceux qui en sont dépourvus', () => {
		const prefixes = [
			{ crossref_member_id: 297 },
			{ crossref_member_id: 297 },
			{ crossref_member_id: null },
			{ crossref_member_id: 93 }
		];
		expect(crossrefMemberIds(prefixes)).toEqual([297, 93]);
	});

	it('rend une liste vide quand aucun préfixe ne porte de membre', () => {
		expect(crossrefMemberIds([{ crossref_member_id: null }])).toEqual([]);
	});
});
