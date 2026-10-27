<script lang="ts">
	import { onMount } from 'svelte';
	import type { Snippet } from 'svelte';

	let {
		title,
		onclose,
		onsubmit,
		maxWidth,
		children,
		actions
	}: {
		title?: string;
		onclose: () => void;
		/** Action « valider » déclenchée par Entrée (hors textarea/bouton/select). */
		onsubmit?: () => void;
		/** Largeur max (sinon défaut `.modal-content`). */
		maxWidth?: string;
		children: Snippet;
		/** Boutons rendus dans `.modal-actions` (optionnel). */
		actions?: Snippet;
	} = $props();

	let dialog: HTMLDivElement | undefined = $state();
	let overlay: HTMLDivElement | undefined = $state();

	// Un appui sur le fond de cette modale la ferme. Une modale ouverte par-dessus a son propre fond : un appui sur elle laisse celle-ci ouverte.
	function onpointerdown(e: PointerEvent): void {
		if (e.target === overlay) onclose();
	}

	// Focus le premier champ de saisie à l'ouverture, pour démarrer la frappe sans cliquer ; à défaut (modale sans champ) le conteneur, qui capte échap. Trap complet de Tab non implémenté (usage admin).
	onMount(() => {
		const field = dialog?.querySelector<HTMLElement>(
			'input:not([type="hidden"]):not(:disabled), textarea:not(:disabled), select:not(:disabled)'
		);
		(field ?? dialog)?.focus();
	});

	function onkeydown(e: KeyboardEvent): void {
		if (e.key === 'Escape') {
			e.preventDefault();
			onclose();
			return;
		}
		// Entrée valide, sauf si le focus est sur un champ multiligne ou un contrôle qui gère déjà Entrée (bouton, lien, select).
		if (e.key === 'Enter' && onsubmit) {
			const tag = (e.target as HTMLElement | null)?.tagName;
			if (tag === 'TEXTAREA' || tag === 'BUTTON' || tag === 'A' || tag === 'SELECT') return;
			e.preventDefault();
			onsubmit();
		}
	}
</script>

<svelte:window {onkeydown} {onpointerdown} />

<div class="modal-overlay" role="presentation" bind:this={overlay}>
	<div
		class="modal-content"
		style:max-width={maxWidth}
		role="dialog"
		aria-modal="true"
		aria-label={title}
		tabindex="-1"
		bind:this={dialog}
	>
		{#if title}<h3>{title}</h3>{/if}
		{@render children()}
		{#if actions}
			<div class="modal-actions">{@render actions()}</div>
		{/if}
	</div>
</div>
