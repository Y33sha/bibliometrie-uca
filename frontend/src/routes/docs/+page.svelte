<script lang="ts">
	import { onMount, tick } from "svelte";
	import { page } from "$app/stores";
	import { goto } from "$app/navigation";
	import { base } from "$app/paths";
	import { api } from "$lib/api";
	import { Marked } from "marked";
	import mermaid from "mermaid";

	interface DocPage {
		slug: string;
		title: string;
	}
	interface DocContent {
		slug: string;
		title: string;
		content: string;
	}

	let pages: DocPage[] = $state([]);
	let current: DocContent | null = $state(null);
	let renderedHtml = $state("");

	const marked = new Marked();

	// Slug courant depuis l'URL (?page=xxx) ou premier par défaut
	const currentSlug = $derived(
		$page.url.searchParams.get("page") || pages[0]?.slug || "architecture",
	);

	async function loadPage(slug: string) {
		current = await api<DocContent>(`/api/docs/${slug}`);
		renderedHtml = await marked.parse(current.content);

		// Rendre les blocs Mermaid après insertion dans le DOM
		await tick();
		const container = document.querySelector(".doc-content");
		if (container) {
			const mermaidBlocks = container.querySelectorAll(
				"pre code.language-mermaid",
			);
			for (const block of mermaidBlocks) {
				const pre = block.parentElement;
				if (!pre) continue;
				const div = document.createElement("div");
				div.className = "mermaid";
				div.textContent = block.textContent || "";
				pre.replaceWith(div);
			}
			await mermaid.run({ querySelector: ".doc-content .mermaid" });
		}
	}

	// Intercepter les clics sur les liens internes pour naviguer sans recharger
	function handleClick(e: MouseEvent) {
		const target = e.target as HTMLElement;
		const link = target.closest("a");
		if (!link) return;
		const href = link.getAttribute("href");
		if (!href) return;
		// Lien interne vers une autre page de doc (ex: "pipeline" ou "glossaire#terme")
		if (!href.startsWith("http") && !href.startsWith("/") && !href.startsWith("#")) {
			e.preventDefault();
			const [slug] = href.split("#");
			if (slug && pages.some((p) => p.slug === slug)) {
				const url = new URL(window.location.href);
				url.searchParams.set("page", slug);
				window.history.pushState({}, "", url);
				loadPage(slug);
			}
		}
	}

	onMount(async () => {
		mermaid.initialize({ startOnLoad: false, theme: "neutral" });
		pages = await api<DocPage[]>("/api/docs");
		await loadPage(currentSlug);
	});

	// Réagir aux changements de paramètre URL
	$effect(() => {
		if (pages.length > 0 && currentSlug !== current?.slug) {
			loadPage(currentSlug);
		}
	});
</script>

<svelte:head>
	<title>{current?.title || "Documentation"} — Bibliométrie UCA</title>
</svelte:head>

<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<div class="docs-layout" onclick={handleClick}>
	<aside class="docs-sidebar">
		<h3>Documentation</h3>
		<ul>
			{#each pages as p}
				<li>
					<a
						href="{base}/docs?page={p.slug}"
						class:active={currentSlug === p.slug}
						onclick={(e: MouseEvent) => {
							e.preventDefault();
							goto(`${base}/docs?page=${p.slug}`, { replaceState: false, noScroll: true });
						}}
					>
						{p.title}
					</a>
				</li>
			{/each}
		</ul>
	</aside>
	<main class="doc-content">
		{@html renderedHtml}
	</main>
</div>

<style>
	.docs-layout {
		display: flex;
		gap: 32px;
		min-height: calc(100vh - 94px);
	}
	.docs-sidebar {
		width: 220px;
		flex-shrink: 0;
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
	.docs-sidebar ul {
		list-style: none;
		padding: 0;
		margin: 0;
	}
	.docs-sidebar li {
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
	.doc-content {
		flex: 1;
		min-width: 0;
		max-width: 900px;
	}
	.doc-content :global(h1) {
		font-size: 1.5rem;
		font-weight: 600;
		margin: 0 0 16px;
		padding-bottom: 8px;
		border-bottom: 1px solid var(--border);
	}
	.doc-content :global(h2) {
		font-size: 1.2rem;
		font-weight: 600;
		margin: 32px 0 12px;
	}
	.doc-content :global(h3) {
		font-size: 1.05rem;
		font-weight: 600;
		margin: 24px 0 8px;
	}
	.doc-content :global(p) {
		margin: 0 0 12px;
		line-height: 1.65;
	}
	.doc-content :global(pre) {
		background: #f5f4f0;
		padding: 14px 18px;
		border-radius: 6px;
		overflow-x: auto;
		font-size: 0.85rem;
		line-height: 1.5;
		margin: 0 0 16px;
	}
	.doc-content :global(code) {
		font-family: "JetBrains Mono", "Fira Code", monospace;
		font-size: 0.85em;
	}
	.doc-content :global(:not(pre) > code) {
		background: #f0efec;
		padding: 2px 5px;
		border-radius: 3px;
	}
	.doc-content :global(table) {
		width: 100%;
		border-collapse: collapse;
		margin: 0 0 16px;
		font-size: 0.9rem;
	}
	.doc-content :global(th) {
		text-align: left;
		padding: 8px 12px;
		border-bottom: 2px solid var(--border);
		font-weight: 600;
	}
	.doc-content :global(td) {
		padding: 8px 12px;
		border-bottom: 1px solid #f0efec;
	}
	.doc-content :global(ul),
	.doc-content :global(ol) {
		margin: 0 0 12px;
		padding-left: 24px;
	}
	.doc-content :global(li) {
		margin: 4px 0;
		line-height: 1.5;
	}
	.doc-content :global(blockquote) {
		border-left: 3px solid var(--accent);
		margin: 0 0 16px;
		padding: 8px 16px;
		background: #f5f9fc;
		border-radius: 0 4px 4px 0;
	}
	.doc-content :global(hr) {
		border: none;
		border-top: 1px solid var(--border);
		margin: 24px 0;
	}
	.doc-content :global(.mermaid) {
		margin: 16px 0;
		text-align: center;
	}
	.doc-content :global(.mermaid svg) {
		max-width: 100%;
	}
</style>
