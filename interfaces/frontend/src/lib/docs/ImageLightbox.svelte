<script lang="ts">
	/**
	 * Lightbox au clic sur les images de doc.
	 *
	 * - Monté une fois au layout `/docs/`.
	 * - Listener global sur les clics dans `.doc-content` : tout `<img>` (qui n'est pas dans un `<a>`) ouvre l'image en plein écran sur un overlay sombre.
	 * - Fermeture : clic sur l'overlay (n'importe où), Esc.
	 * - Bloque le scroll de la page derrière l'overlay tant qu'il est ouvert.
	 */

	let activeSrc = $state<string>('');
	let activeAlt = $state<string>('');

	function open(src: string, alt: string) {
		activeSrc = src;
		activeAlt = alt;
		document.body.style.overflow = 'hidden';
	}

	function close() {
		activeSrc = '';
		activeAlt = '';
		document.body.style.overflow = '';
	}

	$effect(() => {
		function onClick(e: MouseEvent) {
			const target = e.target as HTMLElement | null;
			if (!target) return;
			if (target.tagName !== 'IMG') return;
			if (target.closest('a')) return; // image dans un lien : laisser passer
			if (!target.closest('.doc-content')) return; // hors zone doc
			const img = target as HTMLImageElement;
			e.preventDefault();
			open(img.currentSrc || img.src, img.alt);
		}
		function onKeydown(e: KeyboardEvent) {
			if (e.key === 'Escape') close();
		}
		window.addEventListener('click', onClick);
		window.addEventListener('keydown', onKeydown);
		return () => {
			window.removeEventListener('click', onClick);
			window.removeEventListener('keydown', onKeydown);
		};
	});
</script>

{#if activeSrc}
	<div
		class="lightbox"
		role="dialog"
		aria-label={activeAlt || 'Image agrandie'}
		onclick={close}
		onkeydown={(e) => e.key === 'Enter' && close()}
		tabindex="-1"
	>
		<img src={activeSrc} alt={activeAlt} />
	</div>
{/if}

<style>
	.lightbox {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.85);
		z-index: 2000;
		display: flex;
		align-items: center;
		justify-content: center;
		cursor: zoom-out;
		padding: 24px;
	}
	.lightbox img {
		max-width: 100%;
		max-height: 100%;
		object-fit: contain;
		box-shadow: 0 12px 40px rgba(0, 0, 0, 0.5);
	}
</style>
