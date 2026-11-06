<script lang="ts">
	// Lien d'accès au texte intégral d'une publication : bouton plein, ou, en format de liste, cadenas open access et lien. Sans lien, un bloc du même format signale l'embargo, ou la fermeture hors liste.
	let {
		accessUrl,
		oaStatus,
		compact = false,
	}: {
		accessUrl: string | null | undefined;
		oaStatus: string | null | undefined;
		/** Format de liste et de tableau : libellés courts ; l'accès fermé n'est pas signalé. */
		compact?: boolean;
	} = $props();
</script>

{#if accessUrl && compact}
	<a class="access-link" href={accessUrl} target="_blank" rel="noopener">
		<svg class="oa-logo" viewBox="0 0 40 60" aria-hidden="true">
			<path d="M10 31V16a10 10 0 0 1 20 0v4" fill="none" stroke="currentColor" stroke-width="6" />
			<circle cx="20" cy="41" r="13" fill="none" stroke="currentColor" stroke-width="6" />
			<circle cx="20" cy="41" r="4.5" fill="currentColor" />
		</svg>
		Texte intégral
		<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
			<path d="M7 17L17 7M17 7H8M17 7v9" />
		</svg>
	</a>
{:else if accessUrl}
	<a class="access-btn" href={accessUrl} target="_blank" rel="noopener">
		Lire le texte intégral
		<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
			<path d="M7 17L17 7M17 7H8M17 7v9" />
		</svg>
	</a>
{:else if oaStatus === 'embargoed'}
	<span class="access-btn" class:compact class:access-embargo={compact} class:access-unavailable={!compact}>
		{#if compact}
			Embargo
		{:else}
			<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
				<circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
			</svg>
			Sous embargo
		{/if}
	</span>
{:else if oaStatus === 'closed' && !compact}
	<span class="access-btn access-unavailable">
		<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
			<rect x="3" y="11" width="18" height="11" rx="2" ry="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" />
		</svg>
		Accès fermé
	</span>
{/if}

<style>
	.access-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 8px;
		height: 44px;
		border-radius: var(--radius);
		background: var(--accent);
		color: var(--text-inverse);
		font-weight: 700;
		font-size: var(--fs-base);
		text-decoration: none;
		white-space: nowrap;
	}
	a.access-btn:hover {
		background: color-mix(in srgb, var(--accent), black 20%);
		text-decoration: none;
	}
	.access-btn svg {
		width: 16px;
		height: 16px;
	}
	.access-btn.compact {
		display: inline-flex;
		gap: 4px;
		height: 22px;
		padding: 0 8px;
		font-size: var(--fs-sm);
		font-weight: 600;
	}
	.access-btn.compact svg {
		width: 12px;
		height: 12px;
	}
	/* Dans une liste : lien en texte, précédé du cadenas open access. */
	.access-link {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		font-size: var(--fs-sm);
		font-weight: 600;
		color: var(--text-secondary);
		text-decoration: none;
		white-space: nowrap;
	}
	.access-link:hover {
		color: var(--accent);
		text-decoration: underline;
	}
	.access-link svg {
		width: 12px;
		height: 12px;
	}
	.access-link .oa-logo {
		width: 10px;
		height: 15px;
		color: var(--open-access-logo);
	}
	/* Sans lien d'accès : un état, écrit en texte avec son icône, et non un bouton. */
	.access-unavailable {
		justify-content: flex-start;
		height: auto;
		background: none;
		color: var(--text-secondary);
		font-weight: 600;
		cursor: default;
	}
	.access-embargo {
		background: var(--success-light);
		color: var(--open-text);
		cursor: default;
	}
</style>
