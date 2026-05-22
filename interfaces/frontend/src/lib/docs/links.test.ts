import { describe, it, expect } from 'vitest';
import { resolveDocLink } from './links';

const BASE = '/bibliometrie';

describe('resolveDocLink', () => {
	it('préfixe un slug nu par /docs/', () => {
		expect(resolveDocLink('pipeline', BASE)).toBe('/bibliometrie/docs/pipeline');
	});

	it('conserve une ancre interne au slug', () => {
		expect(resolveDocLink('glossaire#ror', BASE)).toBe('/bibliometrie/docs/glossaire#ror');
	});

	it('strippe une extension .md finale', () => {
		expect(resolveDocLink('pipeline.md', BASE)).toBe('/bibliometrie/docs/pipeline');
	});

	it('strippe .md devant une ancre', () => {
		expect(resolveDocLink('pipeline.md#section', BASE)).toBe(
			'/bibliometrie/docs/pipeline#section'
		);
	});

	it('laisse les URLs externes inchangées', () => {
		expect(resolveDocLink('https://ror.org/01a8ajp46', BASE)).toBe('https://ror.org/01a8ajp46');
		expect(resolveDocLink('http://example.com', BASE)).toBe('http://example.com');
	});

	it('laisse les liens absolus inchangés', () => {
		expect(resolveDocLink('/some/path', BASE)).toBe('/some/path');
	});

	it('laisse les ancres pures inchangées', () => {
		expect(resolveDocLink('#persons', BASE)).toBe('#persons');
	});

	it('laisse les mailto: inchangés', () => {
		expect(resolveDocLink('mailto:foo@bar', BASE)).toBe('mailto:foo@bar');
	});

	it('préfixe les chemins relatifs vers chantiers/ (cassé aujourd\'hui, statu quo)', () => {
		// Comportement intentionnel : voir audit syntaxe markdown phase 2.
		expect(resolveDocLink('chantiers/DATA_raw-data-store.md', BASE)).toBe(
			'/bibliometrie/docs/chantiers/DATA_raw-data-store'
		);
	});
});
