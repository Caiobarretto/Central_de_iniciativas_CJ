"""RAI compartilhada: importa dados do HTML sem executar código e preserva todas as competências."""
import json,re,math,time,hmac,hashlib,unicodedata
from pathlib import Path
from urllib.parse import parse_qs,quote
ROOT=Path(__file__).resolve().parent
TEXTS=('centro','objetivo','indicador','descritivo','mensuracao','tipoMeta','responsavel','nucleo','tipo','gatilho')

def numeric(v):return type(v) in (int,float) and math.isfinite(v)
def norm(v):return ' '.join(''.join(c for c in unicodedata.normalize('NFD',str(v).split('|')[0].upper()) if not unicodedata.combining(c)).split())
def short(v):
    words=str(v).split('|')[0].split();return ' '.join([words[0],words[-1]] if len(words)>1 else words).title()
def identifier(r):return str(r['row'])+'-'+str(r['ano'])+'-'+str(r['mes'])
def validate(rows):
    if not isinstance(rows,list) or not 0<len(rows)<=10000:raise ValueError('Use uma base de até 10.000 registros.')
    out=[];seen=set()
    for i,r in enumerate(rows):
        if not isinstance(r,dict):raise ValueError('Registro inválido.')
        clean={k:r.get(k,'') or '' for k in TEXTS}
        if any(not isinstance(v,str) or len(v)>30000 for v in clean.values()) or not clean['responsavel']:raise ValueError('Confira os nomes e campos de texto.')
        for key,low,high in [('row',1,10000000),('ano',2000,2100),('mes',1,12)]:
            value=r.get(key)
            if type(value) is not int or not low<=value<=high:raise ValueError('Confira linha, ano e mês.')
            clean[key]=value
        for key in ('meta','real','cumprimento'):
            value=r.get(key)
            if value is not None and not numeric(value) and not(isinstance(value,str) and len(value)<=150):raise ValueError('Confira os valores de mensuração.')
            if numeric(value) and abs(value)>1e15:raise ValueError('Valor numérico muito grande.')
            clean[key]=value
        clean['melhor']=-1 if r.get('melhor')==-1 else 1;clean['cancelada']='Sim' if str(r.get('cancelada','')).lower().startswith('sim') else None
        formula=r.get('realFormula');clean['realFormula']=formula if formula is None or numeric(formula) or isinstance(formula,str) and len(formula)<=10000 else None
        rotinas=r.get('rotinas',[])
        if not isinstance(rotinas,list) or len(rotinas)>100:raise ValueError('Confira as rotinas.')
        clean['rotinas']=[]
        for j,rt in enumerate(rotinas):
            text=rt.get('rotina','') if isinstance(rt,dict) else None
            if not isinstance(text,str) or len(text)>10000:raise ValueError('Rotina inválida.')
            order=rt.get('ordem',j+1)
            if type(order) is not int or order<1 or order>1000:raise ValueError('Ordem da rotina inválida.')
            comp=rt.get('componente');component=None
            if isinstance(comp,dict) and numeric(comp.get('num')) and numeric(comp.get('den')) and comp['den']>0:component={'num':comp['num'],'den':comp['den'],'pct':comp['num']/comp['den']}
            clean['rotinas'].append({'ordem':order,'rotina':text,'componente':component})
        key=identifier(clean)
        if key in seen:raise ValueError('Há linhas duplicadas no mesmo período: '+key)
        seen.add(key);out.append(clean)
    return out

