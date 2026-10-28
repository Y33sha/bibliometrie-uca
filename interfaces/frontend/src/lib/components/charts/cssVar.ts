/**
 * Valeur d'une variable CSS de `shared.css` (police, taille), pour les bibliothèques de graphiques qui attendent une valeur résolue (un canvas ne sait pas interpréter `var(...)`). Renvoie une chaîne vide si la variable est absente.
 */
export function cssVar(name: string): string {
	return getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
}

let pixel: CanvasRenderingContext2D | null | undefined;

/**
 * Couleur opaque d'une variable CSS de `shared.css`, en `#rrggbb`, la seule écriture que lisent les calculs de contraste et de mélange (`contrast.ts`). Le navigateur résout l'écriture CSS, `oklch(...)` comprise, en peignant un pixel. Renvoie la valeur telle quelle hors navigateur, une chaîne vide si la variable est absente.
 */
export function cssColor(name: string): string {
	const value = cssVar(name);
	if (!value) return '';
	pixel ??= document.createElement('canvas').getContext('2d', { willReadFrequently: true });
	if (!pixel) return value;
	pixel.clearRect(0, 0, 1, 1);
	pixel.fillStyle = value;
	pixel.fillRect(0, 0, 1, 1);
	const [r, g, b] = pixel.getImageData(0, 0, 1, 1).data;
	return '#' + [r, g, b].map((c) => c.toString(16).padStart(2, '0')).join('');
}

/**
 * Taille en pixels d'un jeton de l'échelle typographique de `shared.css` (`xs`, `sm`, `md`…), pour les polices d'un canvas.
 */
export function fontSize(token: string): number {
	const rem = parseFloat(cssVar(`fs-${token}`));
	return rem * parseFloat(getComputedStyle(document.documentElement).fontSize);
}

/**
 * Couleur d'un statut open access, lue dans la variable CSS de même nom : une valeur de `oa_status` (`diamond`, `gold`, `hybrid`, `bronze`, `green`, `embargoed`, `closed`, `unknown`) ou la catégorie agrégée `open`. Renvoie `undefined` si la variable est absente : le graphique retombe alors sur sa palette.
 */
export function oaStatusColor(status: string | null | undefined): string | undefined {
	return cssColor(status || 'unknown') || undefined;
}
