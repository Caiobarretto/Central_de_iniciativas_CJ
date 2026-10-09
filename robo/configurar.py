import base64,json,pathlib,secrets
root=pathlib.Path(__file__).resolve().parent
path=root/'config.json'
if path.exists():raise SystemExit('Configuração já existe. Para refazer, renomeie config.json primeiro e atualize os segredos no Render.')
url=input('URL HTTPS da Central no Render: ').strip().rstrip('/')
if not url.startswith('https://') or ' ' in url:raise SystemExit('Endereço HTTPS inválido.')
email=input('E-mail de acesso à Lexio: ').strip()
token=secrets.token_urlsafe(40);team=secrets.token_urlsafe(40);key=base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
path.write_text(json.dumps({'central_url':url,'worker_token':token,'lexio_email':email},indent=2),encoding='utf-8')
(root/'SEGREDOS_RENDER.txt').write_text('RPA_WORKER_TOKEN='+token+'\nRPA_QUEUE_KEY='+key+'\nRPA_TEAM_TOKEN='+team+'\n',encoding='utf-8')
(root/'LINK_EQUIPE.txt').write_text(url+'/?rpa='+team+'\n',encoding='utf-8')
print('Configuração pronta. Copie os três valores de SEGREDOS_RENDER.txt para Environment no Render.\nEsses arquivos são privados: não os envie ao GitHub nem ao time. Compartilhe apenas o endereço de LINK_EQUIPE.txt com o time. A senha da Lexio será pedida ao iniciar o robô.')
