<script lang="ts">
	// Ligne d'état d'un tableau quand il n'a aucune donnée à afficher : message de
	// chargement tant que la requête est en vol, message « vide » une fois chargé.
	// Mutualise le libellé et le markup entre tous les tableaux paginés.
	let {
		loading = false,
		colspan,
		emptyText,
	}: {
		loading?: boolean;
		colspan: number;
		emptyText: string;
	} = $props();
</script>

<tr>
	<td {colspan} class={loading ? 'loading-msg' : 'no-results'}>
		{loading ? 'Chargement des résultats en cours…' : emptyText}
	</td>
</tr>
