<script lang="ts">
	import { page } from '$app/stores';
	import { base } from '$app/paths';
	import type { Snippet } from 'svelte';
	import type { LayoutData } from './$types';
	import GlossaryPopover from '$lib/docs/GlossaryPopover.svelte';

	let { data, children }: { data: LayoutData; children: Snippet } = $props();

	const currentSlug = $derived(
		$page.url.pathname.replace(`${base}/docs/`, '').replace(/\/$/, '') || ''
	);

	type TocEntry = { level: 2 | 3; html: string; anchor: string };
	const toc = $derived(($page.data.toc ?? []) as TocEntry[]);

	let activeAnchor = $state('');

	$effect(() => {
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
		<ul class="nav">
			{#each data.nav as node}
				{#if node.kind === 'page'}
					<li>
						<a href="{base}/docs/{node.slug}" class:active={currentSlug === node.slug}>
							{node.title}
						</a>
					</li>
				{:else}
					<li class="section">
						<span class="section-title">{node.title}</span>
						<ul>
							{#each node.children as child}
								<li>
									<a
										href="{base}/docs/{child.slug}"
										class:active={currentSlug === child.slug}
									>
										{child.title}
									</a>
								</li>
							{/each}
						</ul>
					</li>
				{/if}
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

<GlossaryPopover />

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
	/* Niveau 1 (FlatPage top-level + en-tête de Section) : plus gros, couleur accent, pas uppercase. */
	.docs-sidebar > ul > li:not(.section) > a,
	.docs-sidebar .section-title {
		font-size: 1rem;
		font-weight: 600;
		color: var(--accent);
		text-transform: none;
		letter-spacing: normal;
		padding: 8px 10px 6px;
	}
	.docs-sidebar .section-title {
		display: block;
	}
	/* Active sur un FlatPage top-level : la spécificité du sélecteur niveau 1
	   ci-dessus bat `.docs-sidebar a.active` ; il faut donc re-spécifier la
	   couleur blanche pour que le fond accent reste lisible. */
	.docs-sidebar > ul > li:not(.section) > a.active {
		color: white;
	}
	/* Trait de séparation entre items top-level. */
	.docs-sidebar > ul > li + li {
		border-top: 1px solid var(--border);
		margin-top: 6px;
		padding-top: 6px;
	}
	/* Children d'une Section : indentés, plus petits, couleur texte normale. */
	.docs-sidebar li.section > ul > li > a {
		padding-left: 22px;
		font-size: 0.88rem;
		color: var(--text);
		font-weight: 400;
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
	/* Liens vers le glossaire : underline en pointillé pour signaler le popover. */
	.doc-content :global(a[data-glossary]) {
		color: inherit;
		text-decoration: none;
		border-bottom: 1px dotted var(--accent);
		cursor: help;
	}
	.doc-content :global(a[data-glossary]:hover) {
		color: var(--accent);
	}
	@media (max-width: 1100px) {
		.docs-layout {
			grid-template-columns: 240px minmax(0, 1fr);
		}
		.docs-toc {
			display: none;
		}
	}
</style>
