<script lang="ts">
	import Modal from '$lib/components/Modal.svelte';
	import { dialogs, resolveConfirm, dismissToast } from '$lib/dialogs.svelte';
</script>

{#if dialogs.confirmRequest}
	{@const r = dialogs.confirmRequest}
	<Modal
		title={r.title ?? 'Confirmation'}
		maxWidth="440px"
		onclose={() => resolveConfirm(false)}
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
	<div class="toast-stack">
		{#each dialogs.toasts as t (t.id)}
			<!-- svelte-ignore a11y_no_static_element_interactions -->
			<div class="toast toast-{t.type}" role="status" onclick={() => dismissToast(t.id)}>
				{t.message}
			</div>
		{/each}
	</div>
{/if}

<style>
	.confirm-message {
		margin: 0;
		white-space: pre-line;
		font-size: 0.95rem;
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
		border-radius: 6px;
		font-size: 0.9rem;
		color: white;
		box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
		cursor: pointer;
		white-space: pre-line;
	}
	.toast-success {
		background: var(--success, #2e7d32);
	}
	.toast-error {
		background: var(--danger, #c0392b);
	}
	.toast-info {
		background: var(--accent, #3b6b9e);
	}
</style>
