# Blaxx Pontos · Aplicativo Windows

Aplicativo desktop nativo para Windows 10/11, escrito em Python.
Entrega os mesmos três fluxos centrais do programa Blaxx Pontos:
**compra de pontos via PIX**, **envio P2P entre clientes** e
**resgate via PIX**, mais o catálogo de parceiros, benefícios, campanhas
e o módulo administrativo.

## Banco compartilhado entre todas as plataformas

```
                    ┌─────────────────────────────┐
                    │   Neon PostgreSQL           │
                    │   project: blaxx-pontos     │
                    │   region: gru (São Paulo)   │
                    └──────────────┬──────────────┘
                                   │  (DATABASE_URL secret)
                    ┌──────────────▼──────────────┐
                    │  blaxx-pontos-backend       │
                    │  Flask + Gunicorn @ Fly.io  │
                    │  https://blaxx-pontos-      │
                    │       backend.fly.dev       │
                    └──────────────┬──────────────┘
                                   │ HTTPS + JWT Bearer
       ┌──────────────┬────────────┴────────────┬──────────────┐
       ▼              ▼                         ▼              ▼
 ┌──────────┐  ┌────────────┐         ┌─────────────────┐  ┌──────────┐
 │ Web      │  │ Windows    │         │ macOS Electron  │  │ Mac/iOS  │
 │ Netlify  │  │ PyWebView  │  ←──── │ blaxx_app/      │  │ SwiftUI  │
 │ /blaxx/  │  │ blaxx_exe/ │  novo   │ (legacy shell)  │  │ nativo   │
 └──────────┘  └────────────┘         └─────────────────┘  └──────────┘
```

Todas as plataformas falam com a **mesma URL** (`blaxx-pontos-backend.fly.dev`)
e o **mesmo banco** (Neon Postgres). Um usuário cadastrado pelo Windows
aparece no Mac. Um saldo creditado pelo iOS aparece na Web. Não há
sincronização — não tem o que sincronizar, é tudo o mesmo dado.

## Dois modos de operação

| Modo | Como ativar | Backend | Banco | Renderer | Quando usar |
|---|---|---|---|---|---|
| **Produção (default)** | `python main.py` | Fly.io remoto | Neon Postgres compartilhado | servido pelo backend (`/app/`) | uso normal |
| **Dev local** | `python main.py --local` | Flask embarcado | SQLite isolado em `%APPDATA%` | `file://renderer/` local | desenvolvimento offline ou Fly.io fora do ar |
| **Staging / branch** | `python main.py --backend URL` | URL remoto custom | depende da instância | `URL/app/` | testar pré-produção |

A flag `--local` é exclusivamente para desenvolvimento. **Em uso real, ninguém
deve usar `--local`** — isso cria um banco SQLite separado que não conversa com
as outras plataformas.

## Stack

| Camada | Tecnologia | Observação |
|---|---|---|
| Janela desktop | PyWebView ≥ 5.3 com gui `edgechromium` | novo (Windows) |
| Renderizador | Microsoft Edge WebView2 Runtime | nativo do Windows 10/11 |
| Frontend (prod) | servido por `https://blaxx-pontos-backend.fly.dev/app/` | mesma origem do backend, sem CORS |
| Frontend (dev local) | `renderer/` no disco via file:// | só com `--local` |
| Backend (prod) | Fly.io + Gunicorn + Flask + JWT | único, compartilhado |
| Backend (dev local) | Flask + SQLAlchemy embarcado | só com `--local` |
| Banco (prod) | **Neon PostgreSQL** (1 instância, compartilhada) | configurado em `fly secrets` |
| Banco (dev local) | SQLite em `%APPDATA%\Blaxx Pontos\blaxx.db` | isolado por máquina |
| Empacotador | PyInstaller 6+ | `blaxx_exe.spec` |
| Instalador (opcional) | Inno Setup | `installer.iss` |

## Estrutura

