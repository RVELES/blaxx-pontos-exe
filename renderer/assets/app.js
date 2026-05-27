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

// ======================================================================
// ROTINA: exige email verificado antes de operações sensíveis (compra)
// ======================================================================
// requireEmailVerifiedThen(callback) — checa Session.user().email_verified_at.
// Se ja verificado, executa callback. Senão abre modal inline que envia
// código de 6 dígitos por email, valida, e ao sucesso executa o callback.
// ----------------------------------------------------------------------
function _maskEmail(email) {
  if (!email) return '***';
  const parts = String(email).split('@');
  if (parts.length !== 2) return email;
  const local = parts[0];
  if (local.length <= 3) return local[0] + '***@' + parts[1];
  return local.slice(0, 3) + '***@' + parts[1];
}

async function requireEmailVerifiedThen(callback) {
  const u = Session.user();
  if (u && (u.email_verified_at || u.email_verified)) {
    callback();
    return;
  }
  // Re-checa via /auth/me caso Session esteja desatualizada
  try {
    const r = await api('/auth/me');
    const fresh = (r && (r.user || r)) || u;
    if (fresh) Session.set({ token: Session.token(), user: fresh });
    if (fresh && (fresh.email_verified_at || fresh.email_verified)) {
      callback();
      return;
    }
    showEmailVerificationModal(fresh || u || {}, callback);
  } catch (_) {
    showEmailVerificationModal(u || {}, callback);
  }
}

