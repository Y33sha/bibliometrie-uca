/** Accord en nombre : singulier pour 0 et 1, pluriel au-delà. Le pluriel vaut par défaut le singulier suivi de « s ». */
export function plural(count: number, singular: string, pluralForm = `${singular}s`): string {
	return count > 1 ? pluralForm : singular;
}

/** Nombre formaté à la française, suivi du mot accordé : « 1 publication », « 1 234 publications ». */
export function formatCount(count: number, singular: string, pluralForm?: string): string {
	return `${count.toLocaleString('fr-FR')} ${plural(count, singular, pluralForm)}`;
}