```
blaxx_exe/
├── main.py                 # entrypoint: orquestra tray + Flask + WebView2
├── config.py               # config central (paths, portas, versão, defaults)
├── logging_setup.py        # logging rotativo em %APPDATA%\Blaxx Pontos\logs\
├── backend_runner.py       # start_backend + HealthMonitor (auto-recovery)
├── tray.py                 # ícone na bandeja (pystray) + notificações
├── requirements.txt        # deps Python (pywebview, flask, pystray, …)
├── build.py                # helper para empacotar com PyInstaller
├── blaxx_exe.spec          # spec PyInstaller (modo onedir, recomendado)
├── installer.iss           # Inno Setup (gera .exe instalador)
├── scripts/
│   └── make_icon.py        # gera assets/icon.ico (multi-resolução)
├── assets/
│   ├── icon.ico            # ícone do .exe + tray (gerado por make_icon.py)
│   └── icons/              # PNGs individuais (16/24/32/48/64/128/256)
├── backend/                # Flask + SQLAlchemy (cópia do blaxx_app/backend)
│   ├── run.py
│   ├── seed.py
│   ├── requirements.txt
│   └── app/                # blueprints: auth, wallet, pix, transfer, redeem, …
└── renderer/               # HTML/CSS/JS (cópia adaptada do blaxx_app/renderer)
    ├── index.html          # bootstrap → splash.html
    ├── splash.html         # splash com status real do backend + retry
    ├── assets/
    │   ├── design-system.css
    │   └── app.js          # cliente da API (lê URL de localStorage)
    └── screens/            # 30+ telas (dashboard, comprar, enviar, vender, …)
```

## Componentes do app shell

| Componente | Arquivo | Responsabilidade |
|---|---|---|
| Config central | `config.py` | `CONFIG` singleton: paths, portas, versão. Funciona em dev e empacotado. |
| Logging | `logging_setup.py` | Console + arquivo rotativo (5MB × 5). Silencia bibliotecas barulhentas. |
| Backend runner | `backend_runner.py` | Sobe Flask em thread daemon, seed inicial, `HealthMonitor` em background. |
| Health monitor | `backend_runner.py` → `HealthMonitor` | Polla `/health` a cada 10s. Após 3 falhas seguidas, reinicia o Flask. |
| Tray icon | `tray.py` → `BlaxxTray` | Ícone na bandeja, menu (Abrir, Status, Logs, Sair) + toasts nativos. |
| Janela | `main.py` → `create_main_window` | PyWebView com `gui="edgechromium"` (WebView2). |
| Bridge JS | `main.py` → `BlaxxBridge` | `window.pywebview.api`: `backend_url()`, `notify()`, `versions()`. |
| Splash inteligente | `renderer/splash.html` | Aguarda `/health` antes de redirecionar; mostra erro com retry. |

## Pré-requisitos no Windows

1. **Windows 10** (build 1809+) ou **Windows 11**
2. **Microsoft Edge WebView2 Runtime** — já vem por padrão no Windows 11 e
   no 10 atualizado. Se faltar, baixe o "Evergreen Standalone Installer"
   em https://developer.microsoft.com/microsoft-edge/webview2/
3. **Python 3.11+** (recomendado 3.12) — https://www.python.org/downloads/windows/
   - Marque "Add python.exe to PATH" no instalador
4. **Git** (opcional, mas recomendado)

## Primeira execução

Abra o **PowerShell** na pasta do app:

```powershell
cd "C:\Users\<voce>\Dropbox\Blaxx Pontos\blaxx_exe"

# 1) Cria virtualenv local
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2) Instala dependências
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# 3) Roda o app — modo PRODUÇÃO (banco compartilhado)
python main.py
```

Ao rodar `python main.py` o app:

1. Coloca o ícone Blaxx na bandeja (tray)
2. Faz um ping em `https://blaxx-pontos-backend.fly.dev/health` (timeout 8s)
3. Abre a janela WebView2 em `https://blaxx-pontos-backend.fly.dev/app/`
4. Você cai direto na tela de login do mesmo backend que web/Mac/iOS usam

Os usuários cadastrados via Web/Mac/iOS já aparecem aqui — é o mesmo Neon.
Os dados que você criar aqui aparecem instantaneamente nas outras plataformas.

### Modo dev local (banco isolado)

Se precisar trabalhar offline ou contra um banco isolado:

```powershell
python main.py --local
```

Isso sobe um Flask em `127.0.0.1:5050` com SQLite em `%APPDATA%\Blaxx Pontos\blaxx.db`,
roda o `seed.py` na primeira execução e popula os usuários demo:

| Nome | E-mail | Senha | Saldo | Papel |
|---|---|---|---|---|
| Mariana Costa | `mariana@blaxx.com` | `123456` | 84.750 pts | admin + VIP |
| Lucas Andrade | `lucas@blaxx.com`   | `123456` | 5.000 pts  | user |

