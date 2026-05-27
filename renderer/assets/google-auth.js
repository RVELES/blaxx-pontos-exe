/**
 * BlaxxGoogleAuth — wrapper unico do fluxo Google Sign-In no app Windows.
 *
 * Reusa-se em login.html e cadastro.html. Faz duas coisas:
 *   1. Pede a bridge Python (`window.pywebview.api.google_sign_in`) que
 *      execute o fluxo OAuth Authorization Code + PKCE. Por padrao a tela
 *      do Google aparece DENTRO do app numa child PyWebView window
 *      (fluxo embedded). A bridge bloqueia ate o usuario completar.
 *      Retorna `{ok:true, id_token, nonce}` ou `{ok:false, error, code}`.
 *   2. Chama o backend Blaxx em `POST /auth/google` com `{id_token, nonce}`,
 *      recebe `{token, user}` e cria a sessao (igual ao login normal).
 *
 * Codigos de erro conhecidos (campo `code` no retorno da bridge):
 *   - NOT_CONFIGURED  : BLAXX_GOOGLE_CLIENT_ID nao definido
 *   - LOOPBACK_BLOCKED: Client ID nao e' Desktop App
 *   - CANCELLED       : usuario fechou a janela do Google
 *   - TIMEOUT         : 5 min sem callback
 *
 * Compativel com o backend ja em producao (mesmo endpoint /auth/google que
 * a Web e o app Mac/iOS usam).
 */
(function (global) {
  'use strict';

  function bridgeAvailable() {
    return !!(global.pywebview
              && global.pywebview.api
              && global.pywebview.api.google_sign_in);
  }

  async function waitForBridge(timeoutMs) {
    if (bridgeAvailable()) return true;
    const start = Date.now();
    while (Date.now() - start < (timeoutMs || 3000)) {
      if (bridgeAvailable()) return true;
      await new Promise((r) => setTimeout(r, 80));
    }
    return bridgeAvailable();
  }

  async function callBridge() {
    const ok = await waitForBridge(3000);
    if (!ok) {
      throw new Error(
        'Bridge Python indisponivel. Abra o app via main.py para usar o Google Login.'
      );
    }
    return global.pywebview.api.google_sign_in();
  }

  /**
   * Monta a mensagem de erro mostrada ao usuario, juntando error + hint +
   * doc_url. Trata cancelamento como mensagem curta (nao e' "erro" tecnico).
   */
  function formatError(oauth) {
    if (!oauth) return 'Falha desconhecida no Google Sign-In';
    if (oauth.code === 'CANCELLED') return 'Login com Google cancelado.';
    if (oauth.code === 'TIMEOUT')   return 'Tempo esgotado. Tente novamente.';

    let reason = oauth.error || 'Falha desconhecida no Google Sign-In';
    if (oauth.hint)    reason += ' · ' + oauth.hint;
    if (oauth.doc_url) reason += ' (' + oauth.doc_url + ')';
    return reason;
  }

  /**
   * Executa o fluxo completo.
   * @param {{onStart?:Function, onSuccess?:(user)=>void,
   *          onError?:(msg)=>void, onCancel?:Function}} cb
   */
  async function signIn(cb) {
    cb = cb || {};
    try {
      if (cb.onStart) cb.onStart();

      const oauth = await callBridge();
      if (!oauth || !oauth.ok) {
        // Cancelamento e' silencioso (so se onCancel estiver definido)
        if (oauth && oauth.code === 'CANCELLED') {
          if (cb.onCancel) cb.onCancel();
          else if (cb.onError) cb.onError(formatError(oauth));
          return null;
        }
        if (cb.onError) cb.onError(formatError(oauth));
        return null;
      }

      // Backend Blaxx valida id_token + nonce e devolve o JWT da sessao
      const data = await api('/auth/google', {
        method: 'POST',
        body: { id_token: oauth.id_token, nonce: oauth.nonce },
      });

      Session.set({ token: data.token, user: data.user });
      if (cb.onSuccess) cb.onSuccess(data.user);
      return data.user;
    } catch (err) {
      const msg = (err && err.message) || 'Falha ao entrar com Google';
      if (cb.onError) cb.onError(msg);
      return null;
    }
  }

  global.BlaxxGoogleAuth = {
    signIn: signIn,
    isBridgeAvailable: bridgeAvailable,
  };
})(window);
