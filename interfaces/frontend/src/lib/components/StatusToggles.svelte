<script lang="ts">
	import IconButton from '#lib/components/IconButton.svelte';

	// Bascules « confirmer » et « rejeter » d'un statut de validation. Un clic sur la bascule enfoncée remet le statut en attente.
	type Status = 'pending' | 'confirmed' | 'rejected';
	let { status, onchange }: { status: string; onchange: (status: Status) => void } = $props();
</script>

<IconButton
	icon="confirm"
	label={status === 'confirmed' ? 'Retirer la confirmation' : 'Confirmer'}
	pressed={status === 'confirmed'}
	onclick={() => onchange(status === 'confirmed' ? 'pending' : 'confirmed')}
/>
<IconButton
	icon="reject"
	label={status === 'rejected' ? 'Retirer le rejet' : 'Rejeter'}
	pressed={status === 'rejected'}
	onclick={() => onchange(status === 'rejected' ? 'pending' : 'rejected')}
/>
