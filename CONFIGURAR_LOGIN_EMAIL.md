## Atualização: entrada e carregamento

O endereço inicial `/` sempre mostra Entrar com Microsoft, mesmo com uma sessão válida. O clique verifica a sessão: se estiver ativa, abre `/carregando`; se não, pede confirmação por código (ou inicia SSO quando esse modo estiver ativo). Após a autenticação, a tela Carregando credenciais apresenta ícone animado e barra durante dez segundos e então abre `/central`. A barra é uma transição visual; a identidade é verificada pelo servidor. Acesso direto às APIs continua protegido.

# Login real por código — Central de Iniciativas CJ

## O que muda

A página mantém o layout enviado e o botão “Entrar com Microsoft”. Ao clicar, pede nome e e-mail corporativo. O texto abaixo esclarece que é acesso por código enviado ao e-mail, e não SSO Microsoft. Sem integração autorizada com o Entra, não há como descobrir a conta Microsoft já conectada no navegador.

Só endereços `@queirozcavalcanti.adv.br` podem pedir código. O código aleatório tem seis dígitos, validade de dez minutos, no máximo cinco tentativas e uma única utilização no navegador que o solicitou. Nome é informado pelo usuário; o acesso à caixa de e-mail é confirmado pelo código.

Após confirmar, esse navegador mantém uma sessão protegida por até 30 dias, inclusive após fechar e abrir o navegador. Não utiliza autenticação fictícia em localStorage. “Sair” revoga a sessão no servidor; outro navegador, modo anônimo, dados apagados ou sessão expirada exigem novo código.

Não altera o banco atual, o catálogo, a senha de admin ou as credenciais do executor Lexio. Cria tabelas adicionais para desafios de login, sessões, usuários e limites. Registra nome, e-mail e data/hora do último login confirmado. Não guarda o código em texto puro ou senha Microsoft.

## 1. Configurar o envio pela Brevo

1. Crie uma conta gratuita em https://www.brevo.com/.
2. Em **Configurações → Remetentes, domínios e IPs**, adicione um remetente com o nome **Central de Iniciativas CJ** e um endereço que você controla e está autorizado a usar.
3. Valide o endereço e siga a autenticação do domínio solicitada pela Brevo. Ela pode exigir registros DNS. Se não tiver acesso ao DNS do domínio QCA, peça essa etapa à TI ou use outro domínio sob seu controle e autorizado para o envio. Não use um domínio ou remetente sem autorização.
4. Confira se a conta está habilitada para envio transacional; o provedor pode pedir validação adicional.
5. Em **SMTP e API → Chaves de API**, crie uma chave de API. Use a chave de API HTTP, não a senha SMTP. Cadastre-a diretamente no Render.

O plano gratuito consultado oferece 300 envios por dia. A Central reserva no máximo 250 solicitações por 24 horas, seis por endereço por hora, 40 por IP por hora, além do intervalo de 60 segundos para reenvio. Uso de outros envios na mesma conta também consome a quota Brevo. Veja https://help.brevo.com/hc/en-us/articles/208589409-About-Brevo-s-pricing-plans.

Usamos HTTPS para envio porque o Render gratuito bloqueia portas SMTP comuns. Documentação: https://render.com/changelog/free-web-services-will-no-longer-allow-outbound-traffic-to-smtp-ports e https://developers.brevo.com/docs/send-a-transactional-email.

## 2. Render — antes de enviar os arquivos

Mantenha as variáveis existentes do banco, admin e robô. Configure:

| Variável | Valor |
|---|---|
| PUBLIC_URL | https://central-de-iniciativas-cj.onrender.com |
| EMAIL_AUTH_ENABLED | true |
| SSO_ENABLED | false |
| BREVO_API_KEY | Chave API HTTP da Brevo |
| EMAIL_FROM | Endereço exato do remetente validado |
| EMAIL_AUTH_SECRET | Segredo aleatório privado com pelo menos 32 caracteres |

Para gerar o segredo usando o Python já instalado para o robô, abra o CMD **na pasta robo** e execute:

```bat
.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

Copie o resultado para `EMAIL_AUTH_SECRET` no Render. Não compartilhe o segredo, a chave API ou códigos de acesso. Nunca inclua esses valores no GitHub. Trocar EMAIL_AUTH_SECRET invalida as sessões lembradas e códigos pendentes.

As variáveis MICROSOFT_TENANT_ID, MICROSOFT_CLIENT_ID e MICROSOFT_CLIENT_SECRET não são usadas neste modo. Não é necessário registrar a aplicação no Entra.

## 3. Arquivos que você precisa atualizar no GitHub

Substitua na raiz:

- `index.html`
- `server.py`
- `login.html`
- `sso_auth.py` — retorno do SSO também passa pela tela de carregamento
- `email_auth.py` — caso já exista de uma versão anterior
- `requirements.txt` — caso ainda não tenha enviado a versão do pacote anterior

Adicione na raiz:

- `credenciais.html` — nova tela com ícone e barra de carregamento
- `email_auth.py` — caso ainda não exista
- `access_auth.py`
- `sso_auth.py` — caso ainda não exista; é usado pelo seletor de autenticação, mesmo quando o SSO fica desativado

Para conferir as instruções depois, também adicione este guia. Os demais arquivos do robô não precisam de atualização. Se ainda houver workflow de publicação GitHub Pages, substitua `.github/workflows/pages.yml` pelo arquivo desativado do pacote e desative publicações antigas em Settings → Pages. Não publique uma cópia estática da Central sem autenticação.

A autenticação por e-mail vem ativada por padrão nesta versão. Se subir os arquivos antes de configurar o envio, a página estará protegida, mas não enviará códigos até a configuração terminar. Para evitar indisponibilidade, configure o Render e o remetente primeiro.

O start command continua:

```text
gunicorn server:application --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120
```

## 4. Teste final no serviço hospedado

1. Abra https://central-de-iniciativas-cj.onrender.com/ em uma janela normal. A tela de login deve aparecer.
2. Clique em Entrar com Microsoft, informe seu nome e seu e-mail QCA, e peça o código.
3. Confira a caixa de entrada e spam. Se não chegar, consulte os logs de envio transacional na Brevo e os logs de erro no Render. Um envio aceito pelo provedor não garante entrega instantânea na caixa de entrada.
4. Digite o código recebido: a Central abre com seu nome, e-mail e Sair no cabeçalho.
5. Feche e reabra o endereço inicial no mesmo navegador: a tela Entrar com Microsoft sempre aparece. Ao clicar, a sessão lembrada dispensa novo código, mostra Carregando credenciais por dez segundos e abre a Central.
6. Clique em Sair: deverá voltar ao login. Acesso a `/api/data` sem sessão deve retornar 401.
7. Verifique acesso administrativo e o estado do executor Lexio. A conta da equipe não vira administradora; a senha atual continua necessária.

É necessário ter acesso à caixa de e-mail para entrar. Contas sem o domínio permitido são recusadas, mas este método não verifica vínculo empregatício, grupos ou status da conta no Entra.

## O que foi validado

Testes locais: proteção de APIs e arquivos, restrição de domínio, origem das solicitações, código com hash, vínculo ao navegador, tentativas, expiração, uso único, sessão de 30 dias, saída e exceção autenticada das rotas do robô. Envio simulado nos testes; nenhum e-mail real foi enviado. O teste de entrega real depende da conta Brevo e do remetente configurados por você.

Se o repositório tiver relatórios ou dados internos embutidos, mantenha-o privado: autenticação no Render não protege arquivos públicos do GitHub.
