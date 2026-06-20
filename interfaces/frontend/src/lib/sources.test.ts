import { describe, it, expect } from 'vitest';
import { sourceExternalUrl } from './sources';

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