⚠ **Atenção**: o banco SQLite do `--local` é totalmente isolado. Dados criados
nele não aparecem nas outras plataformas e vice-versa. Use só para desenvolvimento.

### Flags úteis

```powershell
python main.py                                # default: produção (banco compartilhado)
python main.py --local                        # dev local (SQLite isolado)
python main.py --backend https://staging...   # outra instância remota
python main.py --dev                          # + DevTools (F12)
python main.py --no-tray                      # sem ícone na bandeja
python main.py --no-monitor                   # sem health monitor de fundo
```

Para apontar permanentemente para outro backend remoto sem precisar passar a
flag toda vez, defina a variável de ambiente `BLAXX_BACKEND_URL`:

```powershell
$env:BLAXX_BACKEND_URL = "https://staging-blaxx.fly.dev"
python main.py
```

## Tray icon e notificações

Ao subir, o app coloca um ícone na bandeja com menu:

- **Abrir Blaxx Pontos** — traz a janela para o topo (item default).
- **Status: …** — texto atualizado pelo health monitor (Subindo / Online / Backend caiu / Reiniciando).
- **Abrir pasta de logs** — abre `%APPDATA%\Blaxx Pontos\logs\` no Explorer.
- **Abrir dados do app** — abre `%APPDATA%\Blaxx Pontos\` (onde fica `blaxx.db`).
- **Sair** — encerra o backend, o monitor e o tray graciosamente.

Toasts nativos do Windows são disparados quando o backend reconecta após cair.
Para silenciar o tray inteiramente, rode com `--no-tray`.

## Health monitor

Em paralelo à janela, uma thread daemon (`HealthMonitor`) consulta o
`/health` do backend (local ou remoto) a cada **10s**.

| Setting | Default | Significado |
|---|---|---|
| `health_check_interval_s` | 10s | Pausa entre checks |
| `health_failure_threshold` | 3 | Falhas consecutivas → ação |
| `health_timeout_s` | 20s | Timeout do ping inicial (modo local) |
| `remote_health_timeout_s` | 8s | Timeout do ping inicial (modo remoto) |

Comportamento por modo:

- **Modo remoto (default)**: o monitor **observa** apenas. Se cai, atualiza
  o status do tray e dispara um toast "Backend remoto fora do ar — verifique
  sua internet". Quando volta, dispara "Backend remoto recuperou". Não tenta
  reiniciar (não temos controle sobre Fly.io daqui).
- **Modo `--local`**: além de observar, **tenta auto-restart** do Flask
  embarcado quando o threshold é atingido. Cria uma nova thread daemon e
  espera o novo `/health` responder em até 10s.

Falhas e recoveries são todos registrados em `%APPDATA%\Blaxx Pontos\logs\app.log`.

## Logs

Console (stderr) + arquivo rotativo em
`%APPDATA%\Blaxx Pontos\logs\app.log`. Rotaciona ao chegar em 5 MB,
mantém os 5 arquivos mais recentes.

Para mudar o nível: `set BLAXX_LOG_LEVEL=DEBUG && python main.py`.

## Ícone

`assets/icon.ico` é gerado por `scripts/make_icon.py` (preto + verde-limão
Blaxx, multi-resolução: 16/24/32/48/64/128/256). Para regerar:

```powershell
python scripts/make_icon.py
```

Se substituir por uma versão profissional, basta sobrescrever
`assets/icon.ico` — `main.py`, `tray.py` e `blaxx_exe.spec` apontam para ele.

## Gerar o `.exe` para distribuir

```powershell
.\.venv\Scripts\Activate.ps1
python build.py
```

Saída em `dist/BlaxxPontos/`:

```
dist/BlaxxPontos/
├── BlaxxPontos.exe            ← arrastar para o desktop ou empacotar no instalador
├── python311.dll
├── _internal/                 ← libs Python, Flask, SQLAlchemy, etc.
└── renderer/, backend/        ← assets embarcados
```

Flags do `build.py`:

```powershell
python build.py --onefile      # 1 .exe único (~100 MB, abertura mais lenta)
python build.py --installer    # roda Inno Setup depois (precisa de iscc no PATH)
```

### Instalador Inno Setup (opcional, recomendado)

Para entregar um setup `.exe` profissional ao usuário final:

1. Instale o Inno Setup: https://jrsoftware.org/isdl.php
2. Garanta que `iscc.exe` está no PATH (geralmente `C:\Program Files (x86)\Inno Setup 6\`)
3. Rode:

```powershell
python build.py --installer
```

Saída: `dist/installer/BlaxxPontos-0.1.0-setup.exe` — entrega esse arquivo
ao usuário. Ele faz "Next, Next, Finish" e ganha atalho no Menu Iniciar +
desinstalador automático.

## Variáveis de ambiente

No **modo padrão (produção)** o app só precisa de uma:

| Var | Default | Uso |
|---|---|---|
| `BLAXX_BACKEND_URL` | `https://blaxx-pontos-backend.fly.dev` | URL do backend remoto compartilhado |
| `BLAXX_LOG_LEVEL` | `INFO` | nível de log: DEBUG, INFO, WARNING, ERROR |

