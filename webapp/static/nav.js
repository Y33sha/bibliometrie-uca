/* Public navigation bar — injected into public pages */

(function() {
    const currentPath = window.location.pathname;

    function isActive(path) {
        if (currentPath === path) return true;
        if (path !== '/' && currentPath.startsWith(path)) return true;
        return false;
    }

    const nav = document.createElement('div');
    nav.className = 'site-header';
    nav.innerHTML = `
        <h1 class="site-title">Bibliométrie UCA</h1>
        <nav class="site-nav">
            <a href="/stats" class="nav-link${isActive('/stats') ? ' active' : ''}">Statistiques</a>
            <a href="/publications" class="nav-link${isActive('/publications') ? ' active' : ''}">Publications</a>
            <a href="/laboratories" class="nav-link${isActive('/laboratories') ? ' active' : ''}">Laboratoires</a>
            <a href="/persons" class="nav-link${isActive('/persons') ? ' active' : ''}">Personnes</a>
            <a href="/admin/addresses" class="nav-link nav-admin-link">Admin</a>
        </nav>`;

    const style = document.createElement('style');
    style.textContent = `
        html { zoom: 1.15; }
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
            font-size: 16px;
            font-weight: 600;
            margin: 0;
        }
        .site-nav {
            display: flex;
            align-items: center;
            gap: 0;
            height: 100%;
        }
        .nav-link {
            color: rgba(255,255,255,0.7);
            text-decoration: none;
            font-size: 13px;
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
        .nav-link:hover { color: white; }
        .nav-link.active {
            color: white;
            box-shadow: inset 0 -2px 0 white;
        }
        .nav-admin-link {
            color: rgba(255,255,255,0.4);
            font-size: 12px;
            margin-left: 12px;
            border-left: 1px solid rgba(255,255,255,0.15);
        }
        .nav-admin-link:hover { color: rgba(255,255,255,0.7); }
    `;
    document.head.appendChild(style);

    const oldHeader = document.querySelector('.header');
    if (oldHeader) {
        oldHeader.replaceWith(nav);
    } else {
        document.body.insertBefore(nav, document.body.firstChild);
    }
})();
