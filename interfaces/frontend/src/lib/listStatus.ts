/** Message et classe CSS d'une liste sans élément : l'erreur de chargement, le chargement en cours, ou le texte propre à la liste vide. */
export function emptyListStatus(
	loading: boolean,
	error: string | null,
	emptyText: string,
): { text: string; cls: string } {
	if (error) return { text: error, cls: 'load-error' };
	if (loading) return { text: 'Chargement…', cls: 'loading' };
	return { text: emptyText, cls: 'no-results' };
}
