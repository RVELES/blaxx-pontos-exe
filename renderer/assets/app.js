/**
 * Blaxx Pontos — runtime do renderer.
 * - Wrapper para o backend Flask em http://127.0.0.1:5050.
 * - Sessão em sessionStorage (some quando fecha o app).
 * - Helpers de navegação entre telas e toasts.
 */

// URL do backend — resolução em ordem:
//   1. localStorage (definido pelo main.py do app Windows a cada navegação)
//   2. window.blaxx.backendUrl (injetado pelo preload Electron ou PyWebView)
//   3. fallback localhost (modo dev)
const API = (() => {
  try {
    const saved = localStorage.getItem('blaxx_api_url');
    if (saved) return saved;
  } catch (_) { /* sandboxed / file:// pode bloquear localStorage */ }
  if (window.blaxx && window.blaxx.backendUrl) return window.blaxx.backendUrl;
  return 'http://127.0.0.1:5050';
})();

// Sessão persistida em localStorage (sobrevive reabertura do app).
// Antes era sessionStorage — perdia login a cada nova janela do WebView2.
// Migração transparente: se houver session em sessionStorage, copia para
// localStorage uma vez e limpa o antigo.
(function _migrateOldSession() {
  try {
    const old = sessionStorage.getItem('blaxx_session');
    if (old && !localStorage.getItem('blaxx_session')) {
      localStorage.setItem('blaxx_session', old);
      sessionStorage.removeItem('blaxx_session');
    }
  } catch (_) { /* tolera storage indisponível */ }
})();

const Session = {
  get() {
    try { return JSON.parse(localStorage.getItem('blaxx_session') || 'null'); }
    catch {
      try { return JSON.parse(sessionStorage.getItem('blaxx_session') || 'null'); }
      catch { return null; }
    }
  },
  set(s) {
    try { localStorage.setItem('blaxx_session', JSON.stringify(s)); }
    catch { sessionStorage.setItem('blaxx_session', JSON.stringify(s)); }
  },
  clear() {
    try { localStorage.removeItem('blaxx_session'); } catch (_) {}
    try { sessionStorage.removeItem('blaxx_session'); } catch (_) {}
  },
  token() { const s = this.get(); return s ? s.token : null; },
  user()  { const s = this.get(); return s ? s.user  : null; },
  requireAuth() {
    if (!this.token()) { go('login.html'); return false; }
    return true;
  },
};

