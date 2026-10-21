"""Identidade Microsoft: OIDC, sessão no servidor, sem Microsoft Graph."""
import base64, hashlib, hmac, json, os, re, secrets, time
from http.cookies import SimpleCookie
from urllib.parse import parse_qs
from cryptography.fernet import Fernet

DOMAIN = 'queirozcavalcanti.adv.br'

def enabled():
    return os.environ.get('SSO_ENABLED', 'false').lower() == 'true'

def settings():
    tenant = os.environ.get('MICROSOFT_TENANT_ID', '').strip()
    client = os.environ.get('MICROSOFT_CLIENT_ID', '').strip()
    secret = os.environ.get('MICROSOFT_CLIENT_SECRET', '')
    origin = os.environ.get('PUBLIC_URL', '').strip().rstrip('/')
    if not re.fullmatch(r'[0-9a-fA-F-]{36}', tenant) or not re.fullmatch(r'[0-9a-fA-F-]{36}', client) or not secret or not origin.startswith('https://'):
        raise ValueError('Configure a aplicação Microsoft no Render antes de ativar o SSO.')
    return tenant.lower(), client, secret, origin

def setup(connect):
    with connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS sso_flows (token TEXT PRIMARY KEY, payload TEXT NOT NULL, expires DOUBLE PRECISION NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS sso_sessions (token TEXT PRIMARY KEY, tenant TEXT NOT NULL, oid TEXT NOT NULL, name TEXT NOT NULL, email TEXT NOT NULL, csrf TEXT NOT NULL, expires DOUBLE PRECISION NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS sso_users (tenant TEXT NOT NULL, oid TEXT NOT NULL, name TEXT NOT NULL, email TEXT NOT NULL, last_login DOUBLE PRECISION NOT NULL, PRIMARY KEY(tenant,oid))')

def cookie(env, name):
    try:
        return SimpleCookie(env.get('HTTP_COOKIE', ''))[name].value
    except (KeyError, ValueError):
        return ''

def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()

def current(env, connect):
    token = cookie(env, 'cj_identity')
    if not token: return None
    with connect() as c:
        row = c.execute('SELECT tenant,oid,name,email,csrf,expires FROM sso_sessions WHERE token=?', (digest(token),)).fetchone()
    return dict(zip(('tenant','oid','name','email','csrf','expires'), row)) if row and row[-1] > time.time() else None

def identity(claims, tenant):
    # Tenant e identificador imutável são a base da identidade; domínio é uma restrição adicional.
    if claims.get('tid', '').lower() != tenant or not re.fullmatch(r'[0-9a-fA-F-]{36}', claims.get('oid', '')) or claims.get('idp') == 'live.com':
        raise ValueError('Conta fora da organização QCA.')
    email = str(claims.get('email') or claims.get('preferred_username') or '').strip().lower()
    if email.count('@') != 1 or not email.split('@')[0] or email.split('@')[1] != DOMAIN:
        raise ValueError('Utilize sua conta @queirozcavalcanti.adv.br.')
    return {'tenant': tenant, 'oid': claims['oid'], 'name': str(claims.get('name') or email)[:300], 'email': email[:320]}

def app():
    import msal
    tenant, client, secret, origin = settings()
    return msal.ConfidentialClientApplication(client, authority='https://login.microsoftonline.com/'+tenant, client_credential=secret, exclude_scopes=['offline_access'])

def cipher():
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(settings()[2].encode()).digest()))

def set_cookie(name, value, age, same='Lax'):
    return ('Set-Cookie', f'{name}={value}; Path=/; Max-Age={age}; HttpOnly; Secure; SameSite={same}')

def clear_admin(env, connect):
    token = cookie(env, 'cj_session')
    if token:
        with connect() as c: c.execute('DELETE FROM sessions WHERE token=?', (digest(token),))

