<script lang="ts">
	import Tooltip from '#lib/components/Tooltip.svelte';

	// Point d'interrogation qui affiche une explication au survol.
	let { text }: { text: string } = $props();
</script>

<Tooltip {text}>
	<span class="help-tip" role="img" aria-label={text}>
		<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
			<circle cx="12" cy="12" r="10" /><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" /><path d="M12 17h.01" />
		</svg>
	</span>
</Tooltip>

<style>
	.help-tip {
		display: inline-flex;
		margin-left: 4px;
		vertical-align: -2px;
		color: var(--muted);
		cursor: help;
	}
	.help-tip:hover {
		color: var(--accent);
	}
</style>
