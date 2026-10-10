"""Central CJ: banco compartilhado e autenticação exclusiva do administrador."""
import base64
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('DATA_DIR', str(ROOT / 'data')))
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / 'central.sqlite3'
MAX_BODY = 100_000_000
ADMIN_USER = os.environ.get('ADMIN_USER', 'admin')
PASSWORD = os.environ.get('ADMIN_PASSWORD', '')
PUBLIC_URL = os.environ.get('PUBLIC_URL', '').strip().rstrip('/')
SECURE_COOKIE = os.environ.get('COOKIE_SECURE', 'true').lower() == 'true'


from database import connect_database
import access_auth as sso_auth
import users_directory
import admin_access


def connect():
    return connect_database(DB)


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 600_000).hex()


def initialize():
    with connect() as con:
        con.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, data TEXT NOT NULL)')
        con.execute('CREATE TABLE IF NOT EXISTS admin (id INTEGER PRIMARY KEY CHECK(id=1), username TEXT, salt BLOB, digest TEXT)')
        con.execute('CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, csrf TEXT, expires REAL)')
        con.execute('CREATE TABLE IF NOT EXISTS attempts (key TEXT PRIMARY KEY, count INTEGER, until REAL)')
        if not con.execute('SELECT 1 FROM state').fetchone():
            seed = json.loads((ROOT / 'initial_data.json').read_text(encoding='utf-8'))
            con.execute('INSERT INTO state VALUES (1,1,?)', (json.dumps(seed, ensure_ascii=False),))
        old = con.execute('SELECT username,salt,digest FROM admin WHERE id=1').fetchone()
        if PASSWORD:
            if len(PASSWORD) < 12:
                raise RuntimeError('ADMIN_PASSWORD precisa ter pelo menos 12 caracteres.')
            if not old or old[0] != ADMIN_USER or not hmac.compare_digest(old[2], password_hash(PASSWORD, old[1])):
                salt = secrets.token_bytes(32)
                con.execute('INSERT OR REPLACE INTO admin VALUES (1,?,?,?)', (ADMIN_USER, salt, password_hash(PASSWORD, salt)))
                con.execute('DELETE FROM sessions')
        elif not old:
            raise RuntimeError('Defina ADMIN_PASSWORD ou execute python server.py para cadastrar o admin.')


def session(environ):
    identity=sso_auth.current(environ,connect)
    if not admin_access.allowed(identity,connect):return None
    try:
        cookie = SimpleCookie(environ.get('HTTP_COOKIE', ''))
        token = cookie['cj_session'].value
    except (KeyError, ValueError):
        return None
    token = hashlib.sha256(token.encode()).hexdigest()
    with connect() as con:
        row = con.execute('SELECT csrf,expires FROM sessions WHERE token=?', (token,)).fetchone()
        bound=con.execute('SELECT email FROM admin_session_profiles WHERE token=?',(token,)).fetchone()
    return (token, row[0]) if row and row[1] > time.time() and bound and bound[0]==identity['email'].lower() else None


def valid_data(data):
    if not isinstance(data, dict) or not isinstance(data.get('items'), list) or not isinstance(data.get('results'), dict):
        return False
    if len(data['items']) > 500 or len(data['results']) > 240:
        return False
    ids = set()
    for card in data['items']:
        if not isinstance(card, dict):
            return False
        for field in ['id','title','category','status','type','description','owner','tags','action','url','instructions']:
            if not isinstance(card.get(field), str) or len(card[field]) >= 20000:
                return False
        if not card['id'] or not card['title'].strip() or card['id'] in ids:
            return False
        ids.add(card['id'])
        if card['category'] not in ['Automações','Ferramentas','Dashboards','Melhorias'] or card['status'] not in ['Disponível','Em implantação','Em estudo']:
            return False
        if card['action'] not in ['assistant','calculator','template','link','download','lexio','vba','segments','attachment'] or not isinstance(card.get('featured'), bool):
            return False
        if card.get('openMode', 'popup') not in ['popup', 'tab']:
            return False
        if card['url'] and urlsplit(card['url']).scheme not in ['http','https']:
            return False
        files = card.get('attachments', [])
        if not isinstance(files, list) or len(files) > 5 or any(not valid_file(f,5_000_000) for f in files):
            return False
    for month, report in data['results'].items():
        if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', month) or not isinstance(report, dict):
            return False
        if not isinstance(report.get('text'), str) or not isinstance(report.get('image'), str):
            return False
        if report['image'] and not re.match(r'^data:image/(png|jpeg|webp);base64,', report['image']):
            return False
        deck = report.get('deck')
        if deck:
            if not isinstance(deck, dict) or not isinstance(deck.get('slides'), list) or len(deck['slides']) != 4:
                return False
            for slide in deck['slides']:
                if not isinstance(slide, dict) or not isinstance(slide.get('title'),str) or not isinstance(slide.get('texts'),list) or any(not isinstance(x,str) for x in slide['texts']):
                    return False
                if not isinstance(slide.get('charts'),list) or not isinstance(slide.get('pictures'),list):
                    return False
        if report.get('original') and not valid_file(report['original'],20_000_000):
            return False
    return True


