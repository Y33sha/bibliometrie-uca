<script lang="ts">
	import { renderMermaidBlocks } from '$lib/docs/mermaid';
	import { tick } from 'svelte';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();

	let bodyEl: HTMLElement;

	$effect(() => {
		// Re-run à chaque changement de slug : le @html change, on relance mermaid
		void data.html;
		(async () => {
			await tick();
			if (bodyEl) await renderMermaidBlocks(bodyEl);
			// Scroll vers l'ancre si présente
			const hash = window.location.hash;
			if (hash) {
				const el = document.getElementById(hash.slice(1));
				if (el) el.scrollIntoView();
			}
		})();
	});
</script>

<svelte:head>
	<title>{data.title || 'Documentation'} — Bibliométrie UCA</title>
</svelte:head>

<div class="doc-body" bind:this={bodyEl}>
	{@html data.html}
</div>

<style>
	.doc-body {
		max-width: 900px;
	}
	.doc-body :global(h1) {
		font-size: 1.5rem;
		font-weight: 600;
		margin: 0 0 16px;
		padding-bottom: 8px;
		border-bottom: 1px solid var(--border);
	}
	.doc-body :global(h2) {
		font-size: 1.2rem;
		font-weight: 600;
		margin: 32px 0 12px;
		scroll-margin-top: 80px;
	}
	.doc-body :global(h3) {
		font-size: 1.05rem;
		font-weight: 600;
		margin: 24px 0 8px;
		scroll-margin-top: 80px;
	}
	.doc-body :global(p) {
		margin: 0 0 12px;
		line-height: 1.65;
	}
	.doc-body :global(pre) {
		background: #f5f4f0;
		padding: 14px 18px;
		border-radius: 6px;
		overflow-x: auto;
		font-size: 0.85rem;
		line-height: 1.5;
		margin: 0 0 16px;
	}
	.doc-body :global(code) {
		font-family: 'JetBrains Mono', 'Fira Code', monospace;
		font-size: 0.85em;
	}
	.doc-body :global(:not(pre) > code) {
		background: var(--border-subtle);
		padding: 2px 5px;
		border-radius: 3px;
	}
	.doc-body :global(table) {
		width: 100%;
		border-collapse: collapse;
		margin: 0 0 16px;
		font-size: 0.9rem;
	}
	.doc-body :global(th) {
		text-align: left;
		padding: 8px 12px;
		border-bottom: 2px solid var(--border);
		font-weight: 600;
	}
	.doc-body :global(td) {
		padding: 8px 12px;
		border-bottom: 1px solid var(--border-subtle);
	}
	.doc-body :global(ul),
	.doc-body :global(ol) {
		margin: 0 0 12px;
		padding-left: 24px;
	}
	.doc-body :global(li) {
		margin: 4px 0;
		line-height: 1.5;
	}
	.doc-body :global(blockquote) {
		border-left: 3px solid var(--accent);
		margin: 0 0 16px;
		padding: 8px 16px;
		background: #f5f9fc;
		border-radius: 0 4px 4px 0;
	}
	.doc-body :global(hr) {
		border: none;
		border-top: 1px solid var(--border);
		margin: 24px 0;
	}
	.doc-body :global(.mermaid) {
		margin: 16px 0;
		text-align: center;
	}
	.doc-body :global(.mermaid svg) {
		max-width: 100%;
	}
</style>
