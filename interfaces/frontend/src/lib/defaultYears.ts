/** Années sélectionnées par défaut : les années présentes de `currentYear - 5` à `currentYear`. Les années postérieures (prépublications datées de l'année suivante) sont exclues. */
export function defaultYears(years: string[], currentYear: number): string[] {
	const first = String(currentYear - 5);
	const current = String(currentYear);
	return years.filter((y) => y >= first && y <= current).sort().reverse();
}
