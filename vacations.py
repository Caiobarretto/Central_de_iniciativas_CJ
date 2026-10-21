"""Calendário de férias compartilhado, com edição administrativa e controle de revisão."""
import json,re,time,unicodedata
from collections import Counter
from datetime import date
from pathlib import Path
ROOT=Path(__file__).resolve().parent
FIELDS={'name':160,'nucleus':160,'subnucleus':160,'notes':2000,'leaderValidation':120,'dpValidation':120,'glpiId':100,'email':150}

def setup(connect):
    with connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS vacations_state (id INTEGER PRIMARY KEY,revision INTEGER NOT NULL,data TEXT NOT NULL,updated DOUBLE PRECISION NOT NULL)')
        if not c.execute('SELECT 1 FROM vacations_state WHERE id=1').fetchone():
            seed=json.loads((ROOT/'vacations_seed.json').read_text(encoding='utf-8'));validate(seed)
            c.execute('INSERT INTO vacations_state VALUES (1,1,?,?) ON CONFLICT (id) DO NOTHING',(json.dumps(seed,ensure_ascii=False),time.time()))

def validate(data):
    if not isinstance(data,dict) or not isinstance(data.get('planningYear'),int) or not 2000<=data['planningYear']<=2100:raise ValueError('Ano de planejamento inválido.')
    if not isinstance(data.get('source',''),str) or len(data.get('source',''))>300:raise ValueError('Fonte inválida.')
    rows=data.get('employees')
    if not isinstance(rows,list) or len(rows)>500:raise ValueError('Limite de 500 integrantes.')
    ids=set();period_ids=set();emails=set()
    for row in rows:
        if not isinstance(row,dict) or not isinstance(row.get('id'),str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',row['id']) or row['id'] in ids:raise ValueError('Identificador de integrante inválido ou repetido.')
        ids.add(row['id'])
        for field,limit in FIELDS.items():
            if not isinstance(row.get(field,''),str) or len(row.get(field,''))>limit:raise ValueError('Campo inválido: '+field)
        if not row.get('name','').strip():raise ValueError('Informe o nome do integrante.')
        email=row.get('email','').strip().lower()
        if email:
            if not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@queirozcavalcanti\.adv\.br",email) or email in emails:raise ValueError('Informe um e-mail institucional válido e vinculado a um único integrante.')
            emails.add(email)
        periods=row.get('periods')
        if not isinstance(periods,list) or len(periods)>12:raise ValueError('Limite de 12 períodos por integrante.')
        for p in periods:
            if not isinstance(p,dict) or not isinstance(p.get('id'),str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',p['id']) or p['id'] in period_ids:raise ValueError('Identificador de período inválido ou repetido.')
            period_ids.add(p['id'])
            try:
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',p.get('start','')) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',p.get('end','')):raise ValueError()
                a,b=date.fromisoformat(p['start']),date.fromisoformat(p['end'])
                if a>b or a.year<2000 or b.year>2100 or (b-a).days>365:raise ValueError()
                days=p.get('declaredDays')
                if days is not None and (type(days)!=int or not 1<=days<=366):raise ValueError()
            except (TypeError,ValueError):raise ValueError('Confira as datas do período de '+row['name']+'.') from None
    return data

def name_key(name):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFD',str(name or '').split('|')[0].casefold()) if not unicodedata.combining(c)).split())

def link_directory(employees,users):
    # Infer only a unique full-name match; never first/last names or email prefixes.
    active=[u for u in users if u.get('active',True)]
    names=Counter(name_key(u.get('name')) for u in active)
    rows=Counter(name_key(e.get('name')) for e in employees)
    claimed={e.get('email','').strip().lower() for e in employees if e.get('email','').strip()}
    by_name={name_key(u['name']):u['email'].strip().lower() for u in active if names[name_key(u['name'])]==1}
    for e in employees:
        e['email']=e.get('email','').strip().lower()
        if not e['email']:
            key=name_key(e['name']);candidate=by_name.get(key,'')
            if rows[key]==1 and candidate and candidate not in claimed:
                e['email']=candidate;claimed.add(candidate)
    return employees

def read(connect,identity=None):
    import users_directory
    with connect() as c:
        revision,raw,updated=c.execute('SELECT revision,data,updated FROM vacations_state WHERE id=1').fetchone()
        users=users_directory.list_users(c)
    data=json.loads(raw);link_directory(data['employees'],users)
    email=str((identity or {}).get('email','')).strip().lower()
    matched=[e for e in data['employees'] if email and e.get('email')==email]
    return {'revision':revision,'updatedAt':updated,**data,'currentEmployeeId':matched[0]['id'] if len(matched)==1 else None}

def write(connect,payload):
    if not isinstance(payload,dict) or type(payload.get('revision'))!=int:raise ValueError('Revisão inválida. Reabra o calendário.')
    data={k:payload.get(k) for k in ['planningYear','source','employees']};validate(data)
    # Keep the stored schema explicit; no client data is interpreted as SQL or HTML.
    clean={'planningYear':data['planningYear'],'source':data['source'],'employees':[]}
    for row in data['employees']:
        employee={'id':row['id'],**{k:row.get(k,'') for k in FIELDS},'periods':[{k:p.get(k) for k in ['id','start','end','declaredDays']} for p in row['periods']]}
        employee['email']=employee['email'].strip().lower()
        if type(row.get('sourceRow'))==int:employee['sourceRow']=row['sourceRow']
        clean['employees'].append(employee)
    with connect() as c:
        c.execute('LOCK TABLE vacations_state IN EXCLUSIVE MODE' if hasattr(c,'connection') else 'BEGIN IMMEDIATE')
        current=c.execute('SELECT revision FROM vacations_state WHERE id=1').fetchone()[0]
        if current!=payload['revision']:return 409,{'error':'Outro administrador atualizou as férias. Recarregue a base antes de salvar novamente.'}
        revision=current+1;updated=time.time();c.execute('UPDATE vacations_state SET revision=?,data=?,updated=? WHERE id=1',(revision,json.dumps(clean,ensure_ascii=False),updated))
    return 200,{'revision':revision,'updatedAt':updated}
