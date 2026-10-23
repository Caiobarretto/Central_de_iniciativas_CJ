"""Permissões administrativas por módulo, sem alterar o núcleo da Central."""
import json,io,hmac,time
import admin_access,users_directory
OWNER=admin_access.OWNER
MODULES={'central':'Central · iniciativas','nac':'NAC','rai':'RAI','produtividade_cj':'Produtividade CJ · Resultados CJ','usuarios':'Usuários e e-mails','ferias':'Férias'}

def register(key,label):
    if not isinstance(key,str) or not key.replace('_','').isalnum():raise ValueError('Identificador de módulo inválido.')
    MODULES[key]=label

def setup(connect):
    with connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS admin_module_permissions (email TEXT PRIMARY KEY,modules TEXT NOT NULL)')
        # Admins legados mantêm os direitos existentes; novos acessos exigem seleção explícita.
        for email, in c.execute('SELECT email FROM admin_access').fetchall():
            c.execute('INSERT INTO admin_module_permissions VALUES (?,?) ON CONFLICT (email) DO NOTHING',(email,json.dumps(list(MODULES))))

def modules(identity,connect):
    if not admin_access.allowed(identity,connect):return []
    email=identity['email'].lower()
    if email==OWNER:return list(MODULES)
    with connect() as c:row=c.execute('SELECT modules FROM admin_module_permissions WHERE email=?',(email,)).fetchone()
    return [k for k in json.loads(row[0]) if k in MODULES] if row else []

def has(identity,connect,module):return module in modules(identity,connect)

def route_module(path):
    if path in ('/api/nac/people','/api/nac/photo') or path.startswith('/api/admin/users'):return 'usuarios'
    if path.startswith('/api/nac/'):return 'nac'
    if path=='/api/cj/rai' or path.startswith('/api/cj/rai/'):return 'rai'
    if path.startswith('/api/cj/'):return 'produtividade_cj'
    if path=='/api/vacations':return 'ferias'
    return None

def install(server):
    setup(server.connect)
    old_session=server.session;old_read=admin_access.read
    def session(env):
        active=old_session(env)
        key=route_module(env.get('PATH_INFO',''))
        return active if active and (not key or has(server.sso_auth.current(env,server.connect),server.connect,key)) else None
    server.session=session
    def read(connect):
        data=old_read(connect);data['modules']=[{'key':k,'label':v} for k,v in MODULES.items()]
        for u in data['users']:u['permissions']=modules({'email':u['email']},connect)
        return data
    admin_access.read=read
    def mutate(connect,data):
        email=str(data.get('email','')).strip().lower();action=data.get('action');selected=data.get('permissions')
        if email==OWNER:raise ValueError('O administrador principal mantém todas as permissões.')
        if action not in ('add','update','remove') or not email:raise ValueError('Informe um usuário e uma ação válida.')
        if action!='remove' and (not isinstance(selected,list) or not selected or any(k not in MODULES for k in selected)):raise ValueError('Selecione pelo menos um módulo válido.')
        with connect() as c:
            c.execute('LOCK TABLE admin_access_meta IN EXCLUSIVE MODE' if hasattr(c,'connection') else 'BEGIN IMMEDIATE')
            version=c.execute('SELECT version FROM admin_access_meta WHERE id=1').fetchone()[0]
            if data.get('version')!=version:return 409,{'error':'As permissões mudaram. Reabra o painel.'}
            if action=='remove':
                c.execute('DELETE FROM admin_access WHERE email=?',(email,));c.execute('DELETE FROM admin_module_permissions WHERE email=?',(email,))
            else:
                if not users_directory.find(c,email):raise ValueError('Cadastre ou ative o integrante antes de autorizar.')
                c.execute('INSERT INTO admin_access VALUES (?) ON CONFLICT (email) DO NOTHING',(email,))
                c.execute('INSERT INTO admin_module_permissions VALUES (?,?) ON CONFLICT (email) DO UPDATE SET modules=excluded.modules',(email,json.dumps(sorted(set(selected)))))
            c.execute('DELETE FROM sessions WHERE token IN (SELECT token FROM admin_session_profiles WHERE email=?)',(email,))
            c.execute('DELETE FROM admin_session_profiles WHERE email=?',(email,))
            c.execute('UPDATE admin_access_meta SET version=? WHERE id=1',(version+1,))
        return 200,{'ok':True}
    admin_access.mutate=mutate
    return old_session

def reply(start,code,data):
    raw=json.dumps(data,ensure_ascii=False).encode();start(str(code)+' '+{200:'OK',400:'Bad Request',401:'Unauthorized',403:'Forbidden'}[code],[('Content-Type','application/json; charset=utf-8'),('Content-Length',str(len(raw))),('Cache-Control','no-store')]);return [raw]

def guard(env,start,server,original_session):
    path=env.get('PATH_INFO','');method=env.get('REQUEST_METHOD','GET')
    identity=server.sso_auth.current(env,server.connect)
    if path=='/api/admin/permissions/me':
        if not identity:return reply(start,401,{'error':'Entre na Central.'})
        return reply(start,200,{'permissions':modules(identity,server.connect),'owner':identity['email'].lower()==OWNER,'labels':MODULES})
    if path=='/api/admin/access':
        if not identity or identity['email'].lower()!=OWNER:return reply(start,403,{'error':'Somente o administrador principal pode delegar permissões.'})
    elif path.startswith('/api/admin/'):
        key=route_module(path)
        if not identity or (not has(identity,server.connect,key) if key else identity['email'].lower()!=OWNER):return reply(start,403,{'error':'Seu perfil não administra este módulo.'})
    # Catálogo e relatórios são enviados juntos pelo núcleo: autorizar somente a parte alterada.
    if path=='/api/data' and method=='POST':
        if not original_session(env):return reply(start,403,{'error':'Entre com a senha administrativa.'})
        try:
            size=int(env.get('CONTENT_LENGTH') or 0)
            if not 0<size<=45_000_000:raise ValueError()
            raw=env['wsgi.input'].read(size);env['wsgi.input']=io.BytesIO(raw);data=json.loads(raw)
            with server.connect() as c:previous=json.loads(c.execute('SELECT data FROM state WHERE id=1').fetchone()[0])
            for field,key in [('items','central'),('results','produtividade_cj')]:
                if data.get(field)!=previous.get(field) and not has(identity,server.connect,key):return reply(start,403,{'error':'Sem permissão para alterar '+MODULES[key]+'.'})
        except (ValueError,TypeError,KeyError,AttributeError):return reply(start,400,{'error':'Dados inválidos.'})
    return None
