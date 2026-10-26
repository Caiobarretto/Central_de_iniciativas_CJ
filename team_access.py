"""Vínculos atuais e únicos do diretório compartilhado."""
import unicodedata

def norm(s):return ' '.join(''.join(c for c in unicodedata.normalize('NFD',str(s or '').split('|')[0].upper()) if not unicodedata.combining(c)).split())
def short(s):
    w=str(s or '').split('|')[0].split();return ' '.join([w[0],w[-1]] if len(w)>1 else w).title()
def directory(connect):
    import users_directory
    with connect() as c:return users_directory.list_users(c)
def resolve(label,users):
    label=norm(label)
    if not label:return None
    exact={u['email'] for u in users if norm(u['name'])==label or u['email']==label.lower()}
    if exact:return next(iter(exact)) if len(exact)==1 else None
    tokens=label.split()
    if len(tokens)<2:return None
    hits=set()
    for u in users:
        stream=iter(norm(u['name']).split())
        if all(any(word==token for word in stream) for token in tokens):hits.add(u['email'])
    return next(iter(hits)) if len(hits)==1 else None

def leader_email(profile,users):return resolve(profile.get('leader',''),users) if profile else None

def reports(identity,users):
    email=identity['email'].lower()
    return {u['email'] for u in users if u.get('active',True) and u['email']!=email and leader_email(u,users)==email}

def correct_links(connect):
    import json,time
    with connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS cj_people_migrations (id TEXT PRIMARY KEY,applied DOUBLE PRECISION NOT NULL)')
        c.execute('LOCK TABLE directory_meta,cj_people_migrations IN EXCLUSIVE MODE' if hasattr(c,'connection') else 'BEGIN IMMEDIATE')
        key='leadership-dani-stela-20261026'
        if c.execute('SELECT id FROM cj_people_migrations WHERE id=?',(key,)).fetchone():return
        changed=False
        for uid,email,raw in c.execute('SELECT id,email,data FROM directory_users').fetchall():
            u=json.loads(raw)
            if email=='daniellerodrigues@queirozcavalcanti.adv.br':u['leader']='LAIS SOUZA GOMES DA SILVA';changed=True
            elif email=='stelasantos@queirozcavalcanti.adv.br':u.update(leader='RAYANNE AURORA ALVES DA ROCHA OLIVEIRA',unit='GESTÃO DE CORRESPONDENTE',subunit='PAUTA');changed=True
            else:continue
            c.execute('UPDATE directory_users SET data=? WHERE id=?',(json.dumps(u,ensure_ascii=False),uid))
        if changed:c.execute('UPDATE directory_meta SET version=version+1 WHERE id=1')
        c.execute('INSERT INTO cj_people_migrations VALUES (?,?)',(key,time.time()))
