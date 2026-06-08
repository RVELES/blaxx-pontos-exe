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
   * Traduz erros crus do backend no login Google para mensagens amigaveis.
   * O usuario nao deve ver jargao tecnico (ex.: "Token Google invalido ou
   * expirado") que sugere falha na conta dele, quando geralmente e' config do
   * servidor (GOOGLE_WEB_CLIENT_ID/GOOGLE_IOS_CLIENT_ID ausente) ou algo
   * transitorio. Paridade com Session.friendlyGoogleError (Mac/iOS) e
   * friendlyGoogleError (Web SPA).
   */
  function friendlyBackendError(err) {
    var raw = (err && err.message) || '';
    var status = (err && err.status) || 0;
    switch (raw) {
      case 'Token Google inválido ou expirado':
      case 'issuer inválido':
      case 'Token Google sem sub ou email':
        return 'Não foi possível entrar com o Google agora. '
             + 'Tente novamente ou use e-mail e senha.';
      case 'Google Sign-In não está configurado neste servidor':
        return 'Login com Google está temporariamente indisponível. '
             + 'Use e-mail e senha por enquanto.';
      case 'nonce inválido — possível replay':
        return 'A sessão de login expirou. Clique em '
             + '"Entrar com Google" novamente.';
      case 'Sua conta Google não tem e-mail verificado':
        return 'Sua conta Google precisa ter o e-mail verificado '
             + 'para entrar no Blaxx.';
      default:
        if (status >= 500 || status < 0) {
          return 'Serviço indisponível no momento. '
               + 'Tente novamente em alguns instantes.';
        }
        return raw || 'Falha ao entrar com Google.';
    }
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
      const msg = friendlyBackendError(err);
      if (cb.onError) cb.onError(msg);
      return null;
    }
  }

  global.BlaxxGoogleAuth = {
    signIn: signIn,
    isBridgeAvailable: bridgeAvailable,
  };
})(window);
