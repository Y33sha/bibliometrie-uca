<script lang="ts">
	// État d'une page d'entité tant que l'entité est absente : chargement en cours, ou entité introuvable après un échec.
	let {
		error,
		notFound,
	}: {
		/** Le chargement de l'entité a échoué. */
		error: boolean;
		/** Message de l'entité introuvable, par exemple « Éditeur introuvable ». */
		notFound: string;
	} = $props();
</script>

{#if error}
	<div class="no-results">{notFound}</div>
{:else}
	<div class="loading">Chargement…</div>
{/if}
