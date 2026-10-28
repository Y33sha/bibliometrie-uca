<script lang="ts">
	interface Props {
		page: number;
		pages: number;
		onchange: (page: number) => void;
	}

	let { page, pages, onchange }: Props = $props();

	const start = $derived(Math.max(1, page - 3));
	const end = $derived(Math.min(pages, page + 3));

	function range(s: number, e: number): number[] {
		const arr: number[] = [];
		for (let i = s; i <= e; i++) arr.push(i);
		return arr;
	}

	const visiblePages = $derived(range(start, end));
</script>

{#if pages > 1}
	<div class="pagination">
		<button disabled={page <= 1} onclick={() => onchange(page - 1)}>&larr;</button>

		{#if start > 1}
			<button onclick={() => onchange(1)}>1</button>
			{#if start > 2}<span>&hellip;</span>{/if}
		{/if}

		{#each visiblePages as p (p)}
			<button class:active={p === page} onclick={() => onchange(p)}>{p}</button>
		{/each}

		{#if end < pages}
			{#if end < pages - 1}<span>&hellip;</span>{/if}
			<button onclick={() => onchange(pages)}>{pages}</button>
		{/if}

		<button disabled={page >= pages} onclick={() => onchange(page + 1)}>&rarr;</button>
		<span class="page-info">Page {page}/{pages}</span>
	</div>
{/if}

<style>
	.pagination {
		display: flex;
		gap: 6px;
		justify-content: center;
		align-items: center;
		margin: 16px 0;
	}
	button {
		min-width: 34px;
		height: 34px;
		padding: 0 10px;
		border: none;
		border-radius: var(--radius);
		background: transparent;
		color: var(--text-secondary);
		cursor: pointer;
		font-size: var(--fs-md);
		font-family: inherit;
	}
	button:hover:not(:disabled):not(.active) {
		background: var(--hover);
	}
	button.active:hover {
		background: color-mix(in srgb, var(--accent) 85%, black);
	}
	button:disabled {
		opacity: 0.4;
		cursor: default;
	}
	button.active {
		background: var(--accent);
		color: white;
		font-weight: 600;
	}
	.page-info {
		font-size: var(--fs-md);
		color: var(--muted);
		margin-left: 8px;
	}
</style>
