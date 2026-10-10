# Login Microsoft da Central CJ

A versão está preparada, mas o login real só funciona depois do registro da aplicação no Microsoft Entra da QCA. Não é necessário migrar Render ou Neon. Mantenha o robô e todas as variáveis existentes.

## 1. Microsoft Entra — com a TI, se necessário

1. Acesse https://entra.microsoft.com no diretório corporativo QCA.
2. Em **Registros de aplicativo → Novo registro**, nomeie **Central de Iniciativas CJ**.
3. Escolha **Contas somente neste diretório organizacional (locatário único)**. Não escolha contas pessoais ou vários diretórios.
4. Adicione plataforma **Web** com URI de redirecionamento exata:
   `https://central-de-iniciativas-cj.onrender.com/auth/callback`
5. Copie o **ID do aplicativo (cliente)** e **ID do diretório (locatário)**.
6. Em **Certificados e segredos**, crie um segredo de cliente. Copie seu **Valor**, não o ID. Cadastre diretamente no Render; não envie ao GitHub ou por mensagem. Anote a expiração para renová-lo antes do vencimento.
7. Em **Configuração de token**, adicione a declaração opcional **email** ao **token de ID**. Não habilite concessão implícita.
8. Este aplicativo solicita somente os escopos de identidade **openid, profile e email**. Não precisa de Microsoft Graph User.Read, Mail.Read ou permissões de SharePoint/Power BI. Remova User.Read se vier como permissão padrão e não for usado por outra integração.
9. Em **Aplicativos empresariais → Central → Propriedades**, defina **Atribuição necessária? Sim**. Em **Usuários e grupos**, atribua explicitamente as pessoas autorizadas. Atribuição por grupo pode depender de licença; atribuição individual evita essa dependência. A TI deve atribuir somente funcionários autorizados da QCA, não convidados. Isso complementa a verificação de tenant e domínio do servidor: domínio de e-mail isolado não é uma fronteira suficiente de autorização.
10. Se a política corporativa exigir, a TI concede consentimento para os escopos de identidade e revisa a aplicação. O registro corporativo continua necessário mesmo quando se usa somente nome/e-mail.

## 2. Atualizar o GitHub

Substitua os arquivos do projeto pelo conteúdo deste pacote, mantendo a estrutura. Os novos arquivos são `sso_auth.py`, `login.html` e este guia; `server.py`, `index.html` e `requirements.txt` também mudaram. Não suba a pasta `data`, `.venv`, `config.json`, `SEGREDOS_RENDER.txt` ou `LINK_EQUIPE.txt`.

O workflow de GitHub Pages do pacote está desativado para não publicar uma cópia estática sem proteção. Substitua também `.github/workflows/pages.yml`. Se já houver uma publicação Pages ativa, desative-a em Settings → Pages; a atualização do workflow não retira uma publicação antiga.

Os dados existentes no Neon não são substituídos: as tabelas de identidade são adicionais e o catálogo continua sendo carregado apenas quando o banco está vazio.

## 3. Render → Environment

Mantenha `DATABASE_URL`, variáveis do admin e variáveis RPA exatamente como estão. Acrescente:

| Nome | Valor |
|---|---|
| PUBLIC_URL | https://central-de-iniciativas-cj.onrender.com |
| MICROSOFT_TENANT_ID | ID do diretório QCA |
| MICROSOFT_CLIENT_ID | ID do aplicativo |
| MICROSOFT_CLIENT_SECRET | Valor do segredo criado no Entra |
| SSO_ENABLED | true |

Ative `SSO_ENABLED=true` somente quando os três valores Microsoft e o registro estiverem prontos. Salve e aguarde o deploy. O comando de inicialização continua:
`gunicorn server:application --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120`

## 4. Conferência final

- Abra a Central em uma janela anônima: somente a página de login deve aparecer.
- Antes do login, `/api/data` deve retornar 401 e não exibir o catálogo.
- Clique em Entrar com Microsoft, use uma conta QCA atribuída e confira nome/e-mail/Sair ao lado do título.
- Uma conta de outro domínio, outro tenant ou uma conta não atribuída deve ser recusada.
- Entre na administração pelo acesso discreto atual; a senha do administrador continua necessária para editar.
- Clique em Sair: volta à tela de login e remove as sessões Microsoft da Central e admin. Outros aplicativos Microsoft permanecem conectados. No próximo login há seleção de conta.
- O executor Lexio usa sua credencial própria, sem login interativo Microsoft. As rotas do executor continuam protegidas pelo token RPA.
- O link de equipe com `?rpa=...` deve ser aberto antes de entrar com Microsoft, na mesma aba. A chave temporária é preservada durante o redirecionamento.
- Confirme também os relatórios, anexos, tratamento de segmentos e um teste controlado do robô. O envio real da Lexio não foi testado nesta atualização.

## Dados e limites

Guardamos no Neon o identificador Microsoft (tenant + oid), nome, e-mail e data/hora do último login bem-sucedido. A sessão da Central dura até oito horas; cookies são HttpOnly e Secure, e as sessões ficam no servidor. Não guardamos senha Microsoft, access token ou refresh token. Dados temporários do fluxo OIDC ficam criptografados por até dez minutos e são consumidos uma única vez. A aplicação não chama Microsoft Graph.

Permissões de admin continuam separadas: o login corporativo não transforma todos os funcionários em administradores. SSO não remove bloqueios de iframe do SharePoint nem altera licenças/permissões de Power BI.

Testes locais usam provedor simulado; a verificação ponta a ponta com a Microsoft precisa acontecer após configurar o Entra. Para retornar temporariamente ao comportamento anterior, configure `SSO_ENABLED=false`; isso reabre o catálogo público como antes.

Se o repositório contiver relatórios ou dados internos em `initial_data.json` ou embutidos em `index.html`, mantenha-o privado e desative GitHub Pages. O login do Render não protege cópias publicadas no GitHub ou em outros endereços.
