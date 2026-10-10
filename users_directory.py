"""Cadastro compartilhado; somente nome/e-mail são expostos antes do login."""
import json,re,secrets
from pathlib import Path
FIELDS=('name','email','costCenter','unit','subunit','leader','role','company')

def validate(user):
    if not isinstance(user,dict):raise ValueError('Cadastro inválido.')
    out={k:user.get(k,'').strip() if isinstance(user.get(k,''),str) else '' for k in FIELDS}
    if any(len(v)>150 or any(ord(c)<32 for c in v) for v in out.values()):raise ValueError('Use campos com até 150 caracteres.')
    out['email']=out['email'].lower()
    if len(out['name'])<2 or not re.fullmatch(r'[a-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@queirozcavalcanti\.adv\.br',out['email']):raise ValueError('Informe nome e e-mail @queirozcavalcanti.adv.br.')
    if not isinstance(user.get('active',True),bool):raise ValueError('Situação inválida.')
    out['active']=user.get('active',True)
    return out

def setup(connect):
    with connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS directory_meta (id INTEGER PRIMARY KEY,version INTEGER NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS directory_users (id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL,data TEXT NOT NULL)')
        # Marcador impede que exclusões do admin sejam desfeitas em um novo deploy.
        c.execute('LOCK TABLE directory_meta IN EXCLUSIVE MODE' if hasattr(c,'connection') else 'BEGIN IMMEDIATE')
        c.execute('INSERT INTO directory_meta VALUES (1,0) ON CONFLICT (id) DO NOTHING')
        if c.execute('SELECT version FROM directory_meta WHERE id=1').fetchone()[0]==0:
            source=Path(__file__).with_name('users_seed.json')
            for u in json.loads(source.read_text(encoding='utf-8')) if source.exists() else []:
                u=validate(u);uid=secrets.token_urlsafe(16)
                c.execute('INSERT INTO directory_users VALUES (?,?,?)',(uid,u['email'],json.dumps(u,ensure_ascii=False)))
            c.execute('UPDATE directory_meta SET version=1 WHERE id=1')

def find(c,email):
    row=c.execute('SELECT id,data FROM directory_users WHERE email=?',(email,)).fetchone()
    if not row:return None
    u=json.loads(row[1]);u['id']=row[0]
    return u if u['active'] else None

def list_users(c,public=False):
    users=[]
    for uid,raw in c.execute('SELECT id,data FROM directory_users').fetchall():
        u=json.loads(raw);u['id']=uid
        if public:
            if not u['active']:continue
            u={k:u[k] for k in ('id','name','email')}
        users.append(u)
    return sorted(users,key=lambda u:u['name'].casefold())

def public(connect):
    with connect() as c:return list_users(c,True)

def read(connect):
    with connect() as c:return {'version':c.execute('SELECT version FROM directory_meta WHERE id=1').fetchone()[0],'users':list_users(c)}

def mutate(connect,data):
    if data.get('action') not in ('save','delete'):raise ValueError('Ação inválida.')
    uid=data.get('id','')
    if not isinstance(uid,str) or len(uid)>100:raise ValueError('Identificador inválido.')
    u=validate(data.get('user')) if data['action']=='save' else None
    with connect() as c:
        c.execute('LOCK TABLE directory_meta IN EXCLUSIVE MODE' if hasattr(c,'connection') else 'BEGIN IMMEDIATE')
        version=c.execute('SELECT version FROM directory_meta WHERE id=1').fetchone()[0]
        if data.get('version')!=version:return 409,{'error':'O cadastro mudou. Reabra Usuários e e-mails antes de salvar.'}
        old=c.execute('SELECT email FROM directory_users WHERE id=?',(uid,)).fetchone() if uid else None
        if uid and not old:return 404,{'error':'Usuário não encontrado.'}
        if data['action']=='save':
            duplicate=c.execute('SELECT id FROM directory_users WHERE email=?',(u['email'],)).fetchone()
            if duplicate and duplicate[0]!=uid:return 409,{'error':'Este e-mail já está cadastrado.'}
            if not uid:uid=secrets.token_urlsafe(16)
            c.execute('INSERT INTO directory_users VALUES (?,?,?) ON CONFLICT (id) DO UPDATE SET email=excluded.email,data=excluded.data',(uid,u['email'],json.dumps(u,ensure_ascii=False)))
            c.execute('UPDATE email_sessions SET name=? WHERE email=?',(u['name'],u['email']))
        elif not uid:raise ValueError('Selecione um usuário para excluir.')
        else:c.execute('DELETE FROM directory_users WHERE id=?',(uid,))
        if old and (not u or not u['active'] or old[0]!=u['email']):
            c.execute('DELETE FROM email_sessions WHERE email=?',(old[0],));c.execute('DELETE FROM email_challenges WHERE email=?',(old[0],))
        c.execute('UPDATE directory_meta SET version=? WHERE id=1',(version+1,))
    return 200,{'ok':True,'version':version+1,'id':uid}