def handle(env, respond, connect):
    path, method = env.get('PATH_INFO'), env.get('REQUEST_METHOD')
    if path == '/api/me' and method == 'GET':
        user = current(env, connect) if enabled() else None
        return respond('200 OK', {'enabled': enabled(), 'mode':'microsoft', 'user': {k:user[k] for k in ('name','email','csrf')} if user else None})
    if not enabled(): return respond('404 Not Found', {'error':'SSO ainda não ativado.'})
    if path == '/auth/login' and method == 'GET':
        try:
            flow = app().initiate_auth_code_flow(scopes=['email'], redirect_uri=settings()[3]+'/auth/callback', response_mode='query', prompt='select_account')
        except Exception:
            return respond('503 Service Unavailable', {'error':'O login Microsoft ainda precisa ser configurado pelo administrador.'})
        binding = secrets.token_urlsafe(40)
        with connect() as c:
            c.execute('DELETE FROM sso_flows WHERE expires<?', (time.time(),))
            c.execute('INSERT INTO sso_flows VALUES (?,?,?)', (digest(binding), cipher().encrypt(json.dumps(flow).encode()).decode(), time.time()+600))
        return respond('302 Found', extra=[('Location', flow['auth_uri']), set_cookie('cj_oidc', binding, 600)])
    if path == '/auth/callback' and method == 'GET':
        binding = cookie(env, 'cj_oidc')
        with connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT payload,expires FROM sso_flows WHERE token=?', (digest(binding),)).fetchone() if binding else None
            if row: c.execute('DELETE FROM sso_flows WHERE token=?', (digest(binding),))
        try:
            if not row or row[1] < time.time(): raise ValueError('Login expirado.')
            flow = json.loads(cipher().decrypt(row[0].encode()))
            query = parse_qs(env.get('QUERY_STRING',''))
            if any(len(v)!=1 for v in query.values()): raise ValueError('Retorno inválido.')
            result = app().acquire_token_by_auth_code_flow(flow, {k:v[0] for k,v in query.items()})
            if not result.get('id_token'): raise ValueError('Login recusado.')
            # Verificação criptográfica explícita além de state, nonce e PKCE tratados pelo MSAL.
            import jwt
            tenant, client, _, _ = settings()
            keys = jwt.PyJWKClient('https://login.microsoftonline.com/'+tenant+'/discovery/v2.0/keys')
            key = keys.get_signing_key_from_jwt(result['id_token']).key
            claims = jwt.decode(result['id_token'], key, algorithms=['RS256'], audience=client, issuer='https://login.microsoftonline.com/'+tenant+'/v2.0', options={'require':['exp','iat','iss','aud','tid','oid','nonce']}, leeway=30)
            user = identity(claims, tenant)
        except Exception:
            return respond('302 Found', extra=[('Location','/?login_error=1'), set_cookie('cj_oidc','',0)])
        token, csrf, now = secrets.token_urlsafe(40), secrets.token_urlsafe(32), time.time()
        clear_admin(env, connect)
        with connect() as c:
            c.execute('DELETE FROM sso_sessions WHERE expires<?', (now,))
            c.execute('DELETE FROM sso_sessions WHERE token=?', (digest(cookie(env,'cj_identity')),))
            c.execute('INSERT INTO sso_sessions VALUES (?,?,?,?,?,?,?)', (digest(token), user['tenant'],user['oid'],user['name'],user['email'],csrf,now+8*3600))
            c.execute('INSERT INTO sso_users (tenant,oid,name,email,last_login) VALUES (?,?,?,?,?) ON CONFLICT (tenant,oid) DO UPDATE SET name=excluded.name,email=excluded.email,last_login=excluded.last_login', (user['tenant'],user['oid'],user['name'],user['email'],now))
        return respond('302 Found', extra=[('Location','/carregando'),set_cookie('cj_identity',token,28800),set_cookie('cj_oidc','',0),set_cookie('cj_session','',0)])
    if path == '/auth/logout' and method == 'POST':
        user = current(env, connect)
        if env.get('HTTP_ORIGIN','') != settings()[3] or not user or not hmac.compare_digest(env.get('HTTP_X_CSRF_TOKEN',''), user['csrf']):
            return respond('403 Forbidden', {'error':'Sessão inválida.'})
        with connect() as c: c.execute('DELETE FROM sso_sessions WHERE token=?', (digest(cookie(env,'cj_identity')),))
        clear_admin(env, connect)
        # Encerra somente a sessão da Central, mantendo os outros aplicativos Microsoft.
        return respond('200 OK', {'ok':True}, [set_cookie('cj_identity','',0),set_cookie('cj_session','',0),set_cookie('cj_oidc','',0)])
    return respond('404 Not Found', {'error':'Endereço não encontrado.'})
