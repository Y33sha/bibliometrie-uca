<script lang="ts">
	// Fil d'Ariane : position de la page dans l'arborescence du site. Les niveaux parents sont des liens, la page courante du texte.
	import { resolve } from '$app/paths';
	import type { PathnameWithSearchOrHash } from '$app/types';

	let {
		trail,
		current
	}: {
		/** Niveaux parents ; `path` est un chemin de l'application, relatif au préfixe de déploiement. `resolve` distribue son type d'argument sur chaque route et refuse donc une valeur typée par leur union : l'assertion du gabarit lève ce refus. */
		trail: { label: string; path: PathnameWithSearchOrHash }[];
		/** Libellé de la page courante ; absent tant que ses données chargent. */
		current?: string | null;
	} = $props();
</script>

<nav class="breadcrumb" aria-label="Fil d'Ariane">
	<ol>
		{#each trail as step (step.path)}
			<li><a href={resolve(...([step.path] as Parameters<typeof resolve>))}>{step.label}</a></li>
		{/each}
		{#if current}
			<li><span aria-current="page">{current}</span></li>
		{/if}
	</ol>
</nav>

<style>
	.breadcrumb {
		margin-bottom: 14px;
		font-size: 0.85rem;
	}
	/* Une seule ligne : les niveaux parents gardent leur largeur, la page courante se tronque. */
	ol {
		display: flex;
		align-items: baseline;
		margin: 0;
		padding: 0;
		list-style: none;
		color: var(--text-secondary);
	}
	li {
		display: flex;
		flex: none;
		white-space: nowrap;
	}
	li:last-child {
		flex: 0 1 auto;
		min-width: 0;
	}
	li + li::before {
		content: '›';
		margin: 0 8px;
		color: var(--muted);
	}
	a {
		color: var(--text-secondary);
	}
	a:hover {
		color: var(--accent);
	}
	span {
		max-width: 60ch;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
</style>
