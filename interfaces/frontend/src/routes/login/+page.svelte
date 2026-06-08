<script lang="ts">
	import { goto } from '$app/navigation';
	import { base } from '$app/paths';
	import { ApiError, auth } from '$lib/api';

	let username = $state('');
	let password = $state('');
	let error = $state('');
	let loading = $state(false);

	async function handleLogin(e: SubmitEvent) {
		e.preventDefault();
		error = '';
		loading = true;
		try {
			await auth.login(username, password);
			goto(base + '/admin/addresses');
		} catch (e) {
			error = e instanceof ApiError ? 'Identifiants incorrects' : 'Erreur de connexion';
			loading = false;
		}
	}
</script>

<svelte:head>
	<title>Connexion — Bibliométrie UCA</title>
</svelte:head>

<div class="login-wrapper">
	<form class="login-card" onsubmit={handleLogin}>
		<h1>Bibliométrie UCA</h1>
		<p class="login-subtitle">Accès administration</p>

		{#if error}
			<div class="login-error">{error}</div>
		{/if}

		<label>
			<span>Identifiant</span>
			<input type="text" bind:value={username} autocomplete="username" required />
		</label>

		<label>
			<span>Mot de passe</span>
			<input type="password" bind:value={password} autocomplete="current-password" required />
		</label>

		<button type="submit" disabled={loading}>
			{loading ? 'Connexion...' : 'Se connecter'}
		</button>
	</form>
</div>

<style>
	.login-wrapper {
		display: flex;
		justify-content: center;
		align-items: center;
		min-height: 60vh;
	}
	.login-card {
		background: var(--card);
		border: 1px solid var(--border);
		border-radius: 8px;
		padding: 32px 36px;
		width: 340px;
		box-shadow: 0 2px 8px rgba(0,0,0,0.06);
	}
	.login-card h1 {
		font-size: 1.3rem;
		margin: 0 0 4px;
		text-align: center;
	}
	.login-subtitle {
		text-align: center;
		color: var(--muted);
		font-size: 0.95rem;
		margin: 0 0 20px;
	}
	.login-error {
		background: var(--danger-light);
		color: var(--danger);
		padding: 8px 12px;
		border-radius: 4px;
		font-size: 0.95rem;
		margin-bottom: 12px;
		text-align: center;
	}
	label {
		display: block;
		margin-bottom: 14px;
	}
	label span {
		display: block;
		font-size: 0.85rem;
		font-weight: 500;
		color: var(--muted);
		margin-bottom: 4px;
	}
	input {
		width: 100%;
		padding: 8px 10px;
		border: 1px solid var(--border);
		border-radius: 4px;
		font-size: 1rem;
		font-family: inherit;
		background: white;
	}
	input:focus {
		outline: none;
		border-color: var(--accent);
		box-shadow: 0 0 0 2px rgba(59, 107, 158, 0.15);
	}
	button {
		width: 100%;
		padding: 10px;
		background: var(--accent);
		color: white;
		border: none;
		border-radius: 4px;
		font-size: 1rem;
		font-weight: 500;
		cursor: pointer;
		font-family: inherit;
		margin-top: 4px;
	}
	button:hover { background: #2d5a85; }
	button:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
