<script lang="ts">
	// Étiquette du type d'une structure, teintée par la variable CSS du type (`--structure-{type}`).
	let { type }: { type: string } = $props();
</script>

<span class="tag structure-type" style="--tag-color: var(--structure-{type})">{type}</span>

<style>
	.structure-type {
		font-size: var(--fs-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: var(--tracking-caps);
	}
</style>
