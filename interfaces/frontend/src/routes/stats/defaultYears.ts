/** Années sélectionnées par défaut : les cinq dernières années présentes jusqu'à `currentYear`. Les années postérieures (prépublications datées de l'année suivante) sont exclues. */
export function defaultYears(years: string[], currentYear: number): string[] {
	const current = String(currentYear);
	return years.filter((y) => y <= current).sort().reverse().slice(0, 5);
}
