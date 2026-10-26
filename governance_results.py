"""IGP e IQN compartilhados por competência, com edição e histórico."""
import json,time,re,math,hmac
from pathlib import Path
from urllib.parse import parse_qs
import module_permissions as permissions
from people_hub import reply,payload

def setup(connect):
    seed=json.loads((Path(__file__).parent/'cj'/'people_indicators_seed.json').read_text())
    with connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS cj_governance (kind TEXT NOT NULL,period TEXT NOT NULL,revision INTEGER NOT NULL,data TEXT NOT NULL,updated DOUBLE PRECISION NOT NULL,PRIMARY KEY(kind,period))')
        c.execute('CREATE TABLE IF NOT EXISTS cj_governance_audit (id TEXT PRIMARY KEY,kind TEXT NOT NULL,period TEXT NOT NULL,data TEXT NOT NULL,actor TEXT NOT NULL,updated DOUBLE PRECISION NOT NULL)')
        for kind,periods in seed.items():
            for period,data in periods.items():c.execute('INSERT INTO cj_governance VALUES (?,?,1,?,?) ON CONFLICT (kind,period) DO NOTHING',(kind,period,json.dumps(data,ensure_ascii=False),time.time()))
def period_value(v):
    if not isinstance(v,str) or not re.fullmatch(r'20\d\d-(?:0[1-9]|1[0-2]|Q[1-4])',v):raise ValueError('Competência inválida.')
    return v

def validate(d):
    if not isinstance(d,dict):raise ValueError('Dados inválidos.')
    out={k:str(d.get(k,'') or '')[:2000] for k in ('note','source')}
    def number(v):
        if v is not None and (type(v) not in (int,float) or not math.isfinite(v) or abs(v)>1e15):raise ValueError('Confira os valores numéricos.')
        return v
    out.update(overall=number(d.get('overall')),target=number(d.get('target')))
    rows=d.get('rows')
    if not isinstance(rows,list) or len(rows)>200:raise ValueError('Use até 200 indicadores.')
    out['rows']=[]
    for r in rows:
        if not isinstance(r,dict) or not isinstance(r.get('label'),str) or not r['label'].strip():raise ValueError('Informe o nome dos indicadores.')
        out['rows'].append({**{k:str(r.get(k,'') or '')[:500] for k in ('label','unit','pillar','direction')},**{k:number(r.get(k)) for k in ('target','real','weight','score','performance')}})
    pillars=d.get('pillars',{})
    if not isinstance(pillars,dict) or len(pillars)>30:raise ValueError('Pilares inválidos.')
    out['pillars']={str(k)[:100]:number(v) for k,v in pillars.items()}
    return out

def handle(env,start,server):
    import secrets
    identity=server.sso_auth.current(env,server.connect)
    if not identity:return reply(start,401,{'error':'Entre na Central.'})
    kind=env['PATH_INFO'].rsplit('/',1)[-1]
    if kind not in ('igp','iqn'):return reply(start,404,{})
    try:
        period=period_value(parse_qs(env.get('QUERY_STRING','')).get('period',['2026-Q3' if kind=='igp' else '2026-Q2'])[0]);method=env.get('REQUEST_METHOD','GET');active=server.session(env)
        if method=='GET':
            with server.connect() as c:
                row=c.execute('SELECT revision,data,updated FROM cj_governance WHERE kind=? AND period=?',(kind,period)).fetchone()
                all_rows=c.execute('SELECT period,data FROM cj_governance WHERE kind=? ORDER BY period',(kind,)).fetchall()
            return reply(start,200,{'kind':kind,'period':period,'revision':row[0] if row else 0,'data':json.loads(row[1]) if row else {'overall':None,'target':None,'rows':[],'pillars':{},'note':'Nenhuma mensuração cadastrada nesta competência.','source':''},'available':bool(row),'history':[{'period':p,'overall':json.loads(raw).get('overall')} for p,raw in all_rows],'template':[{**r,**{k:None for k in ('target','real','weight','performance','score')}} for r in list(json.loads((Path(__file__).parent/'cj'/'people_indicators_seed.json').read_text())[kind].values())[-1]['rows']],'canAdmin':bool(active),'csrf':active[1] if active else ''})
        if method!='POST':return reply(start,405,{})
        if not permissions.has(identity,server.connect,kind) or not active or env.get('HTTP_ORIGIN')!=server.PUBLIC_URL or not hmac.compare_digest(env.get('HTTP_X_CSRF_TOKEN',''),active[1]):return reply(start,403,{'error':'Entre como admin deste módulo para editar.'})
        p=payload(env);data=validate(p.get('data'))
        with server.connect() as c:
            c.execute('LOCK TABLE cj_governance IN EXCLUSIVE MODE' if hasattr(c,'connection') else 'BEGIN IMMEDIATE')
            row=c.execute('SELECT revision,data FROM cj_governance WHERE kind=? AND period=?',(kind,period)).fetchone();v=row[0] if row else 0
            if p.get('revision')!=v:return reply(start,409,{'error':'A competência mudou. Atualize antes de salvar.'})
            if row:c.execute('INSERT INTO cj_governance_audit VALUES (?,?,?,?,?,?)',(secrets.token_urlsafe(16),kind,period,row[1],identity['email'],time.time()))
            c.execute('INSERT INTO cj_governance VALUES (?,?,?,?,?) ON CONFLICT (kind,period) DO UPDATE SET revision=excluded.revision,data=excluded.data,updated=excluded.updated',(kind,period,v+1,json.dumps(data,ensure_ascii=False),time.time()))
        return reply(start,200,{'ok':True})
    except (ValueError,TypeError,KeyError):return reply(start,400,{'error':'Confira a competência e os valores dos indicadores.'})
