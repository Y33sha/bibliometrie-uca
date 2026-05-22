<script lang="ts">
	import { page } from '$app/stores';
	import { base } from '$app/paths';
	import type { Snippet } from 'svelte';
	import type { LayoutData } from './$types';

	let { data, children }: { data: LayoutData; children: Snippet } = $props();

	const currentSlug = $derived(
		$page.url.pathname.replace(`${base}/docs/`, '').replace(/\/$/, '') || ''
	);

	type TocEntry = { level: 2 | 3; html: string; anchor: string };
	const toc = $derived(($page.data.toc ?? []) as TocEntry[]);

	let activeAnchor = $state('');

	$effect(() => {
		// Recalcule à chaque changement de slug
		void currentSlug;
		activeAnchor = '';
		const headings = document.querySelectorAll<HTMLElement>(
			'.doc-content h2[id], .doc-content h3[id]'
		);
		if (headings.length === 0) return;

		const observer = new IntersectionObserver(
			(entries) => {
				const visible = entries
					.filter((e) => e.isIntersecting)
					.sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
				if (visible.length > 0) {
					activeAnchor = visible[0].target.id;
				}
			},
			{ rootMargin: '-80px 0px -70% 0px', threshold: 0 }
		);
		headings.forEach((h) => observer.observe(h));
		return () => observer.disconnect();
	});
</script>

<div class="docs-layout">
	<aside class="docs-sidebar">
		<h3>Documentation</h3>
		<ul>
			{#each data.pages as p}
				<li>
					<a href="{base}/docs/{p.slug}" class:active={currentSlug === p.slug}>
						{p.title}
					</a>
				</li>
			{/each}
		</ul>
	</aside>

	<main class="doc-content">
		{@render children()}
	</main>

	<aside class="docs-toc" class:empty={toc.length === 0}>
		{#if toc.length > 0}
			<h4>Sur cette page</h4>
			<ul>
				{#each toc as h}
					<li class:level-3={h.level === 3}>
						<a href="#{h.anchor}" class:active={activeAnchor === h.anchor}>
							{@html h.html}
						</a>
					</li>
				{/each}
			</ul>
		{/if}
	</aside>
</div>

<style>
	.docs-layout {
		display: grid;
		grid-template-columns: 240px minmax(0, 1fr) 200px;
		gap: 32px;
		min-height: calc(100vh - 94px);
	}
	.docs-sidebar,
	.docs-toc {
		position: sticky;
		top: 70px;
		align-self: flex-start;
		max-height: calc(100vh - 94px);
		overflow-y: auto;
	}
	.docs-sidebar {
		border-right: 1px solid var(--border);
		padding-right: 24px;
	}
	.docs-sidebar h3 {
		font-size: 0.85rem;
		text-transform: uppercase;
		letter-spacing: 1px;
		color: var(--muted);
		margin: 0 0 12px;
	}
	.docs-sidebar ul,
	.docs-toc ul {
		list-style: none;
		padding: 0;
		margin: 0;
	}
	.docs-sidebar li,
	.docs-toc li {
		margin: 0;
	}
	.docs-sidebar a {
		display: block;
		padding: 6px 10px;
		color: var(--text);
		text-decoration: none;
		font-size: 0.9rem;
		border-radius: 4px;
	}
	.docs-sidebar a:hover {
		background: #f0efec;
	}
	.docs-sidebar a.active {
		background: var(--accent);
		color: white;
	}
	.docs-toc {
		border-left: 1px solid var(--border);
		padding-left: 16px;
	}
	.docs-toc h4 {
		font-size: 0.8rem;
		text-transform: uppercase;
		letter-spacing: 1px;
		color: var(--muted);
		margin: 0 0 8px;
		font-weight: 600;
	}
	.docs-toc a {
		display: block;
		padding: 3px 8px;
		color: var(--muted);
		text-decoration: none;
		font-size: 0.8rem;
		line-height: 1.5;
		border-left: 2px solid transparent;
	}
	.docs-toc li.level-3 a {
		padding-left: 18px;
		font-size: 0.78rem;
	}
	.docs-toc a:hover {
		color: var(--text);
	}
	.docs-toc a.active {
		color: var(--accent);
		border-left-color: var(--accent);
	}
	.docs-toc.empty {
		display: none;
	}
</style>
