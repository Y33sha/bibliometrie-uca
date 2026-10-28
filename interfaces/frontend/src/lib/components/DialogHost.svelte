<script lang="ts">
	import Modal from '#lib/components/Modal.svelte';
	import { dialogs, resolveConfirm, dismissToast } from '#lib/dialogs.svelte.js';
</script>

{#if dialogs.confirmRequest}
	{@const r = dialogs.confirmRequest}
	<Modal
		title={r.title ?? 'Confirmation'}
		maxWidth="440px"
		onclose={() => resolveConfirm(false)}
			onsubmit={() => resolveConfirm(true)}
	>
		<p class="confirm-message">{r.message}</p>
		{#snippet actions()}
			<button class="btn" onclick={() => resolveConfirm(false)}>{r.cancelLabel ?? 'Annuler'}</button>
			<button
				class="btn {r.danger ? 'btn-danger' : 'btn-confirm'}"
				onclick={() => resolveConfirm(true)}
			>
				{r.confirmLabel ?? 'Confirmer'}
			</button>
		{/snippet}
	</Modal>
{/if}

{#if dialogs.toasts.length}
	<div class="toast-stack" role="status">
		{#each dialogs.toasts as t (t.id)}
			<button type="button" class="toast toast-{t.type}" title="Fermer" onclick={() => dismissToast(t.id)}>
				{t.message}
			</button>
		{/each}
	</div>
{/if}

<style>
	.confirm-message {
		margin: 0;
		white-space: pre-line;
		font-size: var(--fs-md);
		line-height: 1.4;
	}
	.toast-stack {
		position: fixed;
		bottom: 16px;
		right: 16px;
		z-index: 10000;
		display: flex;
		flex-direction: column;
		gap: 8px;
		max-width: 360px;
	}
	.toast {
		padding: 10px 14px;
		border: none;
		border-radius: var(--radius);
		font-family: inherit;
		text-align: left;
		font-size: var(--fs-md);
		color: white;
		box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
		cursor: pointer;
		white-space: pre-line;
	}
	.toast-success {
		background: var(--success);
	}
	.toast-error {
		background: var(--danger);
	}
	.toast-info {
		background: var(--accent);
	}
	/* Orange assombri : le texte blanc y reste lisible (contraste d'environ 5:1). */
	.toast-warning {
		background: color-mix(in srgb, var(--attention) 85%, black);
	}
</style>
