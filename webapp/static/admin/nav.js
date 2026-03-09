/* Admin navigation bar — injected into admin pages */

(function() {
    const currentPath = window.location.pathname;

    function isActive(path) {
        if (currentPath === path) return true;
        return false;
    }

    const isAdresses = (currentPath === '/admin/addresses' || currentPath === '/admin/feedback');

    const nav = document.createElement('div');
    nav.className = 'site-header';
    nav.innerHTML = `
        <h1 class="site-title">Bibliométrie UCA <span class="site-title-admin">Admin</span></h1>
        <nav class="site-nav">
            <div class="nav-dropdown ${isAdresses ? 'active' : ''}">
                <button class="nav-link">Adresses &#x25BE;</button>
                <div class="nav-dropdown-menu">
                    <a href="/admin/addresses"${isActive('/admin/addresses') ? ' class="active"' : ''}>Rep\u00e9rage</a>
                    <a href="/admin/feedback"${isActive('/admin/feedback') ? ' class="active"' : ''}>Qualit\u00e9</a>
                </div>
            </div>
            <a href="/admin/structures" class="nav-link${isActive('/admin/structures') ? ' active' : ''}">Structures</a>
            <a href="/admin/authorships" class="nav-link${isActive('/admin/authorships') ? ' active' : ''}">Authorships</a>
            <a href="/admin/persons" class="nav-link${isActive('/admin/persons') ? ' active' : ''}">Personnes</a>
            <a href="/stats" class="nav-link nav-public-link">Public</a>
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
        .site-title-admin {
            font-size: 11px;
            font-weight: 400;
            color: rgba(255,255,255,0.5);
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
            display: none;
            position: absolute;
            top: 46px;
            left: 0;
            background: #34495e;
            border-radius: 0 0 5px 5px;
            min-width: 150px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.2);
            z-index: 100;
        }
        .nav-dropdown:hover .nav-dropdown-menu { display: block; }
        .nav-dropdown-menu a {
            display: block;
            padding: 9px 16px;
            color: rgba(255,255,255,0.8);
            text-decoration: none;
            font-size: 13px;
        }
        .nav-dropdown-menu a:hover { background: rgba(255,255,255,0.1); color: white; }
        .nav-dropdown-menu a.active { color: white; font-weight: 600; }
        .nav-public-link {
            color: rgba(255,255,255,0.4);
            font-size: 12px;
            margin-left: 12px;
            border-left: 1px solid rgba(255,255,255,0.15);
        }
        .nav-public-link:hover { color: rgba(255,255,255,0.7); }
    `;
    document.head.appendChild(style);

    const oldHeader = document.querySelector('.header');
    if (oldHeader) {
        oldHeader.replaceWith(nav);
    } else {
        document.body.insertBefore(nav, document.body.firstChild);
    }
})();
