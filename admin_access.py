"""Permissões administrativas por perfil; a senha de admin continua obrigatória."""
import users_directory
OWNER='caiobarretto@queirozcavalcanti.adv.br'

def setup(connect):
    with connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS admin_access (email TEXT PRIMARY KEY)')
        c.execute('CREATE TABLE IF NOT EXISTS admin_session_profiles (token TEXT PRIMARY KEY,email TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS admin_access_meta (id INTEGER PRIMARY KEY,version INTEGER NOT NULL)')
        c.execute('INSERT INTO admin_access_meta VALUES (1,1) ON CONFLICT (id) DO NOTHING')

def allowed(identity,connect):
    if not identity:return False
    email=identity.get('email','').strip().lower()
    with connect() as c:
        return bool(users_directory.find(c,email)) and (email==OWNER or bool(c.execute('SELECT 1 FROM admin_access WHERE email=?',(email,)).fetchone()))

def read(connect):
    with connect() as c:
        emails=[OWNER]+[r[0] for r in c.execute('SELECT email FROM admin_access ORDER BY email').fetchall() if r[0]!=OWNER]
        users=[]
        for email in emails:
            profile=users_directory.find(c,email)
            users.append({'email':email,'name':profile['name'] if profile else '', 'active':bool(profile),'owner':email==OWNER})
        return {'users':users,'version':c.execute('SELECT version FROM admin_access_meta WHERE id=1').fetchone()[0]}

def mutate(connect,data):
    email=str(data.get('email','')).strip().lower()
    action=data.get('action')
    if action not in ['add','remove'] or not email or len(email)>150:raise ValueError('Informe um e-mail cadastrado e uma ação válida.')
    if email==OWNER:raise ValueError('A permissão do administrador principal é permanente.')
    with connect() as c:
        c.execute('LOCK TABLE admin_access_meta IN EXCLUSIVE MODE' if hasattr(c,'connection') else 'BEGIN IMMEDIATE')
        version=c.execute('SELECT version FROM admin_access_meta WHERE id=1').fetchone()[0]
        if data.get('version')!=version:return 409,{'error':'A lista foi alterada. Abra novamente antes de salvar.'}
        if action=='add':
            if not users_directory.find(c,email):raise ValueError('Cadastre ou ative este integrante em Usuários e e-mails primeiro.')
            c.execute('INSERT INTO admin_access VALUES (?) ON CONFLICT (email) DO NOTHING',(email,))
        else:
            c.execute('DELETE FROM admin_access WHERE email=?',(email,))
            c.execute('DELETE FROM sessions WHERE token IN (SELECT token FROM admin_session_profiles WHERE email=?)',(email,))
            c.execute('DELETE FROM admin_session_profiles WHERE email=?',(email,))
        c.execute('UPDATE admin_access_meta SET version=? WHERE id=1',(version+1,))
    return 200,{'ok':True}
