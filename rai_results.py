"""RAI compartilhada: importa dados do HTML sem executar código e preserva todas as competências."""
import json,re,math,time,hmac,hashlib,unicodedata
from pathlib import Path
from urllib.parse import parse_qs
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
    with connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS cj_rai (id INTEGER PRIMARY KEY,revision INTEGER NOT NULL,data TEXT NOT NULL,updated DOUBLE PRECISION NOT NULL)')
        c.execute('INSERT INTO cj_rai VALUES (1,1,?,?) ON CONFLICT (id) DO NOTHING',(json.dumps({'rows':rows,'leaders':seed['leaders'],'source':seed['source']},ensure_ascii=False),time.time()))

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

def get(connect,identity,admin=False,csrf=''):
    with connect() as c:revision,raw,updated=c.execute('SELECT revision,data,updated FROM cj_rai WHERE id=1').fetchone()
    data=json.loads(raw);rows=data['rows'];years=sorted({r['ano'] for r in rows},reverse=True)
    enriched=[{**r,'id':identifier(r),'displayName':short(r['responsavel']),'status':status(r),'applicableRoutines':applicable(r),'leader':data.get('leaders',{}).get(norm(r['responsavel']),''),'percentLike':numeric(r.get('meta')) and abs(r['meta'])<=1.5 and (not numeric(r.get('real')) or abs(r['real'])<=1.5)} for r in rows]
    return {'rows':enriched,'years':years,'revision':revision,'updated':updated,'source':data.get('source',''),'canAdmin':admin,'csrf':csrf if admin else '','user':{'name':identity.get('name',''),'email':identity.get('email','')}}

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
    active=server.session(env);method=env.get('REQUEST_METHOD','GET')
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
