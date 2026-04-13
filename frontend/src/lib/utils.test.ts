import { describe, it, expect } from 'vitest';
import { esc, sanitizeTitle, titleCase, formatDate, halDocUrl, scanrPubUrl } from './utils';

// ── esc (HTML escaping) ────────────────────────────────────────
// esc() utilise document.createElement, non testable sans DOM.
// Seul le cas null/undefined est testé ici.

describe('esc', () => {
	it('retourne une chaîne vide pour null/undefined', () => {
		expect(esc(null)).toBe('');
		expect(esc(undefined)).toBe('');
	});
});

// ── sanitizeTitle ──────────────────────────────────────────────

describe('sanitizeTitle', () => {
	it('échappe le HTML dans un titre simple', () => {
		expect(sanitizeTitle('Hello <b>World</b>')).toContain('World');
	});

	it('rend le LaTeX inline', () => {
		const result = sanitizeTitle('Energy $E=mc^2$ formula');
		expect(result).toContain('katex');
	});

	it('normalise les doubles backslashes dans le LaTeX', () => {
		const result = sanitizeTitle('$\\\\rm{K}^{*}$');
		// Doit rendre via KaTeX sans erreur (pas de texte brut \\rm)
		expect(result).toContain('katex');
		expect(result).not.toContain('\\\\rm');
	});

	it('gère le MathML avec préfixe mml:', () => {
		const result = sanitizeTitle('Test <mml:math><mml:mi>x</mml:mi></mml:math>');
		// Le préfixe mml: doit être supprimé pour le rendu natif
		expect(result).toContain('<math>');
		expect(result).not.toContain('mml:');
	});

	it('retourne une chaîne vide pour null', () => {
		expect(sanitizeTitle(null)).toBe('');
		expect(sanitizeTitle(undefined)).toBe('');
	});
});

// ── titleCase ──────────────────────────────────────────────────

describe('titleCase', () => {
	it('met en majuscule la première lettre de chaque mot', () => {
		expect(titleCase('hello world')).toBe('Hello World');
	});

	it('retourne une chaîne vide pour null', () => {
		expect(titleCase(null)).toBe('');
	});
});

// ── formatDate ─────────────────────────────────────────────────

describe('formatDate', () => {
	it('formate une date ISO en JJ/MM/AAAA', () => {
		expect(formatDate('2024-03-15')).toBe('15/03/2024');
	});

	it('retourne la chaîne telle quelle si format inconnu', () => {
		expect(formatDate('15 mars 2024')).toBe('15 mars 2024');
	});

	it('retourne une chaîne vide pour null', () => {
		expect(formatDate(null)).toBe('');
	});
});

// ── halDocUrl ──────────────────────────────────────────────────

describe('halDocUrl', () => {
	it('retourne hal.science pour un halid normal', () => {
		expect(halDocUrl('hal-04579115')).toBe('https://hal.science/hal-04579115');
	});

	it('retourne dumas pour un document dumas', () => {
		expect(halDocUrl('dumas-12345678')).toBe('https://dumas.ccsd.cnrs.fr/dumas-12345678');
	});

	it('retourne theses.hal.science pour tel-* non closed', () => {
		expect(halDocUrl('tel-04579115')).toBe('https://theses.hal.science/tel-04579115');
		expect(halDocUrl('tel-04579115', 'green')).toBe('https://theses.hal.science/tel-04579115');
		expect(halDocUrl('tel-04579115', null)).toBe('https://theses.hal.science/tel-04579115');
	});

	it('retourne hal.science pour tel-* closed', () => {
		expect(halDocUrl('tel-04579115', 'closed')).toBe('https://hal.science/tel-04579115');
	});
});

// ── scanrPubUrl ────────────────────────────────────────────────

describe('scanrPubUrl', () => {
	it('construit une URL ScanR correcte', () => {
		expect(scanrPubUrl('doi/10.1234/test')).toContain('scanr.enseignementsup-recherche.gouv.fr');
		expect(scanrPubUrl('doi/10.1234/test')).toContain(encodeURIComponent('doi/10.1234/test'));
	});
});
