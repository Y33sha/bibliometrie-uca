import { describe, it, expect, afterEach } from 'vitest';
import { institution, siteTitle } from './institution.svelte.js';

describe('siteTitle', () => {
	afterEach(() => {
		institution.name = '';
		institution.title = null;
	});

	it("compose le titre avec le nom de l'établissement", () => {
		institution.name = 'UCA';
		expect(siteTitle()).toBe('Bibliométrie UCA');
	});

	it('rend le titre configuré', () => {
		institution.name = 'UCA';
		institution.title = 'Observatoire des publications';
		expect(siteTitle()).toBe('Observatoire des publications');
	});
});
