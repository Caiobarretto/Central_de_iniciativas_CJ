"""Seleção de perfil por e-mail cadastrado; não autentica a conta Microsoft."""
import hashlib,hmac,json,os,secrets,time
from http.cookies import SimpleCookie
import users_directory
AGE=30*86400

def enabled():return True
def hashed(value):return hashlib.sha256(value.encode()).hexdigest()
def cookie(env,name):
    try:return SimpleCookie(env.get('HTTP_COOKIE',''))[name].value
    except (KeyError,ValueError):return ''
def setcookie(name,value,age):return ('Set-Cookie',f'{name}={value}; Path=/; Max-Age={age}; HttpOnly; Secure; SameSite=Lax')
def setup(connect):
    with connect() as c:c.execute('CREATE TABLE IF NOT EXISTS profile_sessions (id TEXT PRIMARY KEY,email TEXT NOT NULL,csrf TEXT NOT NULL,expires DOUBLE PRECISION NOT NULL)')
def current(env,connect):
    token=cookie(env,'cj_profile')
    if not token:return None
    with connect() as c:
        row=c.execute('SELECT email,csrf,expires FROM profile_sessions WHERE id=?',(hashed(token),)).fetchone()
        if not row or row[2]<=time.time():return None
        profile=users_directory.find(c,row[0])
    return {'name':profile['name'],'email':profile['email'],'csrf':row[1],'profile':profile} if profile else None

def clear_admin(env,connect):
    token=cookie(env,'cj_session')
    if token:
        with connect() as c:c.execute('DELETE FROM sessions WHERE token=?',(hashed(token),))

def handle(env,respond,connect):
    path,method=env.get('PATH_INFO'),env.get('REQUEST_METHOD')
    if method=='GET' and path=='/api/me':return respond('200 OK',{'enabled':True,'mode':'profile','verified':False,'user':current(env,connect)})
    if method=='GET' and path=='/auth/directory':return respond('200 OK',{'users':users_directory.public(connect)})
    if method=='GET' and path=='/auth/login':return respond('302 Found',extra=[('Location','/')])
    if method!='POST' or path not in ('/auth/profile/select','/auth/logout'):return respond('404 Not Found',{'error':'Endereço não encontrado.'})
    expected=os.environ.get('PUBLIC_URL','').strip().rstrip('/')
    if not expected.startswith('https://') or env.get('HTTP_ORIGIN')!=expected:return respond('403 Forbidden',{'error':'Origem da solicitação inválida.'})
    if path=='/auth/logout':
        user=current(env,connect)
        if not user or not hmac.compare_digest(env.get('HTTP_X_CSRF_TOKEN',''),user['csrf']):return respond('403 Forbidden',{'error':'Perfil inválido.'})
        with connect() as c:c.execute('DELETE FROM profile_sessions WHERE id=?',(hashed(cookie(env,'cj_profile')),))
        clear_admin(env,connect)
        return respond('200 OK',{'ok':True},[setcookie('cj_profile','',0),setcookie('cj_session','',0)])
    try:
        length=int(env.get('CONTENT_LENGTH') or 0)
        if not 0<length<=4096 or 'application/json' not in env.get('CONTENT_TYPE',''):raise ValueError()
        data=json.loads(env['wsgi.input'].read(length))
        if not isinstance(data,dict) or not isinstance(data.get('email'),str):raise ValueError()
        email=data['email'].strip().lower()
        if len(email)>150:raise ValueError()
    except (ValueError,UnicodeDecodeError):return respond('400 Bad Request',{'error':'Informe o e-mail cadastrado.'})
    with connect() as c:
        c.execute('LOCK TABLE directory_meta IN EXCLUSIVE MODE' if hasattr(c,'connection') else 'BEGIN IMMEDIATE')
        profile=users_directory.find(c,email)
        if not profile:return respond('400 Bad Request',{'error':'E-mail não encontrado ou perfil desativado. Procure o administrador.'})
        c.execute('DELETE FROM profile_sessions WHERE expires<?',(time.time(),))
        old=cookie(env,'cj_profile')
        if old:c.execute('DELETE FROM profile_sessions WHERE id=?',(hashed(old),))
        token,csrf=secrets.token_urlsafe(40),secrets.token_urlsafe(32)
        c.execute('INSERT INTO profile_sessions VALUES (?,?,?,?)',(hashed(token),profile['email'],csrf,time.time()+AGE))
    clear_admin(env,connect)
    return respond('200 OK',{'ok':True,'user':{'name':profile['name'],'email':profile['email'],'profile':profile}},[setcookie('cj_profile',token,AGE),setcookie('cj_session','',0),setcookie('cj_identity','',0),setcookie('cj_otp','',0)])
