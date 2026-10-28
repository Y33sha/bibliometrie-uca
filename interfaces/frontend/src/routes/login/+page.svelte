<script lang="ts">
	import { pageTitle, siteTitle } from '#lib/institution.svelte.js';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { auth } from '#lib/api/index.js';
	import { loadSession, returnPath } from '#lib/session.svelte.js';

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
			await loadSession(true);
			goto(returnPath(page.url.searchParams.get('redirect'), page.url.origin));
		} catch (e) {
			error = auth.loginErrorMessage(e);
			loading = false;
		}
	}
</script>

<svelte:head>
	<title>{pageTitle("Connexion")}</title>
</svelte:head>

<div class="login-wrapper">
	<form class="login-card" onsubmit={handleLogin}>
		<h1>{siteTitle()}</h1>
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
		border-radius: var(--radius);
		padding: 32px 36px;
		width: 340px;
		box-shadow: 0 2px 8px rgba(0,0,0,0.06);
	}
	.login-card h1 {
		font-family: var(--font-brand);
		font-size: var(--fs-xl);
		margin: 0 0 4px;
		text-align: center;
	}
	.login-subtitle {
		text-align: center;
		color: var(--muted);
		font-size: var(--fs-md);
		margin: 0 0 20px;
	}
	.login-error {
		background: var(--danger-light);
		color: var(--danger);
		padding: 8px 12px;
		border-radius: var(--radius);
		font-size: var(--fs-md);
		margin-bottom: 12px;
		text-align: center;
	}
	label {
		display: block;
		margin-bottom: 14px;
	}
	label span {
		display: block;
		font-size: var(--fs-sm);
		font-weight: 500;
		color: var(--muted);
		margin-bottom: 4px;
	}
	input {
		width: 100%;
		padding: 8px 10px;
		border: 1px solid var(--border);
		border-radius: var(--radius);
		font-size: var(--fs-base);
		font-family: inherit;
		background: var(--card);
	}
	input:focus {
		outline: none;
		border-color: var(--accent);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent-mid) 25%, transparent);
	}
	button {
		width: 100%;
		padding: 10px;
		background: var(--accent);
		color: white;
		border: none;
		border-radius: var(--radius);
		font-size: var(--fs-base);
		font-weight: 500;
		cursor: pointer;
		font-family: inherit;
		margin-top: 4px;
	}
	button:hover { background: color-mix(in srgb, var(--accent), black 20%); }
	button:disabled { opacity: 0.6; cursor: not-allowed; }
</style>
