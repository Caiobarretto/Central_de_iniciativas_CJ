## Correção aplicada ao index atual enviado

Use o arquivo `index.html` deste pacote. Ele foi corrigido a partir de Central_Controladoria_QCA (6).html, que ainda abria o pop-up antigo. No GitHub, o nome deve ser exatamente index.html, na raiz junto do server.py. Não envie com o nome Central_Controladoria_QCA (6).html: o servidor continua lendo index.html.

Também substitua login.html e credenciais.html: as logos dessas telas não são controladas pelo index. Substitua profile_auth.py e users_directory.py para o salvamento da foto.

Depois do commit, confira no Render se o deploy corresponde ao commit novo. Aguarde o status Live e abra a Central com Ctrl+F5. O clique no nome e a aba Meu perfil devem abrir /central#perfil sem diálogo. As três telas devem mostrar o rodapé QCA; entrada e credenciais mostram a logo CJ. Nenhuma variável precisa mudar.

## Último ajuste: logos, módulo Meu perfil e rodapé

Para atualizar a versão anterior que já usa `ACCESS_MODE=profile`, substitua estes cinco arquivos na raiz do GitHub:

- `index.html`
- `login.html`
- `credenciais.html`
- `profile_auth.py`
- `users_directory.py`

Nenhuma variável do Render precisa mudar. Faça o commit e aguarde o deploy. As logos estão embutidas nos HTMLs; não é necessário enviar arquivos de imagem separados. A tabela de fotos é criada automaticamente no banco, sem executar SQL manualmente.

A logo CJ aparece abaixo do botão Entrar com Microsoft e na tela de carregamento de credenciais. O rodapé das três telas mostra a logo QCA e © 2026 Queiroz Cavalcanti Advocacia.

Meu perfil agora é uma aba própria dentro da Central, acessível pela navegação ou pelo nome no cabeçalho. A foto fica à esquerda e os dados profissionais do cadastro aparecem em colunas. Em celular, os campos se ajustam à largura disponível. A aba Iniciativas retorna aos cards.

O integrante pode incluir, alterar ou remover sua foto. Aceita PNG, JPEG e WebP de até 5 MB; a imagem é recortada ao centro e reduzida para 320 × 320 antes de salvar no Neon. A foto processada tem limite de 400 KB. Os dados profissionais continuam sendo editados pelo admin. A entrada segue apenas por e-mail digitado, sem combobox, e mantém a tela de carregamento de dez segundos.

Confira após o deploy: logos na entrada e no carregamento, aba Meu perfil, inclusão/remoção de foto, retorno às iniciativas e rodapé. Abaixo estão as instruções completas para quem ainda não instalou o modo de perfil.

# Acesso atual: seleção de perfil, sem e-mails e sem códigos

O botão inicial mantém o texto Entrar com Microsoft. Nesta versão, ele apenas abre a seleção de perfil: não faz SSO, não acessa a conta Microsoft e não confirma a titularidade do e-mail. Qualquer pessoa que conheça um endereço da lista pode selecionar aquele perfil e acessar a Central. Nome/e-mail exibidos não são prova de identidade. A senha administrativa continua obrigatória; o perfil da equipe não concede administração.

## Atualizar agora

Se já instalou o pacote anterior, substitua na raiz do repositório:

- `server.py`
- `access_auth.py`
- `users_directory.py`
- `users_seed.json`
- `login.html`
- `index.html`

Adicione o arquivo novo `profile_auth.py`, na mesma pasta de `server.py`. Se ainda não havia enviado `users_directory.py` ou `users_seed.json`, adicione-os também. Preserve `credenciais.html`, `email_auth.py`, `sso_auth.py`, `database.py` e os demais arquivos. O seletor mantém os modos anteriores como opções, por isso os módulos antigos continuam no pacote, embora o modo atual não envie e-mails.

Mantenha o GitHub privado: users_seed.json contém o cadastro real dos integrantes.

No Render → Environment, adicione:

| Variável | Valor |
|---|---|
| ACCESS_MODE | profile |

Pode remover `BREVO_API_KEY`, `EMAIL_FROM` e `EMAIL_AUTH_SECRET` do Render, pois não são usados nesse modo. As variáveis antigas `EMAIL_AUTH_ENABLED` e `SSO_ENABLED` também não ativam o envio ou SSO quando ACCESS_MODE=profile. Não altere DATABASE_URL, ADMIN_USER, ADMIN_PASSWORD, PUBLIC_URL nem as variáveis do robô. PUBLIC_URL continua https://central-de-iniciativas-cj.onrender.com.

Não é necessário configurar Brevo, DNS ou Microsoft Entra para este fluxo. O comando de inicialização e requirements.txt permanecem iguais. Depois do commit, aguarde o novo deploy no Render.

## Fluxo

1. O endereço inicial sempre mostra Entrar com Microsoft.
2. Sem perfil lembrado, clique no botão e digite apenas o e-mail corporativo. Não há lista ou sugestões de integrantes; a consulta é feita no servidor ao clicar em Entrar na Central.
3. Clique em Entrar na Central. Endereços não cadastrados ou desativados são recusados.
4. A página Carregando credenciais exibe o nome e e-mail, o ícone e a barra durante dez segundos. É uma transição visual, não uma autenticação Microsoft.
5. A Central original abre com nome/e-mail e Sair. Clique na aba Meu perfil ou no nome do usuário para abrir o módulo, que mostra nome, e-mail, centro de custo, núcleo, subnúcleo, atendimento às equipes jurídicas, liderança imediata, função, vínculo e empresa/unidade, conforme os campos profissionais da planilha.
6. Este navegador lembra a seleção por até 30 dias. Na próxima visita, a página inicial continua aparecendo; clicar no botão passa diretamente ao carregamento quando o perfil lembrado ainda é válido.
7. Sair apaga a seleção lembrada e a sessão de admin. Para trocar de perfil, use Sair e escolha outro e-mail.

## Admin

Entre na Central e use Acesso administrativo com a senha atual. Em Usuários e e-mails, inclua, edite, desative ou exclua integrantes. A lista e os perfis ficam no Neon e são compartilhados. Desativar, excluir ou mudar um e-mail revoga a seleção lembrada do endereço anterior. Editar as informações profissionais aparece em Meu perfil no próximo acesso/recarregamento.

O cadastro inicial contém 37 integrantes. Ele é importado apenas uma vez. Novos deploys não repõem cadastros excluídos nem desfazem edições. Para cadastros da versão anterior, são completados apenas os novos campos profissionais ausentes de vínculo e atendimento às equipes; valores já editados são preservados. O imobilizado não foi importado.

O backup das iniciativas não inclui o cadastro de integrantes; conserve backup do banco Neon.

## Conferência após o deploy

- Abra a Central numa janela anônima; clique no botão, informe seu e-mail cadastrado e entre sem código.
- Confira a tela de dez segundos, os dados no cabeçalho e Meu perfil.
- Saia e teste um e-mail não cadastrado: não deve liberar o botão nem o acesso.
- Teste o admin com a senha atual e altere um perfil; confira a atualização em outra sessão.
- Confira o executor Lexio; a autenticação do robô e o link/token da equipe foram preservados.

Testes locais do servidor e navegador: seleção apenas por e-mail, dados canônicos do cadastro, ausência de chamadas de envio, origem das solicitações, senha administrativa separada, troca de perfil encerrando a sessão de admin, saída, expiração, desativação, lista/edição, versão móvel e carregamento de dez segundos. Não foi publicado automaticamente no Render.
