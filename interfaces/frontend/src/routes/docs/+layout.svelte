<script lang="ts">
	import { page } from "$app/stores";
	import { base } from "$app/paths";
	import { onMount } from "svelte";
	import { api } from "$lib/api";
	import type { Snippet } from "svelte";

	let { children }: { children: Snippet } = $props();

	interface DocPage {
		slug: string;
		title: string;
	}
	interface Heading {
		text: string;
		anchor: string;
	}

	let pages: DocPage[] = $state([]);
	let headings: Heading[] = $state([]);

	const currentSlug = $derived(
		$page.url.pathname.replace(`${base}/docs/`, "").replace(/\/$/, "") || ""
	);

	onMount(async () => {
		pages = await api<DocPage[]>("/api/docs");
	});

	// Extraire les h2 du DOM après chaque navigation
	function extractHeadings() {
		const container = document.querySelector(".doc-content");
		if (!container) return;
		const h2s = container.querySelectorAll("h2");
		headings = Array.from(h2s).map((h) => ({
			text: h.textContent || "",
			anchor: h.id,
		})).filter((h) => h.anchor);
	}

	// Observer les changements dans le contenu pour extraire les headings
	onMount(() => {
		const container = document.querySelector(".doc-content");
		if (!container) return;
		const observer = new MutationObserver(() => extractHeadings());
		observer.observe(container, { childList: true, subtree: true });
		return () => observer.disconnect();
	});
</script>

<div class="docs-layout">
	<aside class="docs-sidebar">
		<h3>Documentation</h3>
		<ul>
			{#each pages as p}
				<li>
					<a href="{base}/docs/{p.slug}" class:active={currentSlug === p.slug}>
						{p.title}
					</a>
					{#if currentSlug === p.slug && headings.length > 0}
						<ul class="toc">
							{#each headings as h}
								<li>
									<a href="#{h.anchor}">{h.text}</a>
								</li>
							{/each}
						</ul>
					{/if}
				</li>
			{/each}
			<li class="sidebar-separator"></li>
			<li>
				<a href="{base}/docs/todos" class:active={currentSlug === "todos"}>
					TODOs
				</a>
			</li>
		</ul>
	</aside>
	<main class="doc-content">
		{@render children()}
	</main>
</div>

<style>
	.docs-layout {
		display: flex;
		gap: 32px;
		min-height: calc(100vh - 94px);
	}
	.docs-sidebar {
		width: 240px;
		flex-shrink: 0;
		border-right: 1px solid var(--border);
		padding-right: 24px;
		position: sticky;
		top: 70px;
		align-self: flex-start;
		max-height: calc(100vh - 94px);
		overflow-y: auto;
	}
	.docs-sidebar h3 {
		font-size: 0.85rem;
		text-transform: uppercase;
		letter-spacing: 1px;
		color: var(--muted);
		margin: 0 0 12px;
	}
	.docs-sidebar ul {
		list-style: none;
		padding: 0;
		margin: 0;
	}
	.docs-sidebar li {
		margin: 0;
	}
	.docs-sidebar > ul > li > a {
		display: block;
		padding: 6px 10px;
		color: var(--text);
		text-decoration: none;
		font-size: 0.9rem;
		border-radius: 4px;
	}
	.docs-sidebar > ul > li > a:hover {
		background: #f0efec;
	}
	.docs-sidebar > ul > li > a.active {
		background: var(--accent);
		color: white;
	}
	.sidebar-separator {
		border-top: 1px solid var(--border);
		margin: 8px 0;
	}
	.toc {
		padding-left: 0;
		margin: 2px 0 4px;
	}
	.toc li {
		margin: 0;
	}
	.toc li a {
		display: block;
		padding: 2px 10px 2px 16px;
		color: var(--muted);
		text-decoration: none;
		font-size: 0.8rem;
		line-height: 1.6;
	}
	.toc li a:hover {
		color: var(--accent);
	}
</style>
