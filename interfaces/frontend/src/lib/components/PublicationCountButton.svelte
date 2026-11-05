<script lang="ts">
	import { formatCount } from '#lib/plural.js';

	/** Badge du nombre de publications : bouton qui déplie la liste des publications. */
	let { count, expanded, onclick }: { count: number; expanded: boolean; onclick: () => void } = $props();
</script>

<button type="button" class="tag tag-pill tag-accent" aria-expanded={expanded} {onclick}
	>{formatCount(count, 'publication')}</button
>
