# Central da Controladoria Jurídica — QCA

Abra `GUIA_CONFIGURACAO.html` no navegador para o passo a passo completo.

- Site: Render Free; PostgreSQL persistente: Neon Free.
- Página pública nas iniciativas; administração com usuário/senha somente no backend.
- Excel de segmentos: até 3 arquivos por lote, aceitos até 1 GB por arquivo, processados sequencialmente no navegador Chrome/Edge em HTTPS. Python/WebAssembly é carregado automaticamente; não há instalação para o usuário nem envio dos relatórios ao servidor. O resumo contém valores de contagem, sem nova tabela dinâmica. A capacidade depende do armazenamento e da memória disponíveis.
- Lexio: RPA real no computador anfitrião. A Central recebe arquivos Word e metadados numa fila criptografada; o executor local consulta a fila via HTTPS e executa um documento por vez. Sem portas abertas, túnneis ou agente nos computadores do time. O navegador controlado aparece no computador anfitrião, sem transmissão de tela.
- A solicitação de envio exige o link privado de uso da equipe, gerado pela configuração; não cria login para o time.
- Google Chrome e Python são instalados apenas no computador do robô.
- Arquivos temporários do robô são apagados depois de cada trabalho. O Chrome mantém o perfil de sessão separado no computador anfitrião.
- Aguardando na fila: até 8 horas; estados/resultados: até 24 horas, limpos nos acessos seguintes. Falhas e interrupções exigem conferência na Lexio antes de reenviar.

## Render

Build: `pip install -r requirements.txt`

Start: `gunicorn server:application --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120`

Environment: DATABASE_URL, ADMIN_USER, ADMIN_PASSWORD (12+ caracteres), PUBLIC_URL, COOKIE_SECURE=true, REQUIRE_POSTGRES=true, RPA_WORKER_TOKEN, RPA_QUEUE_KEY, RPA_TEAM_TOKEN.

Não crie disco pago nem banco temporário do Render. O serviço e o banco devem permanecer nos planos Free; acompanhe as cotas. O executor ligado faz consultas à Central, então use-o nos horários em que o time precisar.

## Computador anfitrião

Na pasta robo, execute nesta ordem: INSTALAR_WINDOWS.bat, CONFIGURAR_WINDOWS.bat, INICIAR_WINDOWS.bat. Configure os três segredos gerados em Environment no Render. Compartilhe somente o link de LINK_EQUIPE.txt com o time. A senha Lexio é pedida a cada início do executor.

Não envie ao GitHub config.json, SEGREDOS_RENDER.txt, LINK_EQUIPE.txt, .venv, data, __pycache__ ou bancos locais.

## Verificações

O motor do Excel foi testado em Python/WebAssembly com arquivo sintético de 143 MB e 100 mil registros, e conferido quanto às regras, contagem e preservação de outras partes do Excel. A fila foi testada quanto a autenticação do executor, criptografia, idempotência, execução única e interrupções. A execução real na Lexio depende de configuração e teste com a conta do QCA; não foi realizada neste ambiente.

GitHub Pages é apenas uma visualização estática. Use a URL do Render para administração e RPA compartilhados.
