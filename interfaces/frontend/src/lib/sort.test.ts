import { describe, expect, it } from 'vitest';
import { nextSort, sortDirection } from './sort';

describe('nextSort', () => {
	it('part du sens initial sur une autre colonne', () => {
		expect(nextSort('name_asc', 'publications', 'desc')).toBe('publications_desc');
		expect(nextSort('publications_desc', 'name', 'asc')).toBe('name_asc');
	});

	it('inverse le sens sur la colonne déjà triée', () => {
		expect(nextSort('publications_desc', 'publications', 'desc')).toBe('publications_asc');
		expect(nextSort('publications_asc', 'publications', 'desc')).toBe('publications_desc');
	});

	// Régression : le clic sur un en-tête envoyait la colonne sans sens (`sort=serials`), que l'API refuse.
	it('rend toujours une clé suffixée du sens', () => {
		expect(nextSort('serials', 'serials', 'desc')).toBe('serials_desc');
	});

	it('distingue une colonne dont le nom prolonge une autre', () => {
		expect(nextSort('title_asc', 'title_original', 'asc')).toBe('title_original_asc');
	});
});

describe('sortDirection', () => {
	it('lit le sens de la colonne triée', () => {
		expect(sortDirection('year_desc', 'year')).toBe('desc');
		expect(sortDirection('year_asc', 'year')).toBe('asc');
	});

	it('rend null pour une autre colonne', () => {
		expect(sortDirection('year_desc', 'title')).toBeNull();
	});
});
