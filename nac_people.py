"""Fotos compartilhadas, cadastros externos e homenagem mensal do NAC."""
import base64,hashlib,hmac,json,re,time
from datetime import date,timedelta
from urllib.parse import quote,parse_qs
import users_directory

EXTERNAL={'external:arruda':'Arruda','external:igor':'Igor Pereira'}
FIELDS=('name','email','role','unit','subunit','leader','costCenter','company','employment','servicesForTeams')

def setup(connect):
    with connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS nac_people (id TEXT PRIMARY KEY,data TEXT NOT NULL,version INTEGER NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS nac_seen (email TEXT NOT NULL,month TEXT NOT NULL,seen DOUBLE PRECISION NOT NULL,PRIMARY KEY(email,month))')
        for key,name in EXTERNAL.items():
            data={k:'' for k in FIELDS};data.update(name=name,unit='NAC',subunit='NAC',active=True)
            c.execute('INSERT INTO nac_people VALUES (?,?,1) ON CONFLICT (id) DO NOTHING',(key,json.dumps(data,ensure_ascii=False)))

def external(c):
    return [{**json.loads(raw),'id':key,'key':key,'external':True,'version':version} for key,raw,version in c.execute('SELECT id,data,version FROM nac_people').fetchall() if key in EXTERNAL]

def photos(c,keys):
    # URLs leves: bytes das fotos são baixados uma única vez pelo navegador.
    if not keys:return {}
    rows=c.execute('SELECT email,data FROM profile_photos WHERE email IN ('+','.join('?' for _ in keys)+')',tuple(keys)).fetchall()
    return {key:'/api/nac/photo?key='+quote(key,safe='')+'&v='+hashlib.sha256(value.encode()).hexdigest()[:20] for key,value in rows if value}

def people(connect):
    with connect() as c:
        users=users_directory.list_users(c)+external(c);version=c.execute('SELECT version FROM directory_meta WHERE id=1').fetchone()[0]
        urls=photos(c,[u.get('key',u['email']) for u in users])
    return {'users':[{**u,'photoUrl':urls.get(u.get('key',u['email']),'')} for u in users],'version':version}

def photo_value(value):
    if not isinstance(value,str):raise ValueError('Foto inválida.')
    if not value:return ''
    if not value.startswith('data:image/jpeg;base64,') or len(value)>540000:raise ValueError('Use uma foto JPEG de até 400 KB.')
    raw=base64.b64decode(value.split(',',1)[1],validate=True)
    if not 10<len(raw)<=400000 or not raw.startswith(b'\xff\xd8\xff') or not raw.endswith(b'\xff\xd9'):raise ValueError('Use uma foto JPEG válida.')
    return value

def bump(c):c.execute('UPDATE nac_meta SET revision=revision+1 WHERE id=1')
def admin_mutate(connect,data):
    action=data.get('action');key=data.get('id');value=data.get('user',{})
    if action=='photo':photo=photo_value(data.get('photo'))
    elif action not in ('save','delete') or key not in EXTERNAL:raise ValueError('Ação inválida.')
    if action=='save':
        if not isinstance(value,dict):raise ValueError('Cadastro inválido.')
        clean={k:value.get(k,'').strip() if isinstance(value.get(k,''),str) else '' for k in FIELDS}
        if len(clean['name'])<2 or any(len(v)>150 or any(ord(ch)<32 for ch in v) for v in clean.values()):raise ValueError('Informe nome e campos com até 150 caracteres.')
        clean['email']=clean['email'].lower()
        if clean['email'] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',clean['email']):raise ValueError('Confira o e-mail.')
        if type(value.get('active',True)) is not bool:raise ValueError('Situação inválida.')
        clean['active']=value.get('active',True)
    with connect() as c:
        c.execute('LOCK TABLE directory_meta,nac_people,nac_meta IN EXCLUSIVE MODE' if hasattr(c,'connection') else 'BEGIN IMMEDIATE')
        if action=='photo':
            if key not in EXTERNAL and not c.execute('SELECT id FROM directory_users WHERE email=?',(key,)).fetchone():return 404,{'error':'Integrante não encontrado.'}
            if photo:c.execute('INSERT INTO profile_photos VALUES (?,?) ON CONFLICT (email) DO UPDATE SET data=excluded.data',(key,photo))
            else:c.execute('DELETE FROM profile_photos WHERE email=?',(key,))
        else:
            row=c.execute('SELECT data,version FROM nac_people WHERE id=?',(key,)).fetchone()
            if not row:return 404,{'error':'Integrante não encontrado.'}
            if data.get('version')!=row[1]:return 409,{'error':'O cadastro mudou. Reabra antes de salvar.'}
            if action=='delete':clean=json.loads(row[0]);clean['active']=False
            c.execute('UPDATE nac_people SET data=?,version=version+1 WHERE id=?',(json.dumps(clean,ensure_ascii=False),key))
        bump(c)
    return 200,{'ok':True}

def previous_month(today):return (date.fromisoformat(today).replace(day=1)-timedelta(days=1)).isoformat()[:7]
def celebration(connect,identity):
    import nac_addon
    month=previous_month(nac_addon.today())
    with connect() as c:
        if c.execute('SELECT seen FROM nac_seen WHERE email=? AND month=?',(identity['email'],month)).fetchone():return {'show':False}
    # Inclui integrantes que ficaram inativas depois do encerramento do mês.
    people=nac_addon.reporting_roster(connect,month);keys=[p['email'] for p in people]
    if not keys:return {'show':False}
    with connect() as c:
        rows=c.execute('SELECT email,COUNT(*) FROM nac_agreements WHERE active=1 AND closed LIKE ? AND email IN ('+','.join('?' for _ in keys)+') GROUP BY email',(month+'-%',*keys)).fetchall()
        if not rows:return {'show':False}
        top=max(r[1] for r in rows);total=sum(r[1] for r in rows);counts=dict(rows)
        winners=[{**p,'count':top,'share':round(top/total*100,1)} for p in people if counts.get(p['email'])==top]
        goal=c.execute('SELECT target FROM nac_goals WHERE month=?',(month,)).fetchone()
    return {'show':True,'month':month,'winners':winners,'total':total,'goal':goal[0] if goal else 0,'csrf':identity.get('csrf','')}

def handle(env,start,server):
    import nac_addon
    def reply(code,data=None,body=None,mime='application/json; charset=utf-8',extra=()):
        raw=body if body is not None else json.dumps(data or {},ensure_ascii=False).encode()
        start(str(code)+' '+{200:'OK',400:'Bad Request',401:'Unauthorized',403:'Forbidden',404:'Not Found',405:'Method Not Allowed',409:'Conflict'}[code],[('Content-Type',mime),('Cache-Control','no-store'),('X-Content-Type-Options','nosniff'),('Content-Length',str(len(raw)))]+list(extra));return [raw]
    try:
        user=server.sso_auth.current(env,server.connect)
        if not user:return reply(401,{'error':'Entre na Central para continuar.'})
        path=env.get('PATH_INFO');method=env.get('REQUEST_METHOD','GET');admin=server.session(env)
        if path=='/api/nac/people' and not admin:return reply(403,{'error':'Entre como administrador.'})
        if method=='GET':
            if path=='/api/nac/people':return reply(200,people(server.connect))
            if path=='/api/nac/celebration':return reply(200,celebration(server.connect,user))
            key=parse_qs(env.get('QUERY_STRING','')).get('key',[''])[0]
            if len(key)>150:return reply(400)
            with server.connect() as c:
                # Fotos apenas de integrantes do NAC; demais fotos só na gestão administrativa.
                permitted=bool(admin) or key in {p['email'] for p in nac_addon.roster(server.connect,include_inactive=True)}
                if not permitted:return reply(403)
                row=c.execute('SELECT data FROM profile_photos WHERE email=?',(key,)).fetchone()
            if not row:return reply(404)
            value=photo_value(row[0]);raw=base64.b64decode(value.split(',',1)[1],validate=True)
            start('200 OK',[('Content-Type','image/jpeg'),('Content-Length',str(len(raw))),('Cache-Control','private, max-age=60'),('X-Content-Type-Options','nosniff')]);return [raw]
        if method!='POST' or path=='/api/nac/photo':return reply(405)
        csrf=admin[1] if path=='/api/nac/people' else user.get('csrf','')
        if env.get('HTTP_ORIGIN')!=server.PUBLIC_URL or not csrf or not hmac.compare_digest(env.get('HTTP_X_CSRF_TOKEN',''),csrf):return reply(403,{'error':'Sessão inválida. Atualize a Central.'})
        size=int(env.get('CONTENT_LENGTH') or 0)
        if not 0<size<=560000 or 'application/json' not in env.get('CONTENT_TYPE',''):raise ValueError('Dados inválidos.')
        data=json.loads(env['wsgi.input'].read(size))
        if not isinstance(data,dict):raise ValueError('Dados inválidos.')
        if path=='/api/nac/people':
            code,out=admin_mutate(server.connect,data);return reply(code,out)
        month=data.get('month')
        if month!=previous_month(nac_addon.today()):raise ValueError('Período inválido.')
        with server.connect() as c:c.execute('INSERT INTO nac_seen VALUES (?,?,?) ON CONFLICT (email,month) DO NOTHING',(user['email'],month,time.time()))
        return reply(200,{'ok':True})
    except (ValueError,TypeError,UnicodeDecodeError):return reply(400,{'error':'Confira o cadastro ou o formato da foto.'})
