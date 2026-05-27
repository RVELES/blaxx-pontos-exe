/* Comprar pontos · valor livre · fluxo PIX (EXE).
 *
 * Adaptado pra o EXE renderer com:
 *  - Pre-check de auth via Session (sem token → go('login.html'))
 *  - Detecta 401 mid-flow e limpa storage
 *  - Polling com timeout duro de 30 min
 *  - Erros inline (sem alert)
 *  - Botão "Cancelar e voltar" no step-2
 *  - Race do DOMContentLoaded resolvido (checa readyState)
 *
 * NOTA: aqui usamos /pix/custom-charge + /claim-paid (fluxo manual com
 * confirmação admin) — o backend do EXE pode ainda não ter MP webhook.
 * Se o backend tiver MP automático, basta trocar pra /pix/charge.
 */
(function () {
  'use strict';

  // app.js já está carregado antes (script tag na ordem do <body>),
  // então Session, api, go, toast estão disponíveis no window.
  if (!Session || !Session.token || !Session.token()) {
    if (typeof go === 'function') go('login.html');
    else location.href = 'login.html';
    return;
  }

  var POLL_INTERVAL_MS = 10000;
  var POLL_MAX_DURATION_MS = 30 * 60 * 1000; // 30 min
  var CENTS_PER_POINT = 9;

  var currentCharge = null;
  var pollHandle = null;
  var pollStartedAt = 0;

  function fmtBRL(v) {
    return 'R$ ' + Number(v || 0).toFixed(2).replace('.', ',');
  }

  function parseInputAmount(str) {
    var clean = String(str || '').replace(/[^\d,.-]/g, '').replace(',', '.');
    var n = parseFloat(clean);
    return isFinite(n) && n > 0 ? n : 0;
  }

  // ---- UI helpers ----
  function showInlineError(msg) {
    var step2 = document.getElementById('step-2');
    var host = (step2 && step2.style.display !== 'none') ? step2 : document.querySelector('.buy-wrap') || document.body;
    var box = document.getElementById('bx-err-box');
    if (!box) {
      box = document.createElement('div');
      box.id = 'bx-err-box';
      box.style.cssText = 'margin-top:14px;padding:12px 14px;border-radius:10px;font-size:14px;font-weight:600;background:rgba(255,107,107,0.12);color:#ff6b6b;';
      host.appendChild(box);
    }
    box.textContent = msg;
  }
  function clearInlineError() {
    var box = document.getElementById('bx-err-box');
    if (box) box.remove();
  }
  function setStatusPill(text, kind) {
    var pill = document.getElementById('status-pill');
    if (!pill) return;
    pill.className = 'status-pill status-' + (kind || 'confirming');
    pill.textContent = text;
  }

  // ---- Etapa 1 — valor digitado ----
  window.onAmountChange = function (val) {
    var amount = parseInputAmount(val);
    var cents = Math.round(amount * 100);
    var pts = Math.floor(cents / CENTS_PER_POINT);
    var ptsEl = document.getElementById('points-preview');
    if (ptsEl) ptsEl.textContent = pts.toLocaleString('pt-BR');
    var btn = document.getElementById('btn-create');
    if (btn) btn.disabled = amount < 10;
  };

  window.createCharge = async function () {
    clearInlineError();
    var amount = parseInputAmount(document.getElementById('amount-input').value);
    if (amount < 10) {
      showInlineError('Valor mínimo: R$ 10,00');
      return;
    }

    // Email verificado e' pre-requisito da /pix/custom-charge. Se nao for,
    // mostra modal de verificacao e re-tenta createCharge ao sucesso.
    if (typeof requireEmailVerifiedThen === 'function') {
      var u = Session.user && Session.user();
      if (u && !u.email_verified_at && !u.email_verified) {
        requireEmailVerifiedThen(function () { window.createCharge(); });
        return;
      }
    }

    var btn = document.getElementById('btn-create');
    var orig = btn ? btn.textContent : '';
    if (btn) { btn.disabled = true; btn.textContent = 'Gerando QR…'; }

    try {
      var charge = await api('/pix/custom-charge', {
        method: 'POST',
        body: { amount_brl: amount }
      });
      currentCharge = charge;
      showStep2(charge);
    } catch (e) {
      if (e && e.status === 401) {
        Session.clear();
        if (typeof go === 'function') go('login.html');
        return;
      }
      showInlineError(e.message || 'Falha ao gerar QR Code');
      if (btn) { btn.disabled = false; btn.textContent = orig; }
    }
  };

  function showStep2(charge) {
    var step1 = document.getElementById('step-1');
    var step2 = document.getElementById('step-2');
    if (step1) step1.style.display = 'none';
    if (step2) step2.style.display = 'block';

    var amtEl = document.getElementById('pix-amount-display');
    if (amtEl) amtEl.textContent = fmtBRL(charge.amount_brl);

    var img = document.getElementById('qr-img');
    if (img) {
      // Usa QR real se vier do backend, senão fallback estático
      if (charge.qr_code_image) {
        img.src = charge.qr_code_image;
        img.style.display = 'block';
      } else {
        // Fallback: imagem estática do EXE
        img.src = (window.API_URL ? window.API_URL : '') + '/static/pix-qr-blaxx.png';
        img.style.display = 'block';
      }
    }

    // BR Code copia-e-cola se disponível
    if (charge.br_code) {
      var qrBox = document.querySelector('#step-2 .qr-box') || step2;
      var brBox = document.getElementById('br-code-box');
      if (!brBox && qrBox) {
        brBox = document.createElement('div');
        brBox.id = 'br-code-box';
        brBox.style.cssText = 'margin-top:16px;text-align:left;';
        brBox.innerHTML =
          '<div style="font-size:12px;opacity:0.6;margin-bottom:6px;">Ou copie o código PIX:</div>' +
          '<div style="display:flex;gap:8px;align-items:stretch;">' +
            '<textarea id="br-code-text" readonly style="flex:1;height:64px;font-family:ui-monospace,monospace;font-size:11px;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);border-radius:8px;padding:8px;resize:none;color:inherit;"></textarea>' +
            '<button id="br-code-copy" class="btn ghost" type="button" style="white-space:nowrap;">Copiar</button>' +
          '</div>';
        qrBox.appendChild(brBox);
        document.getElementById('br-code-copy').addEventListener('click', function () {
          var ta = document.getElementById('br-code-text');
          ta.select();
          try {
            document.execCommand('copy');
            this.textContent = '✓ Copiado';
            var self = this;
            setTimeout(function () { self.textContent = 'Copiar'; }, 2000);
          } catch (e) { /* silent */ }
        });
      }
      var brText = document.getElementById('br-code-text');
      if (brText) brText.value = charge.br_code;
    }

    // Botão Cancelar/Voltar
    var cancelBtn = document.getElementById('bx-cancel');
    if (!cancelBtn && step2) {
      cancelBtn = document.createElement('button');
      cancelBtn.id = 'bx-cancel';
      cancelBtn.type = 'button';
      cancelBtn.className = 'btn ghost block';
      cancelBtn.style.marginTop = '14px';
      cancelBtn.textContent = '← Cancelar e voltar';
      cancelBtn.addEventListener('click', function () {
        if (pollHandle) { clearInterval(pollHandle); pollHandle = null; }
        step2.style.display = 'none';
        if (step1) step1.style.display = 'block';
        var amtInp = document.getElementById('amount-input');
        if (amtInp) { amtInp.value = ''; window.onAmountChange(''); }
        clearInlineError();
        currentCharge = null;
      });
      step2.appendChild(cancelBtn);
    }

    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  window.claimPaid = async function () {
    if (!currentCharge) return;
    var btn = document.getElementById('btn-claim');
    if (btn) { btn.disabled = true; btn.textContent = 'Enviando…'; }
    try {
      await api('/pix/custom-charge/' + currentCharge.id + '/claim-paid', {
        method: 'POST',
        body: {}
      });
      document.getElementById('step-2').style.display = 'none';
      var s3 = document.getElementById('step-3');
      if (s3) s3.style.display = 'block';
      startPolling(currentCharge.id);
    } catch (e) {
      if (e && e.status === 401) { Session.clear(); if (typeof go === 'function') go('login.html'); return; }
      showInlineError(e.message || 'Falha ao notificar pagamento');
      if (btn) { btn.disabled = false; btn.textContent = 'Já paguei pelo banco'; }
    }
  };

  // Polling com timeout duro de 30 min e tratamento de status final
  function startPolling(chargeId) {
    if (pollHandle) clearInterval(pollHandle);
    pollStartedAt = Date.now();
    pollHandle = setInterval(async function () {
      if (Date.now() - pollStartedAt > POLL_MAX_DURATION_MS) {
        clearInterval(pollHandle); pollHandle = null;
        setStatusPill('⏱ QR expirado', 'rejected');
        showInlineError('O QR expirou. Volte e gere uma nova cobrança.');
        return;
      }
      try {
        var r = await api('/pix/my-charges');
        var c = (r.items || []).find(function (x) { return x.id === chargeId; });
        if (!c) return;
        if (c.status === 'paid') {
          clearInterval(pollHandle); pollHandle = null;
          setStatusPill('✓ Pontos liberados!', 'paid');
          setTimeout(function () {
            if (typeof go === 'function') go('carteira.html'); else location.href = 'carteira.html';
          }, 2000);
        } else if (c.status === 'rejected' || c.status === 'expired') {
          clearInterval(pollHandle); pollHandle = null;
          setStatusPill(c.status === 'expired' ? '⏱ Expirado' : '✗ Rejeitado', 'rejected');
          showInlineError(
            c.status === 'expired'
              ? 'Esta cobrança expirou. Gere uma nova.'
              : 'O pagamento foi rejeitado. Tente novamente.'
          );
        }
      } catch (e) {
        if (e && e.status === 401) {
          clearInterval(pollHandle); pollHandle = null;
          Session.clear();
          if (typeof go === 'function') go('login.html');
        }
        // outros erros: retry silencioso no próximo tick
      }
    }, POLL_INTERVAL_MS);
  }

  window.goWallet = function () {
    if (typeof go === 'function') go('carteira.html');
    else location.href = 'carteira.html';
  };

  // Boot — sem race no DOMContentLoaded
  function boot() {
    // No EXE, valor livre não tem auto-pkg (só web tem ?pkg=plus)
    // Mas se quiser estender, basta replicar o pattern.
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
