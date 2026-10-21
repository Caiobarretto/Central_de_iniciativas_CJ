"""Login por código: e-mail QCA, sessão de 30 dias e envio HTTPS Brevo."""
import hashlib,hmac,json,os,re,secrets,time,urllib.request,urllib.error
from urllib.parse import urlencode
import users_directory
from http.cookies import SimpleCookie
DOMAIN='queirozcavalcanti.adv.br'
AGE=30*86400

def enabled():return os.environ.get('EMAIL_AUTH_ENABLED','true').lower()=='true'
def origin():return os.environ.get('PUBLIC_URL','').strip().rstrip('/')
def secret():
    key=os.environ.get('EMAIL_AUTH_SECRET','')
    if len(key)<32:raise ValueError('Configure EMAIL_AUTH_SECRET com pelo menos 32 caracteres.')
    return key.encode()
def hashed(value):return hashlib.sha256(value.encode()).hexdigest()
def mac(value):return hmac.new(secret(),value.encode(),hashlib.sha256).hexdigest()
def cookie(env,name):
    try:return SimpleCookie(env.get('HTTP_COOKIE',''))[name].value
    except (KeyError,ValueError):return ''
def setcookie(name,value,age):return ('Set-Cookie',f'{name}={value}; Path=/; Max-Age={age}; HttpOnly; Secure; SameSite=Lax')
def setup(connect):
    with connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS email_challenges (id TEXT PRIMARY KEY,email TEXT NOT NULL,name TEXT NOT NULL,digest TEXT NOT NULL,tries INTEGER NOT NULL,expires DOUBLE PRECISION NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS email_sessions (id TEXT PRIMARY KEY,email TEXT NOT NULL,name TEXT NOT NULL,csrf TEXT NOT NULL,expires DOUBLE PRECISION NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS email_users (email TEXT PRIMARY KEY,name TEXT NOT NULL,last_login DOUBLE PRECISION NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS email_delivery (id TEXT PRIMARY KEY,email TEXT NOT NULL,message_id TEXT NOT NULL,created DOUBLE PRECISION NOT NULL,status TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS email_limits (id TEXT PRIMARY KEY,count INTEGER NOT NULL,until DOUBLE PRECISION NOT NULL)')
def current(env,connect):
    token=cookie(env,'cj_identity')
    if not token:return None
    try:ident=mac('session:'+token)
    except ValueError:return None
    with connect() as c:row=c.execute('SELECT email,name,csrf,expires FROM email_sessions WHERE id=?',(ident,)).fetchone()
    if not row or row[-1]<=time.time():return None
    with connect() as c:profile=users_directory.find(c,row[0])
    if not profile:return None
    user=dict(zip(('email','name','csrf','expires'),row));user['name']=profile['name'];user['profile']=profile
    return user

def send_code(email,code):
    api=os.environ.get('BREVO_API_KEY','');sender=os.environ.get('EMAIL_FROM','').strip()
    if not api or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',sender):raise ValueError('Configure o remetente e a chave de envio.')
    payload={'sender':{'name':'Central de Iniciativas CJ','email':sender},'to':[{'email':email}], 'subject':'Seu código de acesso à Central CJ', 'textContent':f'Seu código de acesso à Central de Iniciativas CJ é: {code}\n\nEle vale por 10 minutos e pode ser usado uma única vez no navegador que solicitou o acesso.\nNão compartilhe este código. Se você não solicitou o acesso, ignore esta mensagem.\n\nApós confirmar, este navegador manterá seu acesso por até 30 dias, ou até você clicar em Sair.'}
    req=urllib.request.Request('https://api.brevo.com/v3/smtp/email',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Accept':'application/json','api-key':api},method='POST')
    with urllib.request.urlopen(req,timeout=20) as res:
        if res.status!=201:raise ValueError('Envio recusado.')
        out=json.loads(res.read(16384))
        if not isinstance(out.get('messageId'),str) or not out['messageId']:raise ValueError('O provedor não retornou o identificador de envio.')
        return out['messageId']

def clear_admin(env,connect):
    token=cookie(env,'cj_session')
    if token:
        with connect() as c:c.execute('DELETE FROM sessions WHERE token=?',(hashed(token),))

def lock(c):
    c.execute('LOCK TABLE email_challenges, email_limits IN EXCLUSIVE MODE' if hasattr(c,'connection') else 'BEGIN IMMEDIATE')

def rate_limits(c,env,email,now):
    # Limites persistidos no banco. REMOTE_ADDR não confia em headers fornecidos pelo cliente.
    limits=[('mail:'+email,6,3600),('ip:'+env.get('REMOTE_ADDR',''),40,3600),('global',250,86400)]
    for name,cap,window in limits:
        key=hashed(name);row=c.execute('SELECT count,until FROM email_limits WHERE id=?',(key,)).fetchone()
        if row and row[1]>now and row[0]>=cap:return False
    for name,cap,window in limits:
        key=hashed(name);row=c.execute('SELECT count,until FROM email_limits WHERE id=?',(key,)).fetchone()
        count,until=(row[0]+1,row[1]) if row and row[1]>now else (1,now+window)
        c.execute('INSERT INTO email_limits VALUES (?,?,?) ON CONFLICT (id) DO UPDATE SET count=excluded.count,until=excluded.until',(key,count,until))
    return True

def handle(env,respond,connect):
    path,method=env.get('PATH_INFO'),env.get('REQUEST_METHOD')
    if path=='/auth/directory' and method=='GET' and enabled():return respond('200 OK',{'users':users_directory.public(connect)})
    if path=='/api/me' and method=='GET':
        user=current(env,connect) if enabled() else None
        return respond('200 OK',{'enabled':enabled(),'mode':'email','user':{k:user[k] for k in ('name','email','csrf','profile')} if user else None})
    if not enabled():return respond('404 Not Found',{'error':'Login por e-mail desativado.'})
    if path=='/auth/login' and method=='GET':return respond('302 Found',extra=[('Location','/')])
    if method!='POST' or path not in ['/auth/email/request','/auth/email/verify','/auth/logout']:return respond('404 Not Found',{'error':'Endereço não encontrado.'})
    if not origin().startswith('https://') or env.get('HTTP_ORIGIN','')!=origin():return respond('403 Forbidden',{'error':'Origem da solicitação inválida.'})
    if path=='/auth/logout':
        user=current(env,connect)
        if not user or not hmac.compare_digest(env.get('HTTP_X_CSRF_TOKEN',''),user['csrf']):return respond('403 Forbidden',{'error':'Sessão inválida.'})
        with connect() as c:c.execute('DELETE FROM email_sessions WHERE id=?',(mac('session:'+cookie(env,'cj_identity')),))
        clear_admin(env,connect)
        return respond('200 OK',{'ok':True},[setcookie('cj_identity','',0),setcookie('cj_session','',0),setcookie('cj_otp','',0)])
    try:secret()
    except ValueError:return respond('503 Service Unavailable',{'error':'O administrador ainda precisa configurar o envio de códigos.'})
    try:
        length=int(env.get('CONTENT_LENGTH') or 0)
        if not 0<length<=4096 or 'application/json' not in env.get('CONTENT_TYPE',''):raise ValueError()
        data=json.loads(env['wsgi.input'].read(length))
        if not isinstance(data,dict):raise ValueError()
    except (ValueError,UnicodeDecodeError):return respond('400 Bad Request',{'error':'Dados inválidos.'})
    now=time.time()
    if path=='/auth/email/request':
        uid=data.get('userId','')
        if not isinstance(uid,str):return respond('400 Bad Request',{'error':'Selecione seu nome na lista.'})
        with connect() as c:
            row=c.execute('SELECT data FROM directory_users WHERE id=?',(uid,)).fetchone()
        user=json.loads(row[0]) if row else None
        if not user or not user['active']:return respond('400 Bad Request',{'error':'Selecione um integrante ativo da lista. Procure o administrador se seu nome não aparecer.'})
        email,name=user['email'],user['name']
        if not os.environ.get('BREVO_API_KEY') or not os.environ.get('EMAIL_FROM'):return respond('503 Service Unavailable',{'error':'O administrador ainda precisa configurar o envio de códigos.'})
        binding=secrets.token_urlsafe(40);ident=hashed(binding);code=f'{secrets.randbelow(1_000_000):06d}'
        with connect() as c:
            lock(c)
            c.execute('DELETE FROM email_challenges WHERE expires<?',(now,));c.execute('DELETE FROM email_limits WHERE until<?',(now,));c.execute('DELETE FROM email_sessions WHERE expires<?',(now,))
            previous=c.execute('SELECT expires FROM email_challenges WHERE id=?',(hashed(cookie(env,'cj_otp')),)).fetchone()
            if previous and previous[0]-600+60>now:return respond('429 Too Many Requests',{'error':'Aguarde 60 segundos antes de pedir outro código.'})
            if not rate_limits(c,env,email,now):return respond('429 Too Many Requests',{'error':'Limite de solicitações atingido. Tente novamente mais tarde.'})
            c.execute('INSERT INTO email_challenges VALUES (?,?,?,?,?,?)',(ident,email,name,mac(ident+':'+code),0,now+600))
        try:message_id=send_code(email,code)
        except Exception as error:
            # Nunca imprime código, endereço, chave ou resposta do provedor nos logs.
            import logging
            logging.warning('Envio de codigo indisponivel: tipo=%s status=%s',type(error).__name__,getattr(error,'code','indisponivel'))
            with connect() as c:c.execute('DELETE FROM email_challenges WHERE id=?',(ident,))
            return respond('503 Service Unavailable',{'error':'Não foi possível enviar o código. Tente novamente ou procure o administrador.'})
        with connect() as c:
            c.execute('DELETE FROM email_challenges WHERE id=?',(hashed(cookie(env,'cj_otp')),))
            c.execute('DELETE FROM email_delivery WHERE created<?',(now-30*86400,))
            c.execute('INSERT INTO email_delivery VALUES (?,?,?,?,?)',(ident,email,message_id or '',now,'accepted'))
        return respond('200 OK',{'ok':True,'email':email,'expiresIn':600,'resendAfter':60,'delivery':'accepted'},[setcookie('cj_otp',binding,600)])
    binding=cookie(env,'cj_otp');code=data.get('code','')
    if not binding or not isinstance(code,str) or not re.fullmatch(r'\d{6}',code):return respond('400 Bad Request',{'error':'Informe o código de 6 dígitos enviado ao seu e-mail.'})
    ident=hashed(binding)
    with connect() as c:
        lock(c)
        row=c.execute('SELECT email,name,digest,tries,expires FROM email_challenges WHERE id=?',(ident,)).fetchone()
        if not row or row[4]<=now or row[3]>=5:return respond('401 Unauthorized',{'error':'Código expirado ou tentativas esgotadas. Solicite um novo código.'})
        if not hmac.compare_digest(row[2],mac(ident+':'+code)):
            c.execute('UPDATE email_challenges SET tries=tries+1 WHERE id=?',(ident,))
            return respond('401 Unauthorized',{'error':'Código incorreto. Confira a mensagem recebida.'})
        profile=users_directory.find(c,row[0])
        if not profile:return respond('401 Unauthorized',{'error':'Cadastro desativado ou excluído. Procure o administrador.'})
        c.execute('DELETE FROM email_challenges WHERE id=?',(ident,))
        token,csrf=secrets.token_urlsafe(40),secrets.token_urlsafe(32)
        old=cookie(env,'cj_identity')
        if old:c.execute('DELETE FROM email_sessions WHERE id=?',(mac('session:'+old),))
        c.execute('INSERT INTO email_sessions VALUES (?,?,?,?,?)',(mac('session:'+token),row[0],profile['name'],csrf,now+AGE))
        c.execute('INSERT INTO email_users VALUES (?,?,?) ON CONFLICT (email) DO UPDATE SET name=excluded.name,last_login=excluded.last_login',(row[0],profile['name'],now))
    clear_admin(env,connect)
    return respond('200 OK',{'ok':True},[setcookie('cj_identity',token,AGE),setcookie('cj_otp','',0),setcookie('cj_session','',0)])


def delivery_diagnostics(connect,ident=''):
    """Admin somente: consulta eventos do provedor sem conteúdo da mensagem/OTP."""
    out={'configured':bool(os.environ.get('BREVO_API_KEY') and os.environ.get('EMAIL_FROM')),'sender':os.environ.get('EMAIL_FROM',''),'help':'Se aceito sem entrega, confira Transactional > Logs no Brevo, remetente/domínio autenticado e quarentena do Microsoft 365.'}
    with connect() as c:
        rows=c.execute('SELECT id,email,message_id,created,status FROM email_delivery ORDER BY created DESC LIMIT 20').fetchall()
        selected=c.execute('SELECT message_id FROM email_delivery WHERE id=?',(ident,)).fetchone() if ident else None
    out['messages']=[dict(zip(('id','email','messageId','created','status'),r)) for r in rows]
    if not selected:return out
    if not selected[0]:out['error']='Envio antigo sem identificador. Faça uma nova solicitação.';return out
    req=urllib.request.Request('https://api.brevo.com/v3/smtp/statistics/events?'+urlencode({'messageId':selected[0],'days':30,'limit':50,'sort':'desc'}),headers={'Accept':'application/json','api-key':os.environ.get('BREVO_API_KEY','')})
    try:
        with urllib.request.urlopen(req,timeout=15) as response:body=json.loads(response.read(100000))
        events=body.get('events',[])
        out['events']=[{'event':str(e.get('event',''))[:100],'date':str(e.get('date',''))[:100],'reason':str(e.get('reason',''))[:500]} for e in events if e.get('messageId')==selected[0]]
        out['checkedId']=ident
        if not out['events']:out['notice']='Ainda sem eventos de entrega. Verifique também os logs no Brevo.'
    except Exception as e:out['error']='Não foi possível consultar o Brevo. Confira a chave API/permissões e os logs. Status: '+str(getattr(e,'code','indisponível'))
    return out