function showEmailVerificationModal(user, onSuccess) {
  const existing = document.getElementById('bx-verify-modal');
  if (existing) existing.remove();

  const emailMasked = _maskEmail(user.email || '');
  const overlay = document.createElement('div');
  overlay.id = 'bx-verify-modal';
  overlay.style.cssText =
    'position:fixed;inset:0;z-index:9000;background:rgba(0,0,0,0.7);' +
    'display:flex;align-items:center;justify-content:center;padding:20px;' +
    'font-family:Inter,system-ui,sans-serif;';
  overlay.innerHTML = `
    <div role="dialog" aria-modal="true" style="background:#141414;border:1px solid rgba(255,255,255,.08);
         border-radius:14px;max-width:440px;width:100%;padding:28px;
         box-shadow:0 20px 60px rgba(0,0,0,.5);color:#fff;">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:12px;">
        <div>
          <div style="font-size:11px;color:#ff6b6b;font-weight:700;letter-spacing:.08em;text-transform:uppercase;">Verificação necessária</div>
          <h3 style="margin:6px 0 0;font-size:22px;">Confirme seu email</h3>
        </div>
        <button type="button" id="bx-verify-close" aria-label="Fechar"
          style="background:none;border:0;font-size:24px;cursor:pointer;color:rgba(255,255,255,.5);line-height:1;">×</button>
      </div>
      <p style="font-size:14px;color:rgba(255,255,255,.7);line-height:1.5;margin:0 0 18px;">
        Pra comprar pontos Blaxx, primeiro confirme seu email. Vamos enviar um código de 6 dígitos para
        <strong style="color:#fff;">${emailMasked}</strong>.
      </p>

      <div id="bx-verify-step-send">
        <button id="bx-verify-send-btn" type="button" class="btn primary block">Enviar código por email</button>
      </div>

      <div id="bx-verify-step-input" style="display:none;">
        <div id="bx-verify-sent-msg" style="font-size:13px;color:#a4d65e;background:rgba(164,214,94,.1);
             padding:10px 12px;border-radius:8px;margin-bottom:14px;"></div>
        <label for="bx-verify-code" style="display:block;font-size:13px;font-weight:700;margin-bottom:6px;">Código recebido</label>
        <input id="bx-verify-code" type="text" inputmode="numeric" maxlength="6" pattern="\\d{6}"
          placeholder="000000" autocomplete="one-time-code"
          style="width:100%;padding:14px;font-size:24px;letter-spacing:0.4em;text-align:center;font-weight:700;
                 background:rgba(255,255,255,.05);color:#fff;border:2px solid rgba(255,255,255,.1);
                 border-radius:10px;outline:none;box-sizing:border-box;" />
        <button id="bx-verify-confirm-btn" type="button" class="btn primary block" style="margin-top:14px;">Verificar e continuar</button>
        <div style="text-align:center;margin-top:10px;">
          <a href="#" id="bx-verify-resend" style="font-size:12px;color:rgba(255,255,255,.5);text-decoration:underline;">Reenviar código</a>
        </div>
      </div>

      <p id="bx-verify-error" style="display:none;font-size:13px;color:#ff6b6b;margin-top:10px;text-align:center;"></p>
    </div>
  `;
  document.body.appendChild(overlay);

  const sendBtn = document.getElementById('bx-verify-send-btn');
  const confirmBtn = document.getElementById('bx-verify-confirm-btn');
  const codeInput = document.getElementById('bx-verify-code');
  const errEl = document.getElementById('bx-verify-error');
  const sentMsg = document.getElementById('bx-verify-sent-msg');
  const stepSend = document.getElementById('bx-verify-step-send');
  const stepInput = document.getElementById('bx-verify-step-input');
  const resendLink = document.getElementById('bx-verify-resend');

  const showErr = (msg) => { errEl.textContent = msg; errEl.style.display = 'block'; };
  const clearErr = () => { errEl.style.display = 'none'; errEl.textContent = ''; };
  const close = () => { try { overlay.remove(); } catch (_) {} };

  document.getElementById('bx-verify-close').addEventListener('click', close);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });

  async function sendCode(isResend) {
    clearErr();
    const btn = isResend ? resendLink : sendBtn;
    const origText = btn.textContent;
    if (btn === sendBtn) { sendBtn.disabled = true; sendBtn.textContent = 'Enviando…'; }
    else { resendLink.style.opacity = '0.5'; resendLink.style.pointerEvents = 'none'; resendLink.textContent = 'Enviando…'; }
    try {
      await api('/auth/verify-email/send', { method: 'POST', body: {} });
      sentMsg.textContent = '✓ Código enviado para ' + emailMasked + '. Confira a caixa de entrada (e spam).';
      stepSend.style.display = 'none';
      stepInput.style.display = 'block';
      setTimeout(() => codeInput.focus(), 50);
    } catch (err) {
      if (err.status === 429) showErr('Aguarde alguns segundos antes de pedir novo código.');
      else if (err.status === 404) showErr('Endpoint indisponível neste servidor.');
      else showErr(err.message || 'Falha ao enviar código.');
    } finally {
      if (btn === sendBtn) { sendBtn.disabled = false; sendBtn.textContent = origText; }
      else { resendLink.style.opacity = ''; resendLink.style.pointerEvents = ''; resendLink.textContent = origText; }
    }
  }
  sendBtn.addEventListener('click', () => sendCode(false));
  resendLink.addEventListener('click', (e) => { e.preventDefault(); sendCode(true); });

  async function submitCode() {
    clearErr();
    const code = (codeInput.value || '').trim();
    if (!/^\d{6}$/.test(code)) { showErr('Digite os 6 dígitos do código.'); return; }
    confirmBtn.disabled = true; confirmBtn.textContent = 'Verificando…';
    try {
      const r = await api('/auth/verify-email', { method: 'POST', body: { code } });
      const fresh = r && (r.user || r);
      if (fresh && (fresh.email_verified_at || fresh.email_verified)) {
        Session.set({ token: Session.token(), user: fresh });
      } else {
        const cur = Session.user() || {};
        cur.email_verified_at = new Date().toISOString();
        cur.email_verified = true;
        Session.set({ token: Session.token(), user: cur });
      }
      toast('Email confirmado! Seguindo pra compra…', 'success');
      close();
      if (typeof onSuccess === 'function') onSuccess();
    } catch (err) {
      const c = err.data && err.data.code;
      if (c === 'wrong_code') showErr('Código incorreto. Confira o email.');
      else if (c === 'code_expired' || c === 'token_expired') showErr('Código expirou. Reenvie um novo.');
      else if (c === 'too_many_attempts') showErr('Tentativas excedidas. Reenvie um novo código.');
      else showErr(err.message || 'Falha ao verificar.');
      confirmBtn.disabled = false; confirmBtn.textContent = 'Verificar e continuar';
    }
  }
  confirmBtn.addEventListener('click', submitCode);
  codeInput.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') submitCode(); });
  codeInput.addEventListener('input', () => {
    const v = (codeInput.value || '').replace(/\D/g, '').slice(0, 6);
    codeInput.value = v;
    if (v.length === 6) submitCode();
  });
  sendBtn.focus();
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
