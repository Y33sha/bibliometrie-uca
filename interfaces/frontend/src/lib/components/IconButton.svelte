<script lang="ts">
	// Bouton d'action réduit à son icône : crayon pour modifier, corbeille pour supprimer. Le libellé sert d'infobulle et de nom accessible.
	let {
		icon,
		label,
		onclick,
		disabled = false
	}: {
		icon: 'edit' | 'delete';
		label: string;
		onclick: () => void;
		disabled?: boolean;
	} = $props();
</script>

<button type="button" class="icon-btn" class:icon-btn-danger={icon === 'delete'} title={label} aria-label={label} {disabled} {onclick}>
	<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
		{#if icon === 'edit'}
			<path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" /><path d="m15 5 4 4" />
		{:else}
			<path d="M3 6h18" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" /><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
		{/if}
	</svg>
</button>
