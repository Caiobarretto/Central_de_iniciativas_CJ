"""Datas de pessoas, contratos de estágio e homenagens, com escopos no servidor."""
import json,time,secrets,hashlib,base64
from datetime import datetime,date,timedelta
from zoneinfo import ZoneInfo
from urllib.parse import parse_qs,quote
import module_permissions as permissions
from team_access import directory,reports,short
TZ=ZoneInfo('America/Sao_Paulo')
def today():return datetime.now(TZ).date()
def setup(connect):
    with connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS cj_people_dates (email TEXT PRIMARY KEY,data TEXT NOT NULL,version INTEGER NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS cj_people_seen (email TEXT NOT NULL,event TEXT NOT NULL,seen DOUBLE PRECISION NOT NULL,PRIMARY KEY(email,event))')
def can_admin(identity,connect):return permissions.has(identity,connect,'pessoas')
def parse_date(v):
    if not v:return ''
    if not isinstance(v,str):raise ValueError('Data inválida.')
    d=date.fromisoformat(v)
    if d.year<1900 or d.year>2100:raise ValueError('Ano inválido.')
    return d.isoformat()
def anniversary(value,year):
    d=date.fromisoformat(value)
    try:return d.replace(year=year)
    except ValueError:return date(year,3,1)
def photo_urls(c,emails):
    if not emails:return {}
    rows=c.execute('SELECT email,data FROM profile_photos WHERE email IN ('+','.join('?' for _ in emails)+')',tuple(emails)).fetchall()
    return {email:'/api/people/photo?email='+quote(email,safe='')+'&v='+hashlib.sha256(raw.encode()).hexdigest()[:16] for email,raw in rows}
def state(connect,identity,month):
    date.fromisoformat(month+'-01');users=[u for u in directory(connect) if u.get('active',True)];allowed=reports(identity,users);admin=can_admin(identity,connect);now=today()
    with connect() as c:
        stored={e:{**json.loads(raw),'version':v} for e,raw,v in c.execute('SELECT email,data,version FROM cj_people_dates').fetchall()};photos=photo_urls(c,[u['email'] for u in users])
    people=[];birthdays=[];contracts=[]
    for u in users:
        email=u['email'];d=stored.get(email,{});public={'email':email,'name':short(u['name']),'photoUrl':photos.get(email,''),'unit':u.get('subunit','')}
        if admin:people.append({**public,**d,'isIntern':d.get('isIntern','ESTAG' in u.get('role','').upper()),'version':d.get('version',0)})
        for kind,key in [('birthday','birthDate'),('company','companyStart')]:
            if not d.get(key):continue
            event=anniversary(d[key],int(month[:4]));years=event.year-date.fromisoformat(d[key]).year
            if event.isoformat()[:7]!=month or (kind=='company' and years<1):continue
            birthdays.append({**public,'kind':kind,'day':event.day,'month':event.month,'years':years if kind=='company' else None})
        intern=d.get('isIntern','ESTAG' in u.get('role','').upper())
        if intern and (admin or email in allowed):
            end=d.get('internEnd','');left=(date.fromisoformat(end)-now).days if end else None
            contracts.append({**public,'start':d.get('internStart',''),'end':end,'daysLeft':left,'status':'Sem validade cadastrada' if left is None else 'Encerrado' if left<0 else 'Vence em até 30 dias' if left<=30 else 'Vigente','version':d.get('version',0)})
    birthdays.sort(key=lambda r:(r['day'],r['name']));contracts.sort(key=lambda r:r['end'] or '9999')
    return {'month':month,'birthdays':birthdays,'contracts':contracts,'people':people,'canAdmin':admin,'canSeeContracts':admin or bool(allowed),'today':now.isoformat()}
def save(connect,identity,p):
    users=directory(connect);email=p.get('email');u=next((u for u in users if u['email']==email and u.get('active',True)),None)
    if not u:raise ValueError('Selecione um usuário ativo da Central.')
    d={k:parse_date(p.get(k,'')) for k in ('birthDate','companyStart','internStart','internEnd')}
    if d['birthDate'] and d['birthDate']>today().isoformat():raise ValueError('Nascimento não pode estar no futuro.')
    if d['internStart'] and d['internEnd'] and d['internEnd']<d['internStart']:raise ValueError('O término do estágio precisa ser após o início.')
    d['isIntern']=p.get('isIntern') is True
    with connect() as c:
        c.execute('LOCK TABLE cj_people_dates IN EXCLUSIVE MODE' if hasattr(c,'connection') else 'BEGIN IMMEDIATE')
        row=c.execute('SELECT version FROM cj_people_dates WHERE email=?',(email,)).fetchone();v=row[0] if row else 0
        if p.get('version')!=v:return 409,{'error':'Os dados foram alterados. Recarregue antes de salvar.'}
        c.execute('INSERT INTO cj_people_dates VALUES (?,?,?) ON CONFLICT (email) DO UPDATE SET data=excluded.data,version=excluded.version',(email,json.dumps(d),v+1))
    return 200,{'ok':True}
def celebration(connect,identity):
    now=today();events=[]
    with connect() as c:
        row=c.execute('SELECT data FROM cj_people_dates WHERE email=?',(identity['email'],)).fetchone();seen={r[0] for r in c.execute('SELECT event FROM cj_people_seen WHERE email=?',(identity['email'],)).fetchall()}
    d=json.loads(row[0]) if row else {}
    for kind,key in [('birthday','birthDate'),('company','companyStart')]:
        if not d.get(key):continue
        for day in (now,now-timedelta(days=1)):
            event=anniversary(d[key],day.year);years=event.year-date.fromisoformat(d[key]).year
            event_key=kind+':'+event.isoformat()+':'+now.isoformat()
            if event!=day or (kind=='company' and years<1) or event_key in seen:continue
            events.append({'id':event_key,'kind':kind,'years':years if kind=='company' else None,'after':day!=now,'name':short(identity['name'])})
    return {'events':events,'csrf':identity.get('csrf','')}
def reply(start,code,obj=None,raw=None,mime='application/json; charset=utf-8'):
    body=raw if raw is not None else json.dumps(obj or {},ensure_ascii=False).encode();start(str(code)+' '+{200:'OK',400:'Bad Request',401:'Unauthorized',403:'Forbidden',404:'Not Found',405:'Method Not Allowed',409:'Conflict'}[code],[('Content-Type',mime),('Content-Length',str(len(body))),('Cache-Control','no-store')]);return [body]
def payload(env,limit=1000000):
    n=int(env.get('CONTENT_LENGTH') or 0)
    if not 0<n<=limit or 'application/json' not in env.get('CONTENT_TYPE',''):raise ValueError('Dados inválidos.')
    p=json.loads(env['wsgi.input'].read(n))
    if not isinstance(p,dict):raise ValueError('Dados inválidos.')
    return p

def handle(env,start,server):
    import hmac
    user=server.sso_auth.current(env,server.connect)
    if not user:
        if env.get('PATH_INFO')=='/pessoas':
            start('302 Found',[('Location','/'),('Cache-Control','no-store'),('Content-Length','0')]);return [b'']
        return reply(start,401,{'error':'Entre na Central.'})
    path=env['PATH_INFO'];method=env.get('REQUEST_METHOD','GET');q=parse_qs(env.get('QUERY_STRING',''))
    try:
        if path=='/pessoas':
            if method!='GET':return reply(start,405,{})
            from pathlib import Path
            return reply(start,200,raw=(Path(__file__).parent/'cj'/'pessoas.html').read_bytes(),mime='text/html; charset=utf-8')
        if method=='GET':
            if path=='/api/people/state':return reply(start,200,state(server.connect,user,q.get('month',[today().isoformat()[:7]])[0]))
            if path=='/api/people/celebration':return reply(start,200,celebration(server.connect,user))
            if path=='/api/people/photo':
                email=q.get('email',[''])[0]
                if email not in {u['email'] for u in directory(server.connect) if u.get('active',True)}:return reply(start,404,{})
                with server.connect() as c:row=c.execute('SELECT data FROM profile_photos WHERE email=?',(email,)).fetchone()
                if not row:return reply(start,404,{})
                return reply(start,200,raw=base64.b64decode(row[0].split(',',1)[1]),mime='image/jpeg')
        if method!='POST':return reply(start,405,{})
        if env.get('HTTP_ORIGIN')!=server.PUBLIC_URL:return reply(start,403,{})
        if path=='/api/people/seen':
            if not user.get('csrf') or not hmac.compare_digest(env.get('HTTP_X_CSRF_TOKEN',''),user.get('csrf','')):return reply(start,403,{})
            p=payload(env);valid={e['id'] for e in celebration(server.connect,user)['events']}
            if not isinstance(p.get('events'),list) or len(p['events'])>4 or any(k not in valid for k in p['events']):raise ValueError('Homenagem inválida.')
            with server.connect() as c:
                for k in p['events']:c.execute('INSERT INTO cj_people_seen VALUES (?,?,?) ON CONFLICT (email,event) DO NOTHING',(user['email'],k,time.time()))
            return reply(start,200,{'ok':True})
        if path!='/api/people/dates':return reply(start,404,{})
        active=server.session(env)
        if not can_admin(user,server.connect) or not active or not hmac.compare_digest(env.get('HTTP_X_CSRF_TOKEN',''),active[1]):return reply(start,403,{'error':'Entre como admin do módulo Pessoas para editar.'})
        code,out=save(server.connect,user,payload(env));return reply(start,code,out)
    except (ValueError,KeyError,TypeError):return reply(start,400,{'error':'Confira os dados, as datas e a versão do cadastro.'})
