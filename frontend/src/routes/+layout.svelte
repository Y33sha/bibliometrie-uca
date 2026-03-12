<script lang="ts">
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { base } from '$app/paths';
	import type { Snippet } from 'svelte';

	let { children }: { children: Snippet } = $props();

	const isAdmin = $derived($page.url.pathname.startsWith(base + '/admin'));
	const isAddresses = $derived(
		$page.url.pathname === base + '/admin/addresses' || $page.url.pathname === base + '/admin/feedback'
	);

	let dropdownOpen = $state(false);

	function isActive(path: string): boolean {
		const current = $page.url.pathname;
		const full = base + path;
		if (current === full) return true;
		if (path !== '/' && current.startsWith(full)) return true;
		return false;
	}

	async function logout() {
		await fetch(base + '/api/auth/logout', { method: 'POST' });
		goto(base + '/login');
	}
</script>

<div class="site-header">
	{#if isAdmin}
		<h1 class="site-title">Bibliométrie UCA <span class="site-title-admin">Admin</span></h1>
		<nav class="site-nav">
			<div
				class="nav-dropdown"
				class:active={isAddresses}
				onmouseenter={() => (dropdownOpen = true)}
				onmouseleave={() => (dropdownOpen = false)}
			>
				<button class="nav-link" class:active={isAddresses}>Adresses &#x25BE;</button>
				{#if dropdownOpen}
					<div class="nav-dropdown-menu">
						<a href="{base}/admin/addresses" class:active={isActive('/admin/addresses')}>Repérage</a>
						<a href="{base}/admin/feedback" class:active={isActive('/admin/feedback')}>Qualité</a>
					</div>
				{/if}
			</div>
			<a href="{base}/admin/structures" class="nav-link" class:active={isActive('/admin/structures')}>Structures</a>
			<a href="{base}/admin/persons" class="nav-link" class:active={isActive('/admin/persons')}>Personnes</a>
			<a href="{base}/admin/duplicates" class="nav-link" class:active={isActive('/admin/duplicates')}>Doublons publis</a>
			<a href="{base}/admin/duplicates-persons" class="nav-link" class:active={isActive('/admin/duplicates-persons')}>Doublons personnes</a>
			<a href="{base}/stats" class="nav-link nav-switch-link">Public</a>
			<button class="nav-link nav-switch-link" onclick={logout}>Déconnexion</button>
		</nav>
	{:else}
		<h1 class="site-title">Bibliométrie UCA</h1>
		<nav class="site-nav">
			<a href="{base}/stats" class="nav-link" class:active={isActive('/stats')}>Statistiques</a>
			<a href="{base}/publications" class="nav-link" class:active={isActive('/publications')}>Publications</a>
			<a href="{base}/laboratories" class="nav-link" class:active={isActive('/laboratories')}>Laboratoires</a>
			<a href="{base}/persons" class="nav-link" class:active={isActive('/persons')}>Personnes</a>
			<a href="{base}/admin/addresses" class="nav-link nav-switch-link">Admin</a>
		</nav>
	{/if}
</div>

<div class="container">
	{@render children()}
</div>

<style>
	:global(html) {
		font-size: 16px;
	}
	:global(body) {
		margin: 0;
		font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
		font-size: 1rem;
		line-height: 1.5;
		color: var(--text);
		background: var(--bg);
	}
	:global(:root) {
		--bg: #f8f7f4;
		--card: #ffffff;
		--text: #2c2c2c;
		--muted: #6b7280;
		--accent: #3b6b9e;
		--border: #e5e5e0;
		--gold: #d4a017;
		--diamond: #0288a8;
		--hybrid: #8e6bbf;
		--bronze: #b8733e;
		--green: #2a7d4f;
		--closed: #555;
		--unknown: #bbb;
	}
	:global(*, *::before, *::after) {
		box-sizing: border-box;
	}
	.site-header {
		background: #2c3e50;
		color: white;
		padding: 0 24px;
		display: flex;
		align-items: center;
		justify-content: space-between;
		height: 46px;
	}
	.site-title {
		font-size: 1.15rem;
		font-weight: 600;
		margin: 0;
	}
	.site-title-admin {
		font-size: 0.8rem;
		font-weight: 400;
		color: rgba(255, 255, 255, 0.5);
		margin-left: 6px;
		text-transform: uppercase;
		letter-spacing: 1px;
	}
	.site-nav {
		display: flex;
		align-items: center;
		gap: 0;
		height: 100%;
	}
	.nav-link {
		color: rgba(255, 255, 255, 0.7);
		text-decoration: none;
		font-size: 0.95rem;
		padding: 0 14px;
		height: 46px;
		display: flex;
		align-items: center;
		border: none;
		background: none;
		cursor: pointer;
		font-family: inherit;
		transition: color 0.15s;
	}
	.nav-link:hover {
		color: white;
	}
	.nav-link.active {
		color: white;
		box-shadow: inset 0 -2px 0 white;
	}
	.nav-switch-link {
		color: rgba(255, 255, 255, 0.4);
		font-size: 0.85rem;
		margin-left: 12px;
		border-left: 1px solid rgba(255, 255, 255, 0.15);
	}
	.nav-switch-link:hover {
		color: rgba(255, 255, 255, 0.7);
	}
	.nav-dropdown {
		position: relative;
		height: 46px;
		display: flex;
		align-items: center;
	}
	.nav-dropdown.active > .nav-link {
		color: white;
		box-shadow: inset 0 -2px 0 white;
	}
	.nav-dropdown-menu {
		position: absolute;
		top: 46px;
		left: 0;
		background: #34495e;
		border-radius: 0 0 5px 5px;
		min-width: 150px;
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
		z-index: 100;
	}
	.nav-dropdown-menu a {
		display: block;
		padding: 9px 16px;
		color: rgba(255, 255, 255, 0.8);
		text-decoration: none;
		font-size: 0.95rem;
	}
	.nav-dropdown-menu a:hover {
		background: rgba(255, 255, 255, 0.1);
		color: white;
	}
	.nav-dropdown-menu a.active {
		color: white;
		font-weight: 600;
	}
	.container {
		max-width: 1400px;
		margin: 0 auto;
		padding: 24px;
	}
</style>
