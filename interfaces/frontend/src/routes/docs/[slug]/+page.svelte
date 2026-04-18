<script lang="ts">
	import { page } from "$app/stores";
	import { base } from "$app/paths";
	import { api } from "$lib/api";
	import { onMount, tick } from "svelte";
	import { Marked } from "marked";
	import mermaid from "mermaid";

	interface DocContent {
		slug: string;
		title: string;
		content: string;
	}
	interface DocTodo {
		page: string;
		page_title: string;
		line: number;
		text: string;
	}

	let doc: DocContent | null = $state(null);
	let renderedHtml = $state("");
	let todos: DocTodo[] = $state([]);
	let isTodos = $derived($page.params.slug === "todos");

	// Renderer custom pour ajouter des id sur les headings (ancres)
	const renderer = {
		heading({ text, depth }: { text: string; depth: number }) {
			const anchor = text
				.toLowerCase()
				.replace(/[^\w\s-]/g, "")
				.replace(/[\s]+/g, "-")
				.replace(/-+$/, "");
			return `<h${depth} id="${anchor}">${text}</h${depth}>`;
		},
	};
	const marked = new Marked({ renderer });

	async function renderMermaid() {
		await tick();
		const container = document.querySelector(".doc-body");
		if (!container) return;
		const blocks = container.querySelectorAll("pre code.language-mermaid");
		for (const block of blocks) {
			const pre = block.parentElement;
			if (!pre) continue;
			const div = document.createElement("div");
			div.className = "mermaid";
			div.textContent = block.textContent || "";
			pre.replaceWith(div);
		}
		await mermaid.run({ querySelector: ".doc-body .mermaid" });
	}

	async function loadDoc(slug: string) {
		doc = await api<DocContent>(`/api/docs/${slug}`);
		renderedHtml = await marked.parse(doc.content);
		await renderMermaid();
		// Scroller vers l'ancre si présente dans l'URL
		await tick();
		const hash = window.location.hash;
		if (hash) {
			const el = document.getElementById(hash.slice(1));
			if (el) el.scrollIntoView();
		}
	}

	async function loadTodos() {
		todos = await api<DocTodo[]>("/api/docs/todos/all");
	}

	// Transformer les liens internes dans le HTML rendu
	// "pipeline" → "/bibliometrie/docs/pipeline"
	// "glossaire#terme" → "/bibliometrie/docs/glossaire#terme"
	function fixLinks(html: string): string {
		return html.replace(
			/href="(?!http|\/|#)([^"]+)"/g,
			(_, href) => `href="${base}/docs/${href}"`
		);
	}

	const displayHtml = $derived(fixLinks(renderedHtml));

	onMount(() => {
		mermaid.initialize({ startOnLoad: false, theme: "neutral" });
	});

	$effect(() => {
		const slug = $page.params.slug;
		if (slug === "todos") {
			loadTodos();
		} else if (slug) {
			loadDoc(slug);
		}
	});
</script>

<svelte:head>
	<title>{isTodos ? "TODOs" : doc?.title || "Documentation"} — Bibliométrie UCA</title>
</svelte:head>

<div class="doc-body">
	{#if isTodos}
		<h1>TODOs dans la documentation</h1>
		{#if todos.length === 0}
			<p>Aucun TODO trouvé. Ajoutez <code>&lt;!-- TODO: texte --&gt;</code> dans un fichier .md.</p>
		{:else}
			<p class="todo-count">{todos.length} TODO{todos.length > 1 ? "s" : ""}</p>
			{#each todos as todo}
				<div class="todo-item">
					<a href="{base}/docs/{todo.page}">{todo.page_title}</a>
					<span class="todo-line">l.{todo.line}</span>
					<span class="todo-text">{todo.text}</span>
				</div>
			{/each}
		{/if}
	{:else}
		{@html displayHtml}
	{/if}
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
	}
	.doc-body :global(h3) {
		font-size: 1.05rem;
		font-weight: 600;
		margin: 24px 0 8px;
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
		font-family: "JetBrains Mono", "Fira Code", monospace;
		font-size: 0.85em;
	}
	.doc-body :global(:not(pre) > code) {
		background: #f0efec;
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
		border-bottom: 1px solid #f0efec;
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
	.todo-count {
		color: var(--muted);
		font-size: 0.9rem;
	}
	.todo-item {
		padding: 8px 0;
		border-bottom: 1px solid #f0efec;
		font-size: 0.9rem;
	}
	.todo-item a {
		color: var(--accent);
		text-decoration: none;
		font-weight: 500;
	}
	.todo-item a:hover {
		text-decoration: underline;
	}
	.todo-line {
		color: var(--muted);
		font-size: 0.8rem;
		margin: 0 8px;
	}
	.todo-text {
		color: var(--text);
	}
</style>
