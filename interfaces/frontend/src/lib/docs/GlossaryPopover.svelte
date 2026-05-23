<script lang="ts">
	/**
	 * Popover global pour les termes du glossaire.
	 *
	 * Comportement :
	 * - Se monte une fois au layout `/docs/`.
	 * - Listener global sur les clics : tout `<a data-glossary="slug">` capture le clic et ouvre le popover si le `slug` correspond à une entrée connue (sinon, le lien continue à se comporter comme un lien normal vers `/docs/glossaire#slug`).
	 * - Fermeture sur Esc, clic ailleurs, ou scroll de la page (la position devient incorrecte).
	 * - Lien « Voir dans le glossaire → » en bas du popover pour les définitions longues / riches que l'utilisateur veut consulter en plein.
	 *
	 * MVP volontairement minimal : positionnement basique sous le lien target, pas de flip/collision (à ajouter avec Floating UI si nécessaire plus tard).
	 */
	import { page } from '$app/stores';
	import { base } from '$app/paths';

	type GlossaryEntry = { term: string; html: string };

	const glossary = $derived(
		($page.data.glossary ?? {}) as Record<string, GlossaryEntry>
	);

	let activeSlug = $state<string>('');
	let activeEntry = $state<GlossaryEntry | null>(null);
	let popoverTop = $state(0);
	let popoverLeft = $state(0);
	let popoverEl: HTMLElement | null = $state(null);

	function open(target: HTMLElement, slug: string) {
		const entry = glossary[slug];
		if (!entry) return false;
		activeSlug = slug;
		activeEntry = entry;
		const rect = target.getBoundingClientRect();
		popoverTop = rect.bottom + window.scrollY + 6;
		popoverLeft = rect.left + window.scrollX;
		return true;
	}

	function close() {
		activeEntry = null;
		activeSlug = '';
	}

	$effect(() => {
		// Intercepte en phase capture pour passer DEVANT SvelteKit, qui
		// gère lui-même les clics sur les `<a>` internes (bubble phase).
		// Sans ça, SvelteKit déclenche `goto()` avant que le popover puisse
		// afficher (l'infobulle apparaît brièvement puis la page change).
		function onClickCapture(e: MouseEvent) {
			const target = e.target as HTMLElement | null;
			if (!target) return;
			const link = target.closest<HTMLAnchorElement>('a[data-glossary]');
			if (link) {
				const slug = link.getAttribute('data-glossary');
				if (slug && open(link, slug)) {
					e.preventDefault();
					e.stopImmediatePropagation();
					return;
				}
			}
		}
		function onClickBubble(e: MouseEvent) {
			// Fermer le popover sur clic en dehors. En bubble phase pour ne pas
			// se déclencher avant que l'ouverture (capture) ait positionné le popover.
			const target = e.target as HTMLElement | null;
			if (!target) return;
			if (activeEntry && popoverEl && !popoverEl.contains(target)) {
				const onGlossLink = target.closest<HTMLAnchorElement>('a[data-glossary]');
				if (!onGlossLink) close();
			}
		}
		function onKeydown(e: KeyboardEvent) {
			if (e.key === 'Escape') close();
		}
		function onScroll() {
			close();
		}
		window.addEventListener('click', onClickCapture, true);
		window.addEventListener('click', onClickBubble);
		window.addEventListener('keydown', onKeydown);
		window.addEventListener('scroll', onScroll, true);
		return () => {
			window.removeEventListener('click', onClickCapture, true);
			window.removeEventListener('click', onClickBubble);
			window.removeEventListener('keydown', onKeydown);
			window.removeEventListener('scroll', onScroll, true);
		};
	});
</script>

{#if activeEntry}
	<div
		class="glossary-popover"
		role="dialog"
		aria-label="Définition : {activeEntry.term}"
		style="top:{popoverTop}px;left:{popoverLeft}px;"
		bind:this={popoverEl}
	>
		<h4>{activeEntry.term}</h4>
		<div class="glossary-popover-content">{@html activeEntry.html}</div>
		<a class="see-more" href="{base}/docs/glossaire#{activeSlug}">
			Voir dans le glossaire →
		</a>
	</div>
{/if}

<style>
	.glossary-popover {
		position: absolute;
		z-index: 1000;
		max-width: 420px;
		min-width: 260px;
		background: white;
		border: 1px solid var(--border);
		border-radius: 6px;
		box-shadow: 0 6px 24px rgba(0, 0, 0, 0.12);
		padding: 12px 16px 10px;
		font-size: 0.9rem;
		line-height: 1.5;
	}
	.glossary-popover h4 {
		margin: 0 0 6px;
		font-size: 0.95rem;
		font-weight: 600;
		color: var(--text);
	}
	.glossary-popover-content :global(p) {
		margin: 0 0 6px;
	}
	.glossary-popover-content :global(p:last-child) {
		margin-bottom: 0;
	}
	.glossary-popover-content :global(table) {
		border-collapse: collapse;
		margin: 6px 0;
		font-size: 0.85rem;
	}
	.glossary-popover-content :global(th),
	.glossary-popover-content :global(td) {
		border: 1px solid var(--border);
		padding: 4px 8px;
	}
	.glossary-popover .see-more {
		display: inline-block;
		margin-top: 8px;
		font-size: 0.8rem;
		color: var(--accent);
		text-decoration: none;
	}
	.glossary-popover .see-more:hover {
		text-decoration: underline;
	}
</style>
