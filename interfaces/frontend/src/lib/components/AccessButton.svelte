<script lang="ts">
	// Bouton vers le lien d'accès d'une publication. Sans lien, un bloc du même format signale l'embargo, ou la fermeture hors tableau.
	let {
		accessUrl,
		oaStatus,
		compact = false,
	}: {
		accessUrl: string | null | undefined;
		oaStatus: string | null | undefined;
		/** Format de tableau : libellés courts ; l'accès fermé n'est pas signalé. */
		compact?: boolean;
	} = $props();
</script>

{#if accessUrl}
	<a class="access-btn" class:compact href={accessUrl} target="_blank" rel="noopener">
		{compact ? 'Texte intégral' : 'Lire le texte intégral'}
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
		color: white;
		font-weight: 700;
		font-size: 1rem;
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
		font-size: 0.75rem;
		font-weight: 600;
	}
	.access-btn.compact svg {
		width: 12px;
		height: 12px;
	}
	.access-unavailable {
		background: var(--border);
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
