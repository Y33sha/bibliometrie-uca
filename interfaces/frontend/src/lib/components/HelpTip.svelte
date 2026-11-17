<script lang="ts">
	import CircleQuestionMark from '@lucide/svelte/icons/circle-question-mark';
	import Tooltip from '#lib/components/Tooltip.svelte';

	// Point d'interrogation qui affiche une explication au survol.
	let { text }: { text: string } = $props();
</script>

<Tooltip {text}>
	<span class="help-tip" role="img" aria-label={text}>
		<CircleQuestionMark size={14} />
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