def valid_file(file,limit):
    try:
        if not isinstance(file,dict) or not isinstance(file.get('name'),str) or not isinstance(file.get('size'),int) or file['size'] > limit:
            return False
        if not isinstance(file.get('data'),str) or not re.match(r'^data:[^,]*;base64,',file['data']):
            return False
        binary=base64.b64decode(file['data'].split(',',1)[1],validate=True)
        return len(binary)==file['size'] and len(binary)<=limit
    except (ValueError,TypeError):
        return False


def application(environ,start_response):
    headers=[('Cache-Control','no-store'),('X-Content-Type-Options','nosniff'),('Referrer-Policy','strict-origin-when-cross-origin')]
    def respond(status,obj=None,extra=None):
        body=json.dumps(obj,ensure_ascii=False).encode() if obj is not None else b''
        start_response(status,headers+[('Content-Type','application/json; charset=utf-8'),('Content-Length',str(len(body)))]+(extra or []))
        return [body]
    method=environ.get('REQUEST_METHOD','GET');path=environ.get('PATH_INFO','/')
    try:
        if path.startswith('/auth/') or path=='/api/me':
            def identity_response(status,obj=None,extra=None):
                if path=='/api/me' and isinstance(obj,dict) and obj.get('user'):
                    obj['user']['canAdmin']=admin_access.allowed(obj['user'],connect)
                return respond(status,obj,extra)
            return sso_auth.handle(environ,identity_response,connect)
        if sso_auth.enabled() and method=='GET' and path in ['/','/index.html']:
            body=(ROOT/'login.html').read_bytes()
            start_response('200 OK',headers+[('Content-Type','text/html; charset=utf-8'),('Content-Length',str(len(body)))])
            return [body]
        worker_route=path in ['/api/rpa/worker/claim','/api/rpa/worker/report']
        if sso_auth.enabled() and path not in ['/health','/favicon.png'] and not worker_route:
            identity=sso_auth.current(environ,connect)
            if not identity:
                if method=='GET' and path in ['/central','/carregando']:
                    return respond('302 Found',extra=[('Location','/')])
                return respond('401 Unauthorized',{'error':'Selecione seu perfil para acessar a Central.'})
        if path.startswith('/api/rpa/'):
            import rpa_queue
            return rpa_queue.handle(environ,respond,connect,PUBLIC_URL)
        if method=='GET' and path.startswith('/ferramentas/'):
            file=(ROOT/path.lstrip('/')).resolve()
            if (ROOT/'ferramentas').resolve() not in file.parents or not file.is_file() or file.suffix not in ['.html','.js','.py','.wasm','.zip','.json']:return respond('404 Not Found',{'error':'Arquivo não encontrado.'})
            import mimetypes
            body=file.read_bytes();mime=mimetypes.guess_type(str(file))[0] or 'application/octet-stream'
            start_response('200 OK',headers+[('Content-Type',mime),('Content-Length',str(len(body)))]);return [body]
        if method=='GET' and path in ['/','/index.html','/central','/carregando','/favicon.png','/health']:
            if path=='/health':return respond('200 OK',{'ok':True})
            file=ROOT/('favicon.png' if path=='/favicon.png' else 'credenciais.html' if path=='/carregando' else 'index.html')
            body=file.read_bytes();mime='image/png' if path=='/favicon.png' else 'text/html; charset=utf-8'
            start_response('200 OK',headers+[('Content-Type',mime),('Content-Length',str(len(body)))]);return [body]
        if path.startswith('/api/admin/') or path=='/api/login' or (path=='/api/data' and method=='POST'):
            if not admin_access.allowed(sso_auth.current(environ,connect),connect):
                return respond('403 Forbidden',{'error':'Este perfil não tem permissão para administrar a Central.'})
        if path in ['/api/admin/users','/api/admin/email-delivery','/api/admin/access']:
            active=session(environ)
            if not active:return respond('401 Unauthorized',{'error':'Entre como administrador.'})
            if method=='GET':
                if path.endswith('/users'):return respond('200 OK',users_directory.read(connect))
                if path.endswith('/access'):return respond('200 OK',admin_access.read(connect))
                import email_auth
                return respond('200 OK',email_auth.delivery_diagnostics(connect,parse_qs(environ.get('QUERY_STRING','')).get('id',[''])[0]))
            if method!='POST' or path not in ['/api/admin/users','/api/admin/access']:return respond('405 Method Not Allowed')
            if environ.get('HTTP_ORIGIN')!=PUBLIC_URL or not hmac.compare_digest(environ.get('HTTP_X_CSRF_TOKEN',''),active[1]):return respond('403 Forbidden',{'error':'Sessão ou origem inválida.'})
            try:
                length=int(environ.get('CONTENT_LENGTH') or 0)
                if not 0<length<=20000 or 'application/json' not in environ.get('CONTENT_TYPE',''):raise ValueError('Dados inválidos.')
                data=json.loads(environ['wsgi.input'].read(length))
                if not isinstance(data,dict):raise ValueError('Dados inválidos.')
                status,out=admin_access.mutate(connect,data) if path.endswith('/access') else users_directory.mutate(connect,data)
            except (ValueError,UnicodeDecodeError) as e:return respond('400 Bad Request',{'error':str(e) or 'Dados inválidos.'})
            return respond(str(status)+(' OK' if status==200 else ' Conflict' if status==409 else ' Not Found'),out)
        if method=='GET' and path=='/api/session':
            active=session(environ);return respond('200 OK',{'authenticated':bool(active),'csrf':active[1] if active else '', 'canAdmin':admin_access.allowed(sso_auth.current(environ,connect),connect)})
        if method=='GET' and path=='/api/data':
            with connect() as con:
                revision=con.execute('SELECT revision FROM state WHERE id=1').fetchone()[0]
                if parse_qs(environ.get('QUERY_STRING','')).get('revision')==[str(revision)]:
                    return respond('304 Not Modified')
                revision,raw=con.execute('SELECT revision,data FROM state WHERE id=1').fetchone()
            data=json.loads(raw);data['revision']=revision;return respond('200 OK',data)
        if method!='POST' or path not in ['/api/login','/api/logout','/api/data']:
            return respond('404 Not Found',{'error':'Endereço não encontrado.'})
        # Browser writes must originate from this deployment. No cross-origin CORS writes.
        origin=environ.get('HTTP_ORIGIN','')
        expected=PUBLIC_URL or (environ.get('wsgi.url_scheme','http')+'://'+environ.get('HTTP_HOST',''))
        if not origin or origin!=expected:return respond('403 Forbidden',{'error':'Origem da solicitação inválida.'})
        active=session(environ)
        if path!='/api/login':
            if not active:return respond('401 Unauthorized',{'error':'Sua sessão expirou. Entre novamente como administrador.'})
            if not hmac.compare_digest(environ.get('HTTP_X_CSRF_TOKEN',''),active[1]):return respond('403 Forbidden',{'error':'Sessão inválida. Entre novamente.'})
        cookie_base='; Path=/; HttpOnly; SameSite=Strict'+('; Secure' if SECURE_COOKIE else '')
        if path=='/api/logout':
            with connect() as con:con.execute('DELETE FROM sessions WHERE token=?',(active[0],))
            return respond('200 OK',{'ok':True},[('Set-Cookie','cj_session=; Max-Age=0'+cookie_base)])
        length=int(environ.get('CONTENT_LENGTH') or 0)
        limit=4096 if path=='/api/login' else MAX_BODY
        if length<=0 or length>limit:return respond('413 Payload Too Large',{'error':'Arquivo ou catálogo acima do limite permitido.'})
        if 'application/json' not in environ.get('CONTENT_TYPE',''):return respond('415 Unsupported Media Type',{'error':'Envie dados JSON.'})
        try:data=json.loads(environ['wsgi.input'].read(length))
        except (ValueError,UnicodeDecodeError):return respond('400 Bad Request',{'error':'Dados inválidos.'})
        if not isinstance(data,dict):return respond('400 Bad Request',{'error':'Dados inválidos.'})
        if path=='/api/login':
            key=hashlib.sha256(environ.get('REMOTE_ADDR','').encode()).hexdigest();now=time.time()
            with connect() as con:
                con.execute('BEGIN IMMEDIATE')
                con.execute('DELETE FROM attempts WHERE until<?',(now,))
                attempt=con.execute('SELECT count,until FROM attempts WHERE key=?',(key,)).fetchone()
                if attempt and attempt[0]>=5:return respond('429 Too Many Requests',{'error':'Muitas tentativas. Aguarde 15 minutos.'})
                user,salt,digest=con.execute('SELECT username,salt,digest FROM admin WHERE id=1').fetchone()
                supplied=data.get('password','');supplied=supplied if isinstance(supplied,str) else ''
                valid=hmac.compare_digest(password_hash(supplied,salt),digest) and data.get('username')==user
                if not valid:
                    con.execute('INSERT OR REPLACE INTO attempts VALUES (?,?,?)',(key,(attempt[0] if attempt else 0)+1,attempt[1] if attempt else now+900))
                    return respond('401 Unauthorized',{'error':'Usuário ou senha incorretos.'})
                con.execute('DELETE FROM attempts WHERE key=?',(key,));con.execute('DELETE FROM sessions WHERE expires<?',(now,))
                token=secrets.token_urlsafe(40);csrf=secrets.token_urlsafe(32)
                con.execute('INSERT INTO sessions VALUES (?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),csrf,now+8*3600))
                identity=sso_auth.current(environ,connect)
                con.execute('INSERT INTO admin_session_profiles VALUES (?,?)',(hashlib.sha256(token.encode()).hexdigest(),identity['email'].lower()))
            return respond('200 OK',{'csrf':csrf},[('Set-Cookie','cj_session='+token+'; Max-Age=28800'+cookie_base)])
        if not valid_data(data):return respond('400 Bad Request',{'error':'O catálogo ou relatório contém dados inválidos.'})
        with connect() as con:
            con.execute('BEGIN IMMEDIATE')
            revision=con.execute('SELECT revision FROM state WHERE id=1').fetchone()[0]
            if data.get('revision')!=revision:return respond('409 Conflict',{'error':'Outro administrador atualizou a Central. Carregue a versão atual antes de salvar.'})
            raw=json.dumps({'items':data['items'],'results':data['results']},ensure_ascii=False)
            con.execute('UPDATE state SET revision=?,data=? WHERE id=1',(revision+1,raw))
        return respond('200 OK',{'revision':revision+1})
    except Exception:
        import logging
        logging.exception('Erro interno na Central CJ')
        return respond('500 Internal Server Error',{'error':'Não foi possível concluir. Tente novamente.'})


if __name__=='__main__':
    if not PASSWORD and not os.environ.get('DATABASE_URL') and not DB.exists():
        print('Cadastro inicial do administrador. A senha não será incluída no HTML.')
        ADMIN_USER=input('Usuário [admin]: ').strip() or 'admin'
        PASSWORD=getpass.getpass('Senha (mínimo 12 caracteres): ')
        if PASSWORD!=getpass.getpass('Confirme a senha: '):raise SystemExit('As senhas não coincidem.')
    initialize()
    import rpa_queue
    rpa_queue.setup(connect)
    sso_auth.setup(connect)
    users_directory.setup(connect)
    admin_access.setup(connect)
    from wsgiref.simple_server import make_server
    SECURE_COOKIE=False
    print('Abra http://localhost:8000 — servidor local para teste.')
    make_server('127.0.0.1',8000,application).serve_forever()
else:
    initialize()
    import rpa_queue
    rpa_queue.setup(connect)
    sso_auth.setup(connect)
    users_directory.setup(connect)
    admin_access.setup(connect)
