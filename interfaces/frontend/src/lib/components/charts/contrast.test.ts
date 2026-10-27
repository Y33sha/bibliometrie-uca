import { describe, expect, it } from 'vitest';
import { contrastRatio, readableOn } from './contrast';

const TEXT = '#1d2433';

describe('contrastRatio', () => {
	it('vaut 21 entre le noir et le blanc', () => {
		expect(contrastRatio('#000', '#ffffff')).toBeCloseTo(21);
	});

	it('lit les écritures rgb()', () => {
		expect(contrastRatio('rgb(0, 0, 0)', 'rgb(255 255 255)')).toBeCloseTo(21);
	});
});

describe('readableOn', () => {
	it('écrit en couleur de texte sur une part gris clair', () => {
		expect(readableOn('#e3e6ea', TEXT)).toBe(TEXT);
	});

	it('écrit en blanc sur une part teal foncée', () => {
		expect(readableOn('#2f8a8a', TEXT)).toBe('#ffffff');
	});
});
