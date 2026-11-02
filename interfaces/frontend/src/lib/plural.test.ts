import { describe, it, expect } from 'vitest';
import { formatCount, plural } from './plural';

describe('plural', () => {
	it('met le singulier pour 0 et 1', () => {
		expect(plural(0, 'publication')).toBe('publication');
		expect(plural(1, 'publication')).toBe('publication');
	});

	it('ajoute « s » au-delà de 1', () => {
		expect(plural(2, 'publication')).toBe('publications');
	});

	it('emploie le pluriel fourni', () => {
		expect(plural(2, 'thèse liée', 'thèses liées')).toBe('thèses liées');
	});
});

describe('formatCount', () => {
	it('formate le nombre à la française', () => {
		expect(formatCount(1234, 'publication')).toBe('1 234 publications');
	});
});