def setup(connect):
    seed=json.loads((ROOT/'cj'/'rai_seed.json').read_text());rows=validate(seed['rows'])
    data=json.dumps({'rows':rows,'leaders':seed['leaders'],'source':seed['source']},ensure_ascii=False)
    with connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS cj_rai (id INTEGER PRIMARY KEY,revision INTEGER NOT NULL,data TEXT NOT NULL,updated DOUBLE PRECISION NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS cj_rai_updates (id TEXT PRIMARY KEY,applied DOUBLE PRECISION NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS cj_rai_backups (id TEXT PRIMARY KEY,revision INTEGER NOT NULL,data TEXT NOT NULL,updated DOUBLE PRECISION NOT NULL)')
        c.execute('LOCK TABLE cj_rai,cj_rai_updates,cj_rai_backups IN EXCLUSIVE MODE' if hasattr(c,'connection') else 'BEGIN IMMEDIATE')
        c.execute('INSERT INTO cj_rai VALUES (1,1,?,?) ON CONFLICT (id) DO NOTHING',(data,time.time()))
        update=seed.get('updateId')
        if update:
            if not c.execute('SELECT id FROM cj_rai_updates WHERE id=?',(update,)).fetchone():
                revision,previous,updated=c.execute('SELECT revision,data,updated FROM cj_rai WHERE id=1').fetchone()
                if previous!=data:
                    c.execute('INSERT INTO cj_rai_backups VALUES (?,?,?,?) ON CONFLICT (id) DO NOTHING',(update,revision,previous,updated))
                    c.execute('UPDATE cj_rai SET revision=?,data=?,updated=? WHERE id=1',(revision+1,data,time.time()))
                c.execute('INSERT INTO cj_rai_updates VALUES (?,?)',(update,time.time()))

def routine_months(text):
    n=norm(text);mapa={1:('JAN','JANEIRO'),2:('FEV','FEVEREIRO'),3:('MAR','MARCO'),4:('ABR','ABRIL'),5:('MAI','MAIO'),6:('JUN','JUNHO'),7:('JUL','JULHO'),8:('AGO','AGOSTO'),9:('SET','SETEMBRO'),10:('OUT','OUTUBRO'),11:('NOV','NOVEMBRO'),12:('DEZ','DEZEMBRO')}
    return [m for m,words in mapa.items() if any(re.search(r'\b'+w+r'\b',n) for w in words)]
def applicable(r):
    comps=[]
    for a,b in re.findall(r'(?<![A-Z0-9_])\(?\s*(\d+(?:[.,]\d+)?)\s*/\s*(\d+(?:[.,]\d+)?)\s*\)?',str(r.get('realFormula') or ''),re.I):
        a=float(a.replace(',','.'));b=float(b.replace(',','.'))
        if b:comps.append({'num':a,'den':b,'pct':a/b})
    out=[]
    for rt in r.get('rotinas',[]):
        months=routine_months(rt['rotina'])
        if months and r['mes'] not in months:continue
        index=len(out);out.append({**rt,'componente':comps[index] if index<len(comps) else (None if comps else rt.get('componente'))})
    return out

def status(r):
    if r.get('cancelada'):return 'cancelada'
    if any(isinstance(r.get(k),str) and r[k].startswith('#') for k in ('meta','real','cumprimento')):return 'erro-origem'
    achievement=r.get('cumprimento')
    if numeric(achievement):return 'batida' if achievement>=1 else 'gatilho' if achievement>=.5 else 'nao-batida'
    if not numeric(r.get('real')):return 'sem-mensuracao'
    if not numeric(r.get('meta')):return 'mensurada'
    value=calculate(r);return 'batida' if value==1 else 'gatilho' if value==.5 else 'nao-batida'

def calculate(r):
    if not numeric(r.get('real')) or not numeric(r.get('meta')):return None
    real,meta=r['real'],r['meta'];inverse=r.get('melhor')==-1
    if (real<=meta if inverse else real>=meta):return 1
    if norm(r.get('gatilho'))=='SIM' and (real<=meta*1.1 if inverse else real>=meta*.9):return .5
    return 0

def visible_rows(connect,identity,data):
    import users_directory,admin_access
    import module_permissions
    if module_permissions.has(identity,connect,'rai'):return data['rows'],'admin'
    email=str(identity.get('email','')).lower()
    with connect() as c:
        directory=users_directory.list_users(c)
    viewer=next((u for u in directory if u['email']==email and u.get('active',True)),None)
    if not viewer:return [],'individual'
    names={}
    for u in directory:names.setdefault(norm(u['name']),set()).add(u['email'])
    def resolve(label):
        label=norm(label)
        if not label:return None
        if label.lower() in {u['email'] for u in directory}:return label.lower()
        if label in names:return next(iter(names[label])) if len(names[label])==1 else None
        tokens=label.split()
        if len(tokens)<2:return None
        matches=[]
        for name,addresses in names.items():
            remaining=iter(name.split())
            if all(any(word==token for word in remaining) for token in tokens):matches.extend(addresses)
        return matches[0] if len(set(matches))==1 else None
    allowed=[];team=False
    for row in data['rows']:
        owner=resolve(row['responsavel'])
        profile=next((u for u in directory if u['email']==owner),None)
        # Current directory leadership takes precedence; source mapping covers historical people.
        leader=profile.get('leader','') if profile else ''
        if not leader:leader=data.get('leaders',{}).get(norm(row['responsavel']),'')
        own=owner==email
        report=resolve(leader)==email
        if own or report:allowed.append(row)
        if report and not own:team=True
    return allowed,'leadership' if team else 'individual'

def photo_urls(connect,rows):
    import users_directory
    with connect() as c:
        directory=users_directory.list_users(c)
        names={norm(u['name']):u['email'] for u in directory}
        keys=sorted({names.get(norm(r['responsavel'])) for r in rows}-{None})
        photos=dict(c.execute('SELECT email,data FROM profile_photos WHERE email IN ('+','.join('?' for _ in keys)+')',tuple(keys)).fetchall()) if keys else {}
    out={}
    for row in rows:
        name=row['responsavel'];photo=photos.get(names.get(norm(name)))
        if photo:out[name]='/api/cj/rai/photo?person='+quote(name,safe='')+'&v='+hashlib.sha256(photo.encode()).hexdigest()[:20]
    return out

def profile_summary(connect,identity):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    with connect() as c:data=json.loads(c.execute('SELECT data FROM cj_rai WHERE id=1').fetchone()[0])
    name=norm(identity.get('name',''));now=datetime.now(ZoneInfo('America/Sao_Paulo'));current=now.year*12+now.month
    own=[{**r,'status':status(r)} for r in data['rows'] if norm(r['responsavel'])==name and not r['cancelada'] and r['ano']*12+r['mes']<=current]
    measured=[r for r in own if numeric(r.get('real')) and r['status']!='erro-origem']
    if not measured:return {'available':False,'message':'Ainda não há resultados RAI mensurados para o seu perfil.'}
    year,month=max((r['ano'],r['mes']) for r in measured)
    rows=[r for r in own if r['ano']==year and r['mes']==month];valid=[r for r in rows if numeric(r.get('real')) and r['status']!='erro-origem']
    grd=[r['real'] for r in valid if r['tipo']=='GRD'];goals=[r for r in rows if r['tipo']!='GRD' and r['status'] in ('batida','gatilho','nao-batida')]
    return {'available':True,'year':year,'month':month,'grd':sum(grd)/len(grd) if grd else None,'measured':len(valid),'total':len(rows),'goalsMet':sum(r['status'] in ('batida','gatilho') for r in goals),'goalsMeasured':len(goals),'url':'/resultados-cj?module=rai&person='+quote(rows[0]['responsavel'],safe='')+'&month='+str(year)+'-'+str(month).zfill(2)}

def get(connect,identity,admin=False,csrf=''):
    with connect() as c:revision,raw,updated=c.execute('SELECT revision,data,updated FROM cj_rai WHERE id=1').fetchone()
    data=json.loads(raw);rows,scope=visible_rows(connect,identity,data);years=sorted({r['ano'] for r in rows},reverse=True)
    urls=photo_urls(connect,rows)
    from team_access import directory,resolve
    users=directory(connect);profiles={norm(u['name']):u for u in users};by_email={u['email']:u for u in users}
    def current_leader(r):
        label=profiles.get(norm(r['responsavel']),{}).get('leader') or data.get('leaders',{}).get(norm(r['responsavel']),'')
        return by_email.get(resolve(label,users),{}).get('name',label).split('|')[0].strip()
    enriched=[{**r,'photoUrl':urls.get(r['responsavel'],''),'id':identifier(r),'displayName':short(r['responsavel']),'status':status(r),'applicableRoutines':applicable(r),'leader':current_leader(r),'currentSubunit':profiles.get(norm(r['responsavel']),{}).get('subunit',''),'percentLike':numeric(r.get('meta')) and abs(r['meta'])<=1.5 and (not numeric(r.get('real')) or abs(r['real'])<=1.5)} for r in rows]
    return {'rows':enriched,'years':years,'revision':revision,'updated':updated,'source':data.get('source',''),'scope':scope,'canAdmin':admin,'csrf':csrf if admin else '','user':{'name':identity.get('name',''),'email':identity.get('email','')}}

def mutate(connect,payload):
    action=payload.get('action')
    with connect() as c:
        c.execute('LOCK TABLE cj_rai IN EXCLUSIVE MODE' if hasattr(c,'connection') else 'BEGIN IMMEDIATE')
        revision,raw=c.execute('SELECT revision,data FROM cj_rai WHERE id=1').fetchone()
        if payload.get('revision')!=revision:return 409,{'error':'A RAI mudou. Atualize antes de salvar para não substituir outra edição.'}
        data=json.loads(raw)
        if action=='import':
            data['rows']=validate(payload.get('rows'));data['source']=str(payload.get('source','Base importada'))[:200]
            if payload.get('leaders') is not None:
                leaders=payload['leaders']
                if not isinstance(leaders,dict) or len(leaders)>2000 or any(not isinstance(k,str) or not isinstance(v,str) or max(len(k),len(v))>200 for k,v in leaders.items()):raise ValueError('Confira os dados de liderança.')
                data['leaders']={norm(k):v for k,v in leaders.items()}
        elif action=='update':
            row=next((r for r in data['rows'] if identifier(r)==payload.get('id')),None)
            if not row:return 404,{'error':'Indicador não encontrado.'}
            for field in ('meta','real'):
                value=payload.get(field)
                if value is not None and (not numeric(value) or abs(value)>1e15):raise ValueError('Confira meta e resultado.')
                row[field]=value
            row['melhor']=-1 if payload.get('melhor')==-1 else 1;row['gatilho']='Sim' if payload.get('gatilho') is True else 'Não';row['cancelada']='Sim' if payload.get('cancelada') is True else None;row['realFormula']=None
            if payload.get('components') is not None:
                items=payload['components'];required=applicable(row)
                if not isinstance(items,list) or not required or len(items)!=len(required):raise ValueError('Preencha todas as rotinas aplicáveis.')
                by_order={i.get('ordem'):i for i in items if isinstance(i,dict)}
                if len(by_order)!=len(required):raise ValueError('Rotinas duplicadas ou inválidas.')
                parts=[]
                for rt in required:
                    comp=by_order.get(rt['ordem'],{});a,b=comp.get('num'),comp.get('den')
                    if not numeric(a) or not numeric(b) or a<0 or b<=0 or max(a,b)>1e12:raise ValueError('Use numerador não negativo e denominador maior que zero em cada rotina.')
                    part={'num':a,'den':b,'pct':a/b};parts.append(part)
                    for original in row['rotinas']:
                        if original['ordem']==rt['ordem']:original['componente']=part
                row['real']=sum(p['pct'] for p in parts)/len(parts);row['realFormula']='=('+ '+'.join('('+str(p['num'])+'/'+str(p['den'])+')' for p in parts)+')/'+str(len(parts))
            row['cumprimento']=calculate(row)
        else:raise ValueError('Ação inválida.')
        c.execute('UPDATE cj_rai SET revision=?,data=?,updated=? WHERE id=1',(revision+1,json.dumps(data,ensure_ascii=False),time.time()))
    return 200,{'ok':True,'revision':revision+1}

def handle(env,start,server):
    def reply(code,data):
        raw=json.dumps(data,ensure_ascii=False).encode();start(str(code)+' '+{200:'OK',400:'Bad Request',401:'Unauthorized',403:'Forbidden',404:'Not Found',405:'Method Not Allowed',409:'Conflict'}[code],[('Content-Type','application/json; charset=utf-8'),('Content-Length',str(len(raw))),('Cache-Control','no-store'),('X-Content-Type-Options','nosniff')]);return [raw]
    user=server.sso_auth.current(env,server.connect)
    if not user:return reply(401,{'error':'Entre na Central para acessar a RAI.'})
    path=env.get('PATH_INFO','');method=env.get('REQUEST_METHOD','GET')
    if path=='/api/cj/rai/profile':
        return reply(200,profile_summary(server.connect,user)) if method=='GET' else reply(405,{})
    if path=='/api/cj/rai/photo':
        if method!='GET':return reply(405,{})
        import base64,users_directory
        person=parse_qs(env.get('QUERY_STRING','')).get('person',[''])[0]
        with server.connect() as c:stored=json.loads(c.execute('SELECT data FROM cj_rai WHERE id=1').fetchone()[0])
        visible,_=visible_rows(server.connect,user,stored)
        if not any(r['responsavel']==person for r in visible):return reply(403,{'error':'Foto indisponível para este perfil.'})
        with server.connect() as c:
            matches=[u['email'] for u in users_directory.list_users(c) if norm(u['name'])==norm(person)]
            photo=c.execute('SELECT data FROM profile_photos WHERE email=?',(matches[0],)).fetchone() if len(matches)==1 else None
        if not photo:return reply(404,{})
        raw=base64.b64decode(photo[0].split(',',1)[1]);start('200 OK',[('Content-Type','image/jpeg'),('Content-Length',str(len(raw))),('Cache-Control','private, max-age=60'),('X-Content-Type-Options','nosniff')]);return [raw]
    active=server.session(env)
    if method=='GET':return reply(200,get(server.connect,user,bool(active),active[1] if active else ''))
    if method!='POST':return reply(405,{})
    if not active or env.get('HTTP_ORIGIN')!=server.PUBLIC_URL or not hmac.compare_digest(env.get('HTTP_X_CSRF_TOKEN',''),active[1]):return reply(403,{'error':'Entre como administrador para editar a RAI.'})
    try:
        size=int(env.get('CONTENT_LENGTH') or 0)
        if not 0<size<=8_000_000 or 'application/json' not in env.get('CONTENT_TYPE',''):raise ValueError('Base inválida ou acima de 8 MB.')
        payload=json.loads(env['wsgi.input'].read(size))
        if not isinstance(payload,dict):raise ValueError('Dados inválidos.')
        code,out=mutate(server.connect,payload);return reply(code,out)
    except (ValueError,TypeError,KeyError,AttributeError,UnicodeDecodeError) as e:return reply(400,{'error':str(e) or 'Confira os dados enviados.'})
