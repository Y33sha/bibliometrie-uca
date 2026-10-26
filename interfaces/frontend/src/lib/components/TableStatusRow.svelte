<script lang="ts">
	import { emptyListStatus } from '#lib/listStatus.js';

	// Ligne d'état d'un tableau quand il n'a aucune donnée à afficher : erreur de chargement, chargement en cours ou message « vide ». Mutualise le libellé et le markup entre tous les tableaux paginés.
	let {
		loading = false,
		error = null,
		colspan,
		emptyText,
	}: {
		loading?: boolean;
		error?: string | null;
		colspan: number;
		emptyText: string;
	} = $props();

	const status = $derived(emptyListStatus(loading, error, emptyText));
</script>

<tr>
	<td {colspan} class={status.cls}>{status.text}</td>
</tr>
