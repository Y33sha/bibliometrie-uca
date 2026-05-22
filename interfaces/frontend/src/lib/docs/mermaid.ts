import mermaid from 'mermaid';

let initialized = false;

/**
 * Détecte les blocs `<pre><code class="language-mermaid">` dans un container,
 * les remplace par `<div class="mermaid">…</div>` et déclenche le rendu.
 *
 * Le rendu Mermaid reste client-side : le HTML pré-rendu côté serveur
 * contient toujours les blocs de code, et c'est cette fonction qui les
 * active au mount du composant qui les affiche.
 */
export async function renderMermaidBlocks(container: Element): Promise<void> {
	if (!initialized) {
		mermaid.initialize({ startOnLoad: false, theme: 'neutral' });
		initialized = true;
	}
	const blocks = container.querySelectorAll('pre code.language-mermaid');
	for (const block of blocks) {
		const pre = block.parentElement;
		if (!pre) continue;
		const div = document.createElement('div');
		div.className = 'mermaid';
		div.textContent = block.textContent || '';
		pre.replaceWith(div);
	}
	if (container.querySelectorAll('.mermaid').length > 0) {
		await mermaid.run({ nodes: Array.from(container.querySelectorAll('.mermaid')) });
	}
}