No **modo `--local`** (dev), o Flask embarcado lê todas as variáveis do
backend tradicional (mesmas do `blaxx_app/`):

| Var | Default local | Uso |
|---|---|---|
| `BLAXX_BACKEND_HOST` | `127.0.0.1` | host onde o Flask local escuta |
| `BLAXX_BACKEND_PORT` | `5050` | porta do Flask local |
| `DATABASE_URL` | `sqlite:///%APPDATA%/Blaxx Pontos/blaxx.db` | banco local |
| `SECRET_KEY` | aleatório por sessão | assinatura Flask |
| `JWT_SECRET_KEY` | igual SECRET_KEY | assinatura JWT |
| `PIX_PROVIDER` | `mock` | `mock` ou `mercadopago` |
| `MP_ACCESS_TOKEN` | — | token Mercado Pago se PIX_PROVIDER=mercadopago |
| `CORS_ORIGINS` | `*` | origens autorizadas no Flask local |

Note que `DATABASE_URL` no modo `--local` pode ser apontada para o **Neon
Postgres compartilhado** se você quiser rodar o Flask local mas usar o banco
de produção (caso raro, útil para testar mudanças no backend contra dados
reais):

```powershell
$env:DATABASE_URL = "postgresql+psycopg://user:senha@host/blaxx?sslmode=require"
python main.py --local
```

## Google Sign-In nativo

O app Windows tem o botão "Entrar com Google" / "Cadastrar com Google" igual
ao site Netlify e o app Mac. O fluxo é implementado em Python no arquivo
`google_auth.py`, seguindo o padrão **Authorization Code Flow + PKCE** com
**loopback redirect** (RFC 8252 "OAuth 2.0 for Native Apps"), que é o método
oficial recomendado pelo Google para apps desktop.

### Passo a passo do que acontece

1. Usuário clica no botão Google em `login.html` ou `cadastro.html`.
2. JS chama `window.pywebview.api.google_sign_in()` (bridge para o Python).
3. Python (`google_auth.sign_in`) gera `code_verifier`, `code_challenge`
   (S256), `state` (CSRF) e `nonce` (anti-replay).
4. Python sobe um servidor HTTP em `127.0.0.1:<porta-livre>/callback` em
   thread daemon.
5. Python abre o navegador padrão do Windows em
   `https://accounts.google.com/o/oauth2/v2/auth?...` (PKCE + state + nonce).
6. Usuário escolhe a conta no Google, autoriza.
7. Google redireciona para `http://127.0.0.1:<porta>/callback?code=...&state=...`.
8. O handler captura o `code`, valida o `state` e fecha o servidor.
9. Python faz `POST https://oauth2.googleapis.com/token` com
   `code + code_verifier`, recebe o `id_token` JWT assinado pelo Google.
10. Retorna `{ok, id_token, nonce}` para o JS.
11. JS chama `POST /auth/google` no backend Blaxx com `{id_token, nonce}`.
12. Backend valida JWT (assinatura + audience + nonce), cria/linka usuário,
    devolve `{token, user}` — JWT da sessão Blaxx.
13. JS guarda a sessão e redireciona para `dashboard.html`.

O endpoint `/auth/google` é exatamente o mesmo usado pela Web Netlify e pelo
app Mac/iOS — não há código duplicado no backend, todas as plataformas
compartilham a mesma lógica de validação.

### Configuração do OAuth Client (obrigatória)

