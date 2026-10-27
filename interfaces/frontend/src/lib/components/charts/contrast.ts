/** Composantes rouge, vert, bleu (0-255) d'une couleur `#rgb`, `#rrggbb` ou `rgb(r, g, b)`, `null` pour une autre écriture. */
function parseColor(color: string): [number, number, number] | null {
	const value = color.trim();
	const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(value);
	if (hex) {
		const digits = hex[1].length === 3 ? [...hex[1]].map((d) => d + d).join('') : hex[1];
		return [0, 2, 4].map((i) => parseInt(digits.slice(i, i + 2), 16)) as [number, number, number];
	}
	const rgb = /^rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)/i.exec(value);
	if (rgb) return [Number(rgb[1]), Number(rgb[2]), Number(rgb[3])];
	return null;
}

/** Luminance relative d'une couleur, au sens des WCAG. */
function luminance([r, g, b]: [number, number, number]): number {
	const channel = (c: number) => {
		const s = c / 255;
		return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
	};
	return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

/** Rapport de contraste WCAG entre deux couleurs, de 1 à 21. */
export function contrastRatio(a: string, b: string): number {
	const ca = parseColor(a);
	const cb = parseColor(b);
	if (!ca || !cb) return 1;
	const [hi, lo] = [luminance(ca), luminance(cb)].sort((x, y) => y - x);
	return (hi + 0.05) / (lo + 0.05);
}

/** Couleur de texte posée sur `background` : `light` ou `dark`, celle qui contraste le plus. */
export function readableOn(background: string, dark: string, light = '#ffffff'): string {
	return contrastRatio(background, light) >= contrastRatio(background, dark) ? light : dark;
}
