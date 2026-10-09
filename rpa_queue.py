"""Fila criptografada: a Central recebe documentos; só o executor autorizado os retira."""
import base64, hashlib, hmac, json, os, secrets, time, zipfile, io
from urllib.parse import parse_qs
from cryptography.fernet import Fernet

def setup(connect):
    with connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS rpa_jobs (id TEXT PRIMARY KEY, secret TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL, result TEXT NOT NULL, created DOUBLE PRECISION NOT NULL, updated DOUBLE PRECISION NOT NULL, request_key TEXT UNIQUE NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS rpa_worker (id INTEGER PRIMARY KEY, seen DOUBLE PRECISION NOT NULL)')
        if not c.execute('SELECT 1 FROM rpa_worker WHERE id=1').fetchone():c.execute('INSERT INTO rpa_worker VALUES (1,0)')

def handle(env,respond,connect,public_url):
    path=env.get('PATH_INFO','');method=env.get('REQUEST_METHOD','GET');now=time.time()
    token=os.environ.get('RPA_WORKER_TOKEN','');key=os.environ.get('RPA_QUEUE_KEY','')
    if len(token)<32 or not key:return respond('503 Service Unavailable',{'error':'O administrador ainda não configurou o robô remoto.'})
    cipher=Fernet(key.encode())
    def sweep(c):
        c.execute("UPDATE rpa_jobs SET status='uncertain',payload='',result=?,updated=? WHERE status='running' AND updated<?",(json.dumps({'error':'Execução perdeu conexão. Confira a Lexio antes de reenviar.'}),now,now-180))
        c.execute("UPDATE rpa_jobs SET status='expired',payload='',result=?,updated=? WHERE status='queued' AND created<?",(json.dumps({'error':'Prazo da fila expirou. Envie novamente após ligar o robô.'}),now,now-8*3600))
        c.execute('DELETE FROM rpa_jobs WHERE updated<?',(now-86400,))
    worker=path.startswith('/api/rpa/worker/')
    if worker:
        if not hmac.compare_digest(env.get('HTTP_AUTHORIZATION',''),'Bearer '+token):return respond('403 Forbidden',{'error':'Executor não autorizado.'})
    elif method=='POST':
        origin=env.get('HTTP_ORIGIN','');expected=public_url or env.get('wsgi.url_scheme','http')+'://'+env.get('HTTP_HOST','')
        if origin!=expected:return respond('403 Forbidden',{'error':'Origem inválida.'})
    data={}
    if method=='POST':
        try:
            length=int(env.get('CONTENT_LENGTH') or 0)
            if not 0<length<=16_000_000:return respond('413 Payload Too Large',{'error':'Documento deve ter até 10 MB.'})
            data=json.loads(env['wsgi.input'].read(length))
            if not isinstance(data,dict):raise ValueError()
        except (ValueError,UnicodeDecodeError):return respond('400 Bad Request',{'error':'Dados inválidos.'})
    if method=='GET' and path=='/api/rpa/health':
        with connect() as c:
            sweep(c);seen=c.execute('SELECT seen FROM rpa_worker WHERE id=1').fetchone()[0]
        online=now-seen<100
        return respond('200 OK',{'status':'ok' if online else 'offline','version':3,'online':online})
    if method=='POST' and path=='/api/rpa/submit':
        team=os.environ.get('RPA_TEAM_TOKEN','')
        if len(team)<32 or not hmac.compare_digest(env.get('HTTP_X_RPA_TEAM',''),team):return respond('403 Forbidden',{'error':'Abra a Central pelo link de uso da equipe fornecido pelo administrador.'})
        try:
            name=data['name'];meta=data['metadata'];request_key=data['requestKey'];secret=data['secret']
            if not isinstance(name,str) or not name.lower().endswith('.docx') or len(name)>240 or '/' in name or '\\' in name:raise ValueError()
            if not isinstance(secret,str) or len(secret)<32 or len(secret)>128 or not isinstance(request_key,str) or not 24<=len(request_key)<=128:raise ValueError()
            binary=base64.b64decode(data['document'],validate=True)
            if not 0<len(binary)<=10_000_000:raise ValueError()
            with zipfile.ZipFile(io.BytesIO(binary)) as z:
                if 'word/document.xml' not in z.namelist() or sum(i.file_size for i in z.infolist())>100_000_000:raise ValueError()
            if not isinstance(meta,dict) or meta.get('action') not in ('sign','upload_only'):raise ValueError()
            if any(not isinstance(meta.get(k),str) or not 0<len(meta[k])<=300 for k in ('folder','contract_type')):raise ValueError()
            signers=meta['signers']
            if not isinstance(signers,list) or not (1 if meta['action']=='sign' else 0)<=len(signers)<=6:raise ValueError()
            if any(not isinstance(s,dict) or not isinstance(s.get('name'),str) or not s['name'].strip() or len(s['name'])>300 or not isinstance(s.get('email'),str) or '@' not in s['email'] or len(s['email'])>300 or s.get('type') not in ('parte','advogado') for s in signers):raise ValueError()
            meta={k:meta.get(k,'') for k in ('folder','contract_type','glpi_id','signers','action','docType')}
            if not isinstance(meta['docType'],str) or len(meta['docType'])>100:raise ValueError()
            if not isinstance(meta['glpi_id'],str) or len(meta['glpi_id'])>300:raise ValueError()
        except (ValueError,KeyError,TypeError,zipfile.BadZipFile):return respond('400 Bad Request',{'error':'Revise documento Word, pasta, tipo e assinantes.'})
        digest=hashlib.sha256(secret.encode()).hexdigest()
        with connect() as c:
            c.execute('BEGIN IMMEDIATE');sweep(c)
            old=c.execute('SELECT id,secret FROM rpa_jobs WHERE request_key=?',(request_key,)).fetchone()
            if old:
                if not hmac.compare_digest(old[1],digest):return respond('409 Conflict',{'error':'Identificador já utilizado.'})
                return respond('200 OK',{'id':old[0]})
            seen=c.execute('SELECT seen FROM rpa_worker WHERE id=1').fetchone()[0]
            if now-seen>=100:return respond('503 Service Unavailable',{'error':'Robô offline. Peça ao responsável para iniciar o executor.'})
            if c.execute("SELECT COUNT(*) FROM rpa_jobs WHERE status IN ('queued','running')").fetchone()[0]>=20:return respond('429 Too Many Requests',{'error':'Fila cheia. Aguarde as execuções atuais.'})
            jid=secrets.token_urlsafe(24);encrypted=cipher.encrypt(json.dumps({'name':name,'metadata':meta,'document':data['document']}).encode()).decode()
            c.execute('INSERT INTO rpa_jobs VALUES (?,?,?,?,?,?,?,?)',(jid,digest,'queued',encrypted,'{}',now,now,request_key))
        return respond('200 OK',{'id':jid})
    if method=='GET' and path=='/api/rpa/job':
        query=parse_qs(env.get('QUERY_STRING',''));jid=query.get('id',[''])[0];secret=env.get('HTTP_X_JOB_SECRET','')
        with connect() as c:
            sweep(c);row=c.execute('SELECT secret,status,result FROM rpa_jobs WHERE id=?',(jid,)).fetchone()
        if not row or not hmac.compare_digest(row[0],hashlib.sha256(secret.encode()).hexdigest()):return respond('404 Not Found',{'error':'Trabalho não encontrado.'})
        return respond('200 OK',{'id':jid,'state':row[1],**json.loads(row[2])})
    if method=='POST' and path=='/api/rpa/worker/claim':
        with connect() as c:
            c.execute('BEGIN IMMEDIATE');sweep(c);c.execute('UPDATE rpa_worker SET seen=? WHERE id=1',(now,))
            if c.execute("SELECT 1 FROM rpa_jobs WHERE status='running'").fetchone():return respond('200 OK',{'job':None})
            row=c.execute("SELECT id,payload FROM rpa_jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if not row:return respond('200 OK',{'job':None})
            payload=json.loads(cipher.decrypt(row[1].encode()));c.execute("UPDATE rpa_jobs SET status='running',updated=?,payload='' WHERE id=?",(now,row[0]))
        return respond('200 OK',{'job':{'id':row[0],**payload}})
    if method=='POST' and path=='/api/rpa/worker/report':
        jid=data.get('id');state=data.get('state');result=data.get('result',{})
        if state not in ('running','done','uncertain') or not isinstance(result,dict):return respond('400 Bad Request',{'error':'Estado inválido.'})
        result={k:result[k] for k in ('message','error','link') if isinstance(result.get(k),str) and len(result[k])<2000}
        if result.get('link') and not result['link'].startswith('https://app.lexio.legal/'):result.pop('link')
        with connect() as c:
            c.execute('UPDATE rpa_worker SET seen=? WHERE id=1',(now,))
            c.execute("UPDATE rpa_jobs SET status=?,result=?,updated=?,payload='' WHERE id=? AND status='running'",(state,json.dumps(result,ensure_ascii=False),now,jid))
        return respond('200 OK',{'ok':True})
    return respond('404 Not Found',{'error':'Endereço não encontrado.'})