**Atenção**: Windows precisa de um OAuth Client tipo **"Desktop application"**.
Clients iOS, Android, Chrome e Web NÃO funcionam com este fluxo:

- **iOS/Android/Chrome**: Google **bloqueou o loopback flow em 2022** ([loopback
  migration guide](https://developers.google.com/identity/protocols/oauth2/resources/loopback-migration)).
  Tentar usar dá `Error 400: invalid_request - The loopback flow has been blocked`.
- **Web**: exige `client_secret` embarcado (não-seguro) e listar cada porta
  manualmente.
- **Desktop app**: aceita qualquer porta loopback automaticamente, sem secret,
  sem listar URIs. É o tipo certo para apps Windows/Mac/Linux.

Por isso o app **não tem Client ID default** — você precisa criar um.

**Passo a passo:**

1. https://console.cloud.google.com → projeto Blaxx Pontos → APIs e serviços
   → Credenciais (ou direto em https://console.cloud.google.com/apis/credentials)
2. **Criar credenciais → ID do cliente OAuth**
3. Tipo de aplicativo: **Desktop app** (não escolha iOS, Android nem Web)
4. Nome: `Blaxx Windows` (ou o que preferir)
5. Não pede "URIs de redirecionamento" — Desktop app aceita loopback
   automaticamente em qualquer porta
6. **Criar** → copie o **Client ID** que aparece (sem secret no Desktop app)
7. Configure no app antes de rodar:

   ```powershell
   $env:BLAXX_GOOGLE_CLIENT_ID = "123456789-xxxxx.apps.googleusercontent.com"
   python main.py
   ```

   Para persistir entre sessões, defina como variável permanente:
   ```powershell
   [System.Environment]::SetEnvironmentVariable(
       'BLAXX_GOOGLE_CLIENT_ID',
       '123456789-xxxxx.apps.googleusercontent.com',
       'User'
   )
   ```

8. **Backend (obrigatório)**: adicione este Client ID à lista de audiences
   aceitas pelo backend Fly.io. No `app/config.py`:

   ```python
   GOOGLE_DESKTOP_CLIENT_ID = os.environ.get("GOOGLE_DESKTOP_CLIENT_ID", "")
   ```

   E no método `google_allowed_audiences`:
   ```python
   return [a for a in (cls.GOOGLE_WEB_CLIENT_ID,
                       cls.GOOGLE_IOS_CLIENT_ID,
                       cls.GOOGLE_DESKTOP_CLIENT_ID) if a]
   ```

   Daí no Fly.io:
   ```bash
   fly secrets set GOOGLE_DESKTOP_CLIENT_ID="123456789-xxxxx.apps.googleusercontent.com"
   fly deploy
   ```

   Sem isso o backend rejeita o id_token com **"audience inválida"** (401).

### Se aparecer `Error 400: invalid_request`

A mensagem do Google será uma destas:

- **"The loopback flow has been blocked"** — você usou um Client ID iOS,
  Android ou Chrome. Crie um Client tipo **Desktop app** (passos acima).
- **"redirect_uri_mismatch"** — você usou um Client tipo **Web** sem listar
  a URI exata `http://127.0.0.1:<porta>/callback`. Troque pro tipo Desktop.

O app detecta esses erros e mostra dica direta no toast.

### Por que loopback IP e não custom URI scheme?

Custom URI schemes no Windows (tipo `com.blaxx.pontos://callback`) exigem
registro no registry do Windows + permissões de instalação. O loopback é
mais simples, é o método recomendado pelo Google para apps desktop, e
funciona sem privilégios elevados. Cada execução pega uma porta livre
diferente — não há conflito mesmo se o usuário tiver outros apps.

### Diferenças entre as 3 implementações de Google Login

| Plataforma | Implementação | SDK |
|---|---|---|
| Web (Netlify) | Google Identity Services (botão renderizado pelo SDK) | `https://accounts.google.com/gsi/client` |
| Mac/iOS | `ASWebAuthenticationSession` + PKCE | SO nativo |
| **Windows** | **navegador padrão + HTTP loopback + PKCE** | **stdlib Python (sem SDK)** |

Todas geram um `id_token` JWT que vai para o **mesmo endpoint** `POST /auth/google`.

## Fluxos suportados

O renderer e backend são idênticos ao `blaxx_app/`. Logo, todas as telas e
endpoints do macOS funcionam aqui:

- **Auth**: login (email/CPF + senha), cadastro, recuperar senha, Google OAuth
- **Compra PIX**: `comprar-pontos` → `checkout` → `pagamento-pix` (QR + copia-e-cola) → `compra-aprovada`
- **Envio P2P**: `enviar-pontos` → `confirmar-envio` → `envio-concluido` (`ENV-2026-XXXX-XXXX`)
- **Resgate PIX**: `vender-pontos` → `resgate-pix` (chave + senha) → `resgate-concluido`
  - Chaves começando com `fail-` simulam falha do gateway (estorno automático)
- **Catálogo**: parceiros, benefícios, vouchers, campanhas
- **Conta**: perfil, MFA, troca de senha, indique-e-ganhe, excluir conta
- **Admin** (role=admin): confirmar PIX manual, gestão de usuários, audit log

## Diferenças do app macOS

| Item | macOS (Electron) | Windows (PyWebView) |
|---|---|---|
| Shell | Electron (Chromium embarcado) | WebView2 (Edge instalado no SO) |
| Runtime | Node.js + Python | Python apenas |
| Tamanho `.exe` | ~250 MB | ~80-100 MB |
| Inicialização | 2-3s | 1-2s |
| Janela | `titleBarStyle: 'hiddenInset'` | barra padrão Windows |
| Ícone | `.icns` | `.ico` |

A interface e os dados são idênticos.

## Troubleshooting

**"WebView2 is not available"** — Instale o WebView2 Runtime (link no início).

**Tela mostra "Sem conexão com backend remoto"** — internet caiu ou o Fly.io
está fora do ar. Cheque `https://blaxx-pontos-backend.fly.dev/health` no
navegador. Como fallback temporário, use `python main.py --local` para
trabalhar com banco isolado.

**No modo `--local`, "Backend não respondeu em /health"** — Porta 5050
ocupada por outro app. Solução: `$env:BLAXX_BACKEND_PORT="5060"; python main.py --local`.

**"Cannot find module 'app'"** — virtualenv não ativada. Execute
`.\.venv\Scripts\Activate.ps1` antes do `python main.py`.

**Login funciona mas dashboard mostra "Falha ao carregar saldo"** — abra
F12 com `python main.py --dev` e veja se as chamadas vão para a URL certa.
Se você alternou entre `--local` e produção, limpe o localStorage do app:
`localStorage.clear()` no console do DevTools.

**Cadastrei um usuário no modo `--local` e ele não aparece na Web** — Esperado.
O `--local` usa SQLite isolado. Para que apareça em todas as plataformas,
rode no modo padrão (`python main.py`) e cadastre o usuário no backend
remoto compartilhado.

**Vejo dados diferentes entre Windows e Mac** — você está em modo `--local`
ou apontando para outro `--backend URL`. Rode `python main.py` (sem flags)
para garantir que ambos usem o mesmo backend de produção.

**`.exe` empacotado abre console preto** — Bug no `.spec`: a flag
`console=False` deve estar no bloco `EXE(...)`. Já está configurado.

**`.exe` empacotado fecha sozinho ao abrir** — Falta DLL do Python.
Reinstale o Python com a opção "Install for all users" + "Add to PATH"
e rode `pyinstaller` de novo.

## Roadmap

- [x] Ícone `.ico` (gerado por `scripts/make_icon.py`, substituível por arte definitiva)
- [x] Tray icon com notificações em background (pystray)
- [x] Health monitor + auto-recovery do Flask
- [x] Splash com status em tempo real do backend
- [x] Logging rotativo em arquivo
- [ ] Code signing do `.exe` (certificado EV ou Authenticode)
- [ ] Auto-update embutido (sparkle-like — opção: `pyupdater` ou GitHub releases + verificação manual)
- [ ] Atalho global (Win+B abre o app rapidamente)
- [ ] Modo offline com cache de saldo + sync ao reconectar
- [ ] Quick-actions no tray: "Comprar pontos", "Enviar pontos" abrem a tela direto

Veja `Blaxx_Pontos_Backlog_Tarefas.xlsx` (raiz do projeto) para o backlog
completo — 20 épicos, 143 sub-tarefas, distribuídos em P0/P1/P2.

## Licença

UNLICENSED — uso interno Blaxx. Não distribuir publicamente sem autorização.
