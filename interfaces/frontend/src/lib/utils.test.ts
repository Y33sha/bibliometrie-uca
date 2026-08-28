// @vitest-environment jsdom
// DOMPurify exige un DOM, et pas n'importe lequel : sous happy-dom il reçoit un nom de balise
// vide pour chaque nœud et n'évalue donc aucune liste blanche — les assertions d'assainissement
// y passeraient sans rien vérifier. jsdom est l'environnement que DOMPurify prend en charge.
import { describe, it, expect } from 'vitest';
import {
	sanitizeAbstract,
	sanitizeTitle,
	titleCase,
	formatDate,
	halDocUrl,
	scanrPubUrl,
	deriveStructDetectionStatus,
	paramsToQuery
} from './utils';

// ── paramsToQuery ──────────────────────────────────────────────

describe('paramsToQuery', () => {
	it('restaure les virgules littérales dans les valeurs de liste', () => {
		const p = new URLSearchParams();
		p.set('year', '2024,2023');
		expect(paramsToQuery(p)).toBe('year=2024,2023');
	});

	it('laisse les autres caractères percent-encodés intacts', () => {
		const p = new URLSearchParams();
		p.set('q', 'a b&c');
		expect(paramsToQuery(p)).toBe('q=a+b%26c');
	});

	it('retourne une chaîne vide sans paramètre', () => {
		expect(paramsToQuery(new URLSearchParams())).toBe('');
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

	it('décode le markup simple-encodé (&lt;sub&gt; → <sub>)', () => {
		const result = sanitizeTitle('Fe&lt;sub&gt;3&lt;/sub&gt;O&lt;sub&gt;4&lt;/sub&gt;');
		expect(result).toContain('<sub>3</sub>');
		expect(result).not.toContain('&lt;');
		expect(result).not.toContain('&amp;');
	});

	it('décode un &amp; de contenu isolé (&amp; → &)', () => {
		// "Smith &amp; Jones" → "Smith & Jones", ré-échappé une fois à l'affichage.
		const result = sanitizeTitle('Smith &amp; Jones');
		expect(result).toBe('Smith &amp; Jones');
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

// ── sanitizeAbstract ───────────────────────────────────────────
describe('sanitizeAbstract', () => {
	it('garde les paragraphes que les sources déposent dans un résumé', () => {
		const result = sanitizeAbstract('<p>Premier.</p><p>Second.</p>');
		expect(result).toContain('<p>');
		expect(result).toContain('Premier.');
		expect(result).toContain('Second.');
	});

	it('garde les sauts de ligne', () => {
		expect(sanitizeAbstract('Avant<br>Après')).toContain('<br>');
	});

	it('retire les balises hors liste blanche en gardant leur texte', () => {
		const result = sanitizeAbstract('<div onclick="x()">Texte</div>');
		expect(result).toContain('Texte');
		expect(result).not.toContain('onclick');
		expect(result).not.toContain('<div');
	});

	it('rend le MathML comme un titre', () => {
		expect(sanitizeAbstract('Soit <math><mi>x</mi></math> le seuil')).toContain('<math>');
	});

	it('échappe une injection', () => {
		expect(sanitizeAbstract('<img src=x onerror=alert(1)>')).not.toContain('onerror');
	});
});

// ── heuristique LaTeX : un montant en dollars n'est pas une formule ──
describe('détection des segments LaTeX', () => {
	it('rend en maths un segment qui porte une commande LaTeX', () => {
		expect(sanitizeTitle('Mesure de $\\sqrt{s}=13$ TeV')).toContain('katex');
	});

	it('rend en maths un segment court sans commande', () => {
		expect(sanitizeTitle('Le boson $Z$ et le photon')).toContain('katex');
	});

	it('laisse la prose entre deux montants intacte', () => {
		// Deux dollars de monnaie encadrent de la prose : la passer à KaTeX la déformerait.
		const result = sanitizeAbstract(
			'Le coût atteint $39.43 for treatment. About 18% of patients paid $12 par acte.'
		);
		expect(result).not.toContain('katex');
		expect(result).toContain('for treatment');
		expect(result).toContain('$39.43');
	});

	it('garde les paragraphes quand la prose contient un montant', () => {
		const result = sanitizeAbstract('<p>Un budget de $5 million sur trois ans.</p>');
		expect(result).toContain('<p>');
		expect(result).toContain('$5 million');
	});
});
