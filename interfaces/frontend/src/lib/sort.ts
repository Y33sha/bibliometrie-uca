// Clés de tri des listes : `<colonne>_<sens>`, le vocabulaire des paramètres `sort` de l'API.

export type SortDirection = 'asc' | 'desc';

/** Clé de tri après un clic sur l'en-tête de `column` : le sens s'inverse sur la colonne déjà triée, une autre colonne part du sens `first`. */
export function nextSort<C extends string>(
	current: string,
	column: C,
	first: SortDirection,
): `${C}_${SortDirection}` {
	const direction = sortDirection(current, column);
	if (direction === null) return `${column}_${first}`;
	return `${column}_${direction === 'asc' ? 'desc' : 'asc'}`;
}

/** Sens du tri courant sur `column`, ou `null` quand la liste est triée sur une autre colonne. */
export function sortDirection(current: string, column: string): SortDirection | null {
	if (current === `${column}_asc`) return 'asc';
	if (current === `${column}_desc`) return 'desc';
	return null;
}
