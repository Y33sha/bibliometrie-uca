<script lang="ts">
	// Fil d'Ariane : position de la page dans l'arborescence du site. Les niveaux parents sont des liens, la page courante du texte.
	let {
		trail,
		current
	}: {
		trail: { label: string; href: string }[];
		/** Libellé de la page courante ; absent tant que ses données chargent. */
		current?: string | null;
	} = $props();
</script>

<nav class="breadcrumb" aria-label="Fil d'Ariane">
	<ol>
		{#each trail as step (step.href)}
			<li><a href={step.href}>{step.label}</a></li>
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
	ol {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		margin: 0;
		padding: 0;
		list-style: none;
		color: var(--text-secondary);
	}
	li {
		display: flex;
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
