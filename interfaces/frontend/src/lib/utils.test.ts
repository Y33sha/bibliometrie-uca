// @vitest-environment jsdom
// DOMPurify exige un DOM, et pas n'importe lequel : sous happy-dom il reçoit un nom de balise
// vide pour chaque nœud et n'évalue donc aucune liste blanche — les assertions d'assainissement
// y passeraient sans rien vérifier. jsdom est l'environnement que DOMPurify prend en charge.
import { describe, it, expect } from 'vitest';
import {
	sanitizeAbstract,
	sanitizeTitle,
	titleCase,
	titleText,
	formatDate,
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

	it('retire le gras et garde son texte', () => {
		expect(sanitizeTitle('Phys. Rev. D <b>108</b>, <i>E. coli</i>')).toBe('Phys. Rev. D 108, <i>E. coli</i>');
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

	it("garde les sauts de ligne d'un tableau dans une formule à commandes simples", () => {
		const result = sanitizeTitle('$$ \\begin{array}{l}a=1,\\\\ b=2\\end{array} $$');
		expect(result.match(/<mtr>/g)?.length).toBe(2);
	});

	it('affiche en bloc une formule détachée de plusieurs lignes, dans la phrase les autres', () => {
		expect(sanitizeTitle('$$ \\begin{array}{l}a=1,\\\\ b=2\\end{array} $$')).toContain('katex-display');
		expect(sanitizeTitle('Mesure de $$ D^+ \\to \\eta \\pi^+ $$ et suite')).not.toContain('katex-display');
	});

	it('retire le gras des formules LaTeX', () => {
		for (const tex of ['\\mathbf{\\sqrt{s}=13}', '\\varvec{pp}', '\\pmb{x}', '\\boldsymbol{x}', '\\textbf{892}', '{\\bf x}']) {
			const result = sanitizeTitle(`Mesure à $$${tex}$$ TeV`);
			expect(result).toContain('katex');
			expect(result.replace(/<annotation[\s\S]*?<\/annotation>/g, '')).not.toMatch(/mathbf|boldsymbol|bold"/);
		}
	});

	it('rend en lettre ajourée un ensemble de nombres en gras', () => {
		expect(sanitizeTitle('Sous-groupes de $$SL_2(\\mathbf {Z})$$')).toContain('<span class="mord mathbb">Z</span>');
	});

	it('rend les macros inconnues de KaTeX sans erreur', () => {
		for (const tex of ['\\varvec{p}', '\\uppi^+', '\\Upgamma', '\\C_p']) {
			expect(sanitizeTitle(`$${tex}$`)).not.toContain('katex-error');
		}
		expect(titleText('Désintégration $J/\\uppsi$')).toBe('Désintégration J/ψ');
	});

	it('retire le gras du MathML', () => {
		const result = sanitizeTitle(
			'<mml:math><mml:mi mathvariant="bold">x</mml:mi><mml:mtext mathvariant="bold-italic">s</mml:mtext></mml:math>'
		);
		expect(result).toContain('<mi>x</mi>');
		expect(result).toContain('<mtext mathvariant="italic">s</mtext>');
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
describe('titleText', () => {
	it('renvoie le texte visible du MathML, sans balise', () => {
		expect(
			titleText('Measurement of <mml:math><mml:msup><mml:mi>W</mml:mi><mml:mo>+</mml:mo></mml:msup></mml:math> production')
		).toBe('Measurement of W+ production');
	});

	it('renvoie le texte visible du LaTeX, sans la source TeX ni la copie MathML de KaTeX', () => {
		const text = titleText('$\\Sigma^{\\pm}$ production in pp collisions');
		expect(text).toBe('Σ± production in pp collisions');
	});

	it('décode les entités et retire le formatage HTML', () => {
		expect(titleText('H&lt;sub&gt;2&lt;/sub&gt;O &amp; CO<sub>2</sub>')).toBe('H2O & CO2');
	});

	it('renvoie une chaîne vide pour un titre absent', () => {
		expect(titleText(null)).toBe('');
	});
});

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

	it('garde les intertitres en gras', () => {
		expect(sanitizeAbstract('<b>Background:</b> Texte')).toContain('<b>Background:</b>');
		expect(sanitizeAbstract('<strong>Methods:</strong> Texte')).toContain('<strong>Methods:</strong>');
	});

	it('retire les balises hors liste blanche en gardant leur texte', () => {
		const result = sanitizeAbstract('<div onclick="x()">Texte</div>');
		expect(result).toContain('Texte');
		expect(result).not.toContain('onclick');
		expect(result).not.toContain('<div');
	});

	it('rend les commandes LaTeX et MathJax inconnues de KaTeX', () => {
		for (const tex of [
			'\\mbox{ in } \\Omega',
			'L^p(\\ensuremath{\\mathbb{R}}^d)',
			'a \\hfill b',
			'1 \\textless{} p \\textgreater{} 0',
			'\\left\\arrowvert x \\right\\arrowvert',
			'{H \\mathord{\\left/ {\\vphantom {H B}} \\right. \\kern-\\nulldelimiterspace} B}',
			'\\begin{equation*} x^7 = z^n \\end{equation*}',
			'u = 0. \\tag{1}',
			'\\begin{eqnarray} a &=& b \\end{eqnarray}',
			'y^\\eps + \\pa \\Omega + (\\Cal T) + \\cE + \\dsp{f\\over g} + \\re s + \\Log r + \\conv(S) + \\diam'
		]) {
			expect(sanitizeAbstract(`Soit $${tex}$.`)).not.toMatch(/katex-error|cc0000/);
		}
	});

	it('remplace un caractère désigné par son code par sa lettre de base', () => {
		const text = titleText('Somme $S_{n,\\unicode[STIX]{x1D6FC}}$');
		expect(text).toContain('Sn,α');
		expect(text).not.toContain('unicode');
	});

	it('garde la branche mathématique d\'une condition TeX', () => {
		expect(titleText('Charge $\\ifmmode\\pm\\else\\textpm\\fi{}2$')).toBe('Charge ±2');
	});

	it('retire une étiquette d\'équation', () => {
		expect(titleText('Équation $\\label{1}x=1$')).toBe('Équation x=1');
	});

	it('garde le gras des formules', () => {
		expect(sanitizeAbstract('Le vecteur $\\mathbf{v}$')).toContain('mathbf');
		expect(sanitizeAbstract('Le vecteur $\\varvec{v}$')).not.toContain('katex-error');
		expect(sanitizeAbstract('<math><mi mathvariant="bold">v</mi></math>')).toContain('mathvariant="bold"');
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
