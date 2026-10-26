<script lang="ts">
	import { asset } from '$app/paths';

	// Logo DOI vers la page du DOI, qui grossit au survol.
	let { doi }: { doi: string } = $props();
</script>

<a href="https://doi.org/{doi}" target="_blank" rel="noopener" class="doi-link" title={doi}>
	<img src={asset('icons/doi.svg')} alt="DOI" />
</a>

<style>
	.doi-link {
		display: inline-block;
		vertical-align: middle;
		transition: transform 0.1s;
	}
	.doi-link:hover {
		transform: scale(1.15);
	}
	.doi-link img {
		display: block;
		width: 20px;
		height: 20px;
	}
</style>
