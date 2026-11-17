<script lang="ts">
	import { tooltip } from '#lib/actions/tooltip.svelte.js';
	import { asset } from '$app/paths';
	import { doiUrl } from '#lib/utils.js';

	// Lien vers la page du DOI : logo qui grossit au survol, ou DOI écrit en entier, en texte discret.
	let { doi, text = false }: { doi: string; text?: boolean } = $props();
</script>

{#if text}
	<a href={doiUrl(doi)} target="_blank" rel="noopener" class="doi-text">{doi}</a>
{:else}
	<a href={doiUrl(doi)} target="_blank" rel="noopener" class="doi-link" use:tooltip={doi}>
		<img src={asset('icons/doi.svg')} alt="DOI" />
	</a>
{/if}

<style>
	.doi-link {
		display: inline-block;
		vertical-align: middle;
		transition: transform 0.1s;
	}
	.doi-link:hover {
		transform: scale(1.15);
	}
	.doi-link img {
		display: block;
		width: 20px;
		height: 20px;
	}
	.doi-text {
		color: var(--muted);
		text-decoration: none;
		overflow-wrap: anywhere;
	}
	.doi-text:hover {
		color: var(--accent);
		text-decoration: underline;
	}
</style>