async function api(path, opts = {}) {
  const headers = Object.assign(
    { 'Content-Type': 'application/json' },
    opts.headers || {}
  );
  const token = Session.token();
  if (token) headers['Authorization'] = 'Bearer ' + token;
  const res = await fetch(API + path, {
    method: opts.method || 'GET',
    headers,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  let data;
  const txt = await res.text();
  try { data = txt ? JSON.parse(txt) : {}; } catch { data = { raw: txt }; }
  if (!res.ok) {
    const err = new Error(data.error || data.message || `HTTP ${res.status}`);
    err.status = res.status;
    err.data = data;
    // 401 global: token expirado/invalidado em endpoints autenticados →
    // limpa Session e manda pro login. Não dispara em endpoints públicos
    // (auth/login, register, google, forgot, reset) — ali 401 é "credenciais
    // inválidas" e a UI específica trata.
    if (res.status === 401
        && !path.startsWith('/auth/login')
        && !path.startsWith('/auth/register')
        && !path.startsWith('/auth/google')
        && !path.startsWith('/auth/forgot')
        && !path.startsWith('/auth/reset')) {
      try { Session.clear(); } catch (_) {}
      // Evita loop se já estiver na própria login
      const here = (location.pathname.split('/').pop() || '').toLowerCase();
      if (here !== 'login.html' && here !== 'cadastro.html'
          && here !== 'recuperar-senha.html' && here !== 'redefinir-senha.html'
          && here !== 'validacao.html' && here !== 'index.html') {
        go('login.html');
      }
    }
    throw err;
  }
  return data;
}

function go(file) {
  // Todas as telas vivem em renderer/screens/. index.html roteia para login.
  if (file === 'index.html') {
    location.href = '../index.html';
  } else {
    location.href = file;
  }
}

// Logout proper — avisa backend (POST /auth/logout pra revogar JWT)
// e só depois limpa Session local. Silencioso em erro de rede.
function logout() {
  const finish = () => { Session.clear(); go('login.html'); };
  try {
    api('/auth/logout', { method: 'POST' }).then(finish, finish);
  } catch (_) {
    finish();
  }
}

// Redirect síncrono se já logado — usado em login.html/cadastro.html pra
// evitar flash da tela de login quando o user reabre o app já logado.
// Retorna true se redirecionou (caller deve abortar init).
function redirectIfLoggedIn() {
  if (Session.token()) {
    go('dashboard.html');
    return true;
  }
  return false;
}

// Handler global pra cliques em links "Sair" / "Entrar" hardcoded no HTML.
// Algumas telas tem <a href="login.html">Sair</a> direto, sem onclick que
// limpe Session — clicar só navega, deixando token no storage. Resultado:
// user "achava" que deslogou mas estava ainda autenticado.
//
// Solução: event delegation captura todo <a> apontando pra login.html e
// analisa o texto pra decidir entre logout() ou ir pro dashboard.
function installGlobalLogoutHandler() {
  document.addEventListener('click', (e) => {
    const a = e.target.closest && e.target.closest('a');
    if (!a) return;
    const href = a.getAttribute('href') || '';
    if (!/login(\.html)?(\?|#|$)/.test(href)) return;
    const text = (a.textContent || '').trim().toLowerCase();
    if (text.indexOf('sair') >= 0 || text.indexOf('logout') >= 0) {
      e.preventDefault();
      logout();
      return;
    }
    if (Session.token() && (text.indexOf('entrar') >= 0 || text.indexOf('cadastre') >= 0)) {
      e.preventDefault();
      go('dashboard.html');
    }
  }, true);
}

// Instala o handler global assim que o DOM estiver disponível
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', installGlobalLogoutHandler);
} else {
  installGlobalLogoutHandler();
}

function toast(msg, kind = 'success', ms = 2400) {
  const el = document.createElement('div');
  el.className = 'toast ' + kind;
  el.textContent = msg;
  document.body.appendChild(el);
  requestAnimationFrame(() => el.classList.add('show'));
  setTimeout(() => {
    el.classList.remove('show');
    setTimeout(() => el.remove(), 250);
  }, ms);
}

function fmtPts(n) {
  return Number(n || 0).toLocaleString('pt-BR') + ' pts';
}
function fmtBRL(v) {
  return Number(v || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}
function fmtDateTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
}

// Sidebar reutilizável - injetada nas telas autenticadas
function renderSidebar(active) {
  const items = [
    { id: 'dashboard',     icon: '◇', label: 'Início',         href: 'dashboard.html' },
    { id: 'carteira',      icon: '⌬', label: 'Carteira',       href: 'carteira.html' },
    { id: 'extrato',       icon: '≡', label: 'Extrato',         href: 'extrato.html' },
    { id: 'comprar',       icon: '+', label: 'Comprar pontos', href: 'comprar-pontos.html' },
    { id: 'enviar',        icon: '↗', label: 'Enviar pontos',  href: 'enviar-pontos.html' },
    { id: 'resgatar',      icon: '↙', label: 'Resgatar',       href: 'vender-pontos.html' },
    { id: 'parceiros',     icon: '◯', label: 'Parceiros',      href: 'parceiros.html' },
    { id: 'beneficios',    icon: '✦', label: 'Benefícios',     href: 'resgates.html' },
    { id: 'campanhas',     icon: '★', label: 'Campanhas',      href: 'campanhas.html' },
  ];
  const user = Session.user() || { name: 'Convidado' };
  const initial = (user.name || '?').slice(0,1).toUpperCase();

  return `
    <aside class="sidebar">
      <div class="logo logo-blaxx"><span class="logo-mark">BlaxX</span><span class="logo-sub">pontos</span></div>

      <div class="section-label">Programa</div>
      ${items.map(it => `
        <div class="nav-item ${active === it.id ? 'active' : ''}"
             onclick="go('${it.href}')">
          <span class="icon">${it.icon}</span>
          <span>${it.label}</span>
        </div>
      `).join('')}

      <div class="section-label">Conta</div>
      <div class="nav-item ${active === 'perfil' ? 'active' : ''}" onclick="go('perfil.html')">
        <span class="icon">◐</span><span>Perfil</span>
      </div>
      <div class="nav-item ${active === 'seguranca' ? 'active' : ''}" onclick="go('seguranca.html')">
        <span class="icon">🔒</span><span>Segurança</span>
      </div>
      <div class="nav-item" onclick="logout()">
        <span class="icon">⎋</span><span>Sair</span>
      </div>

      <div class="sidebar-footer">
        ${initial} · ${user.name}<br/>
        BlaxX · v0.1.0
      </div>
    </aside>
  `;
}

function renderTopbar({ eyebrow = 'Bem-vindo de volta', title } = {}) {
  const user = Session.user() || { name: '' };
  const initial = (user.name || '?').slice(0,1).toUpperCase();
  const html = `
    <div class="topbar">
      <div class="greeting">
        <span class="eyebrow">${eyebrow}</span>
        <h2>${title || 'Olá, ' + (user.name || '').split(' ')[0]}</h2>
      </div>
      <div class="actions">
        <button class="btn ghost" onclick="go('central-notificacoes.html')" id="btn-notif">
          Notificações <span id="notif-count" style="display:none;background:var(--blaxx-lime);color:var(--blaxx-black);padding:2px 8px;border-radius:999px;margin-left:6px;font-weight:700;font-size:11px;"></span>
        </button>
        <div class="avatar">${initial}</div>
      </div>
    </div>
  `;
  // Atualiza contagem de não lidas (fire-and-forget)
  setTimeout(async () => {
    try {
      const r = await api('/notifications/unread-count');
      const el = document.getElementById('notif-count');
      if (el && r.count > 0) {
        el.textContent = r.count;
        el.style.display = 'inline-block';
      }
    } catch {}
  }, 100);
  return html;
}
