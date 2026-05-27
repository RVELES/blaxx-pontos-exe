/* Admin · script da página /admin
 *
 * Liga a tabela e os toggles VIP ao backend /admin/* (precisa user.role==='admin').
 * Sem framework, sem dependências — só fetch + DOM puro.
 */
(function () {
  'use strict';

  var API = window.BLAXX_API || location.origin;
  var TOKEN = sessionStorage.getItem('blaxx_token');
  var USER = (function () {
    try { return JSON.parse(sessionStorage.getItem('blaxx_user') || 'null'); }
    catch (e) { return null; }
  })();

  // ── Guard ──────────────────────────────────────────────────────────────
  if (!TOKEN || !USER) {
    location.href = '/login';
    return;
  }
  if (USER.role !== 'admin') {
    // Não-admin tentando acessar /admin: manda pra dashboard
    alert('Acesso restrito. Apenas administradores.');
    location.href = '/dashboard';
    return;
  }

  document.getElementById('admin-name').textContent = (USER.name || '').split(' ')[0];

  // ── Helpers ────────────────────────────────────────────────────────────
  function api(path, opts) {
    opts = opts || {};
    var headers = Object.assign({ 'Content-Type': 'application/json',
                                  'Authorization': 'Bearer ' + TOKEN },
                                opts.headers || {});
    return fetch(API + path, Object.assign({}, opts, { headers: headers })).then(function (res) {
      return res.text().then(function (raw) {
        var data;
        try { data = raw ? JSON.parse(raw) : {}; }
        catch (e) { throw new Error('Servidor respondeu HTTP ' + res.status + ' não-JSON'); }
        if (!res.ok) {
          var err = new Error(data.error || ('HTTP ' + res.status));
          err.status = res.status; err.data = data;
          throw err;
        }
        return data;
      });
    });
  }

  function fmt(n) { return Number(n || 0).toLocaleString('pt-BR'); }
  function shortDate(iso) {
    if (!iso) return '—';
    var d = new Date(iso);
    return d.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
  }

  // ── Stats (KPIs no topo) ───────────────────────────────────────────────
  function loadStats() {
    api('/admin/stats').then(function (s) {
      var grid = document.getElementById('stats-grid');
      var vol = s.volume_last_30d_by_type || {};
      var totalVol = Object.keys(vol).reduce(function (acc, k) { return acc + (vol[k] || 0); }, 0);
      grid.innerHTML = [
        kpi('Usuários', fmt(s.total_users), 'cadastrados no total'),
        kpi('Admins', fmt(s.total_admins), 'com acesso ao painel'),
        kpi('VIPs', fmt(s.total_vips), 'sem limite diário'),
        kpi('E-mail verificado', fmt(s.email_verified_users), 'usuários ativos'),
        kpi('Saldo total', fmt(s.total_balance_pts) + ' pts', 'pontos em circulação'),
        kpi('Volume 30d', fmt(totalVol) + ' pts', 'movimentado'),
      ].join('');
    }).catch(function (e) {
      console.error('stats:', e);
    });
  }
  function kpi(label, value, subtitle) {
    return '<div class="stat-card">' +
      '<div class="label">' + label + '</div>' +
      '<div class="value">' + value + '</div>' +
      '<div class="subtitle">' + subtitle + '</div>' +
      '</div>';
  }

  // ── Users tab ──────────────────────────────────────────────────────────
  var USERS_PAGE = 0;
  var USERS_LIMIT = 25;
  var USERS_TOTAL = 0;
  var _debounce;

  window.debouncedLoadUsers = function () {
    clearTimeout(_debounce);
    _debounce = setTimeout(function () { USERS_PAGE = 0; loadUsers(); }, 300);
  };

  window.loadUsers = function () {
    var q = document.getElementById('user-search').value.trim();
    var role = document.getElementById('user-role-filter').value;
    var vip = document.getElementById('user-vip-filter').value;
    var params = ['limit=' + USERS_LIMIT, 'offset=' + (USERS_PAGE * USERS_LIMIT)];
    if (q) params.push('q=' + encodeURIComponent(q));
    if (role) params.push('role=' + role);
    if (vip) params.push('vip=' + vip);

    api('/admin/users?' + params.join('&')).then(function (r) {
      USERS_TOTAL = r.total;
      var tbody = document.getElementById('users-tbody');
      if (!r.items.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="empty-state">Nenhum usuário encontrado.</td></tr>';
      } else {
        tbody.innerHTML = r.items.map(renderUserRow).join('');
      }
      document.getElementById('users-info').textContent =
        'Mostrando ' + (r.items.length ? (USERS_PAGE * USERS_LIMIT + 1) : 0) +
        '–' + (USERS_PAGE * USERS_LIMIT + r.items.length) + ' de ' + USERS_TOTAL;
      document.getElementById('users-prev').disabled = USERS_PAGE === 0;
      document.getElementById('users-next').disabled = (USERS_PAGE + 1) * USERS_LIMIT >= USERS_TOTAL;
    }).catch(function (e) {
      console.error('loadUsers:', e);
      document.getElementById('users-tbody').innerHTML =
        '<tr><td colspan="6" class="empty-state">Erro ao carregar: ' + e.message + '</td></tr>';
    });
  };

  function renderUserRow(u) {
    var roleBadge = u.role === 'admin' ? '<span class="badge admin">ADMIN</span> ' : '';
    var vipBadge = u.is_vip ? '<span class="badge vip">VIP</span> ' : '';
    var verifBadge = u.email_verified
      ? '<span class="badge verified">✓ verificado</span>'
      : '<span class="badge unverified">não verificado</span>';
    return '<tr>' +
      '<td>' + roleBadge + escapeHtml(u.name) + '</td>' +
      '<td>' + escapeHtml(u.email) + '</td>' +
      '<td>' + escapeHtml(u.cpf || '—') + '</td>' +
      '<td>' + fmt(u.balance_pts) + ' pts</td>' +
      '<td>' + vipBadge + verifBadge + '</td>' +
      '<td style="text-align:center;">' +
        '<label class="vip-toggle">' +
        '<input type="checkbox" ' + (u.is_vip ? 'checked' : '') +
        ' onchange="toggleVip(\'' + u.id + '\', this.checked, this)">' +
        '<span class="slider"></span>' +
        '</label>' +
      '</td>' +
      '</tr>';
  }

  function escapeHtml(s) {
    return String(s || '').replace(/[&<>"']/g, function (c) {
      return { '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":"&#39;" }[c];
    });
  }

  window.toggleVip = function (userId, newValue, checkbox) {
    api('/admin/users/' + userId + '/vip', {
      method: 'PATCH',
      body: JSON.stringify({ is_vip: newValue }),
    }).then(function (r) {
      loadStats(); // atualiza contador de VIPs
    }).catch(function (e) {
      // Reverte UI em caso de erro
      checkbox.checked = !newValue;
      alert('Falha ao atualizar VIP: ' + e.message);
    });
  };

  window.changePage = function (delta) {
    USERS_PAGE = Math.max(0, USERS_PAGE + delta);
    loadUsers();
  };

  // ── Transactions tab ───────────────────────────────────────────────────
  var TX_PAGE = 0;
  var TX_LIMIT = 50;
  var TX_TOTAL = 0;

  window.loadTransactions = function () {
    var type = document.getElementById('tx-type-filter').value;
    var params = ['limit=' + TX_LIMIT, 'offset=' + (TX_PAGE * TX_LIMIT)];
    if (type) params.push('type=' + type);

    api('/admin/transactions?' + params.join('&')).then(function (r) {
      TX_TOTAL = r.total;
      var tbody = document.getElementById('tx-tbody');
      if (!r.items.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="empty-state">Nenhuma transação.</td></tr>';
      } else {
        tbody.innerHTML = r.items.map(function (t) {
          var sign = t.amount_pts > 0 ? 'pos' : 'neg';
          var prefix = t.amount_pts > 0 ? '+' : '';
          return '<tr>' +
            '<td>' + shortDate(t.created_at) + '</td>' +
            '<td>' + escapeHtml(t.user_name || '—') + '<br><small style="color:#8a918a;">' + escapeHtml(t.user_email || '') + '</small></td>' +
            '<td>' + escapeHtml(t.type) + '</td>' +
            '<td>' + escapeHtml(t.description || '—') + '</td>' +
            '<td style="text-align:right;" class="tx-amount ' + sign + '">' + prefix + fmt(t.amount_pts) + '</td>' +
            '</tr>';
        }).join('');
      }
      document.getElementById('tx-info').textContent =
        'Mostrando ' + (r.items.length ? (TX_PAGE * TX_LIMIT + 1) : 0) +
        '–' + (TX_PAGE * TX_LIMIT + r.items.length) + ' de ' + TX_TOTAL;
      document.getElementById('tx-prev').disabled = TX_PAGE === 0;
      document.getElementById('tx-next').disabled = (TX_PAGE + 1) * TX_LIMIT >= TX_TOTAL;
    }).catch(function (e) {
      console.error('loadTransactions:', e);
    });
  };

  window.changeTxPage = function (delta) {
    TX_PAGE = Math.max(0, TX_PAGE + delta);
    loadTransactions();
  };

  // ── Tabs ───────────────────────────────────────────────────────────────
  window.switchTab = function (tab) {
    document.querySelectorAll('.tab-row button').forEach(function (b) {
      b.classList.toggle('active', b.dataset.tab === tab);
    });
    document.getElementById('tab-users').style.display = tab === 'users' ? '' : 'none';
    document.getElementById('tab-transactions').style.display = tab === 'transactions' ? '' : 'none';
    if (tab === 'transactions' && TX_TOTAL === 0) loadTransactions();
  };

  window.adminLogout = function () {
    sessionStorage.clear();
    location.href = '/login';
  };

  // ── Boot ───────────────────────────────────────────────────────────────
  loadStats();
  loadUsers();
})();
