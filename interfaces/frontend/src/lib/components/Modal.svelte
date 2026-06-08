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

	// Focus à l'ouverture (l'utilisateur démarre dans la modale ; échap ferme).
	// Trap complet de Tab non implémenté — usage admin, quick-win a11y.
	onMount(() => dialog?.focus());

	function onkeydown(e: KeyboardEvent): void {
		if (e.key === 'Escape') {
			e.preventDefault();
			onclose();
			return;
		}
		// Entrée valide, sauf si le focus est sur un champ multiligne ou un
		// contrôle qui gère déjà Entrée (bouton, lien, select).
		if (e.key === 'Enter' && onsubmit) {
			const tag = (e.target as HTMLElement | null)?.tagName;
			if (tag === 'TEXTAREA' || tag === 'BUTTON' || tag === 'A' || tag === 'SELECT') return;
			e.preventDefault();
			onsubmit();
		}
	}
</script>

<svelte:window {onkeydown} />

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="modal-overlay" onclick={onclose} role="presentation">
	<div
		class="modal-content"
		style:max-width={maxWidth}
		role="dialog"
		aria-modal="true"
		aria-label={title}
		tabindex="-1"
		bind:this={dialog}
		onclick={(e) => e.stopPropagation()}
	>
		{#if title}<h3>{title}</h3>{/if}
		{@render children()}
		{#if actions}
			<div class="modal-actions">{@render actions()}</div>
		{/if}
	</div>
</div>
