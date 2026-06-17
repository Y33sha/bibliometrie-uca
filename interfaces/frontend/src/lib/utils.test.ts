import { describe, it, expect } from 'vitest';
import {
	esc,
	sanitizeTitle,
	titleCase,
	formatDate,
	halDocUrl,
	scanrPubUrl,
	sourceExternalUrl,
	deriveStructDetectionStatus
} from './utils';

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

	it('décode les titres double-encodés (&amp;lt;i&amp;gt; → <i>)', () => {
		const result = sanitizeTitle(
			'Detection of &amp;lt;i&amp;gt;Candida&amp;lt;/i&amp;gt; species'
		);
		expect(result).toContain('<i>Candida</i>');
		expect(result).not.toContain('&amp;');
	});

	it('décode les entités numériques double-encodées (&amp;#233; → é)', () => {
		const result = sanitizeTitle('Gagn&amp;#233; et al.');
		expect(result).toContain('Gagné');
	});

	it('ne décode pas un &amp; isolé légitime', () => {
		// "Smith & Jones" stocké comme "Smith &amp; Jones" (encodage simple)
		// ne doit PAS être décodé : le & affiché vient de l'échappement final.
		const result = sanitizeTitle('Smith &amp; Jones');
		expect(result).toBe('Smith &amp;amp; Jones');
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

// ── sourceExternalUrl ──────────────────────────────────────────

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

	it('construit une URL DOI pour CrossRef', () => {
		expect(sourceExternalUrl('crossref', '10.1111/jpm.70007')).toBe(
			'https://doi.org/10.1111/jpm.70007'
		);
	});

	it('retourne # pour une source inconnue', () => {
		expect(sourceExternalUrl('mystery', 'abc')).toBe('#');
	});
});

// ── deriveStructDetectionStatus ────────────────────────────────

describe('deriveStructDetectionStatus', () => {
	it('confirmed a la priorité absolue', () => {
		expect(deriveStructDetectionStatus(true, true)).toBe('confirmed');
		expect(deriveStructDetectionStatus(true, false)).toBe('confirmed');
	});

	it('rejected prime sur detected', () => {
		expect(deriveStructDetectionStatus(false, true)).toBe('rejected');
	});

	it('detected si is_confirmed est null et is_detected true', () => {
		expect(deriveStructDetectionStatus(null, true)).toBe('detected');
		expect(deriveStructDetectionStatus(undefined, true)).toBe('detected');
	});

	it('manual par défaut', () => {
		expect(deriveStructDetectionStatus(null, false)).toBe('manual');
		expect(deriveStructDetectionStatus(null, null)).toBe('manual');
		expect(deriveStructDetectionStatus(undefined, undefined)).toBe('manual');
	});
});
