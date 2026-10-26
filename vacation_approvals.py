"""Férias por equipe e alterações sujeitas à aprovação do líder atual."""
import json,time,hashlib,secrets,hmac,copy
import vacations,module_permissions as permissions
from people_hub import reply,payload
from team_access import directory,reports,leader_email,short

def setup(connect):
    with connect() as c:c.execute('CREATE TABLE IF NOT EXISTS cj_vacation_requests (id TEXT PRIMARY KEY,employee TEXT NOT NULL,email TEXT NOT NULL,before_data TEXT NOT NULL,after_data TEXT NOT NULL,requester TEXT NOT NULL,approver TEXT NOT NULL,status TEXT NOT NULL,version INTEGER NOT NULL,created DOUBLE PRECISION NOT NULL,reviewer TEXT NOT NULL,reviewed DOUBLE PRECISION NOT NULL,reason TEXT NOT NULL)')
def dumps(v):return json.dumps(v,ensure_ascii=False,sort_keys=True)
def loaded(c,users):
    revision,raw,updated=c.execute('SELECT revision,data,updated FROM vacations_state WHERE id=1').fetchone();data=json.loads(raw);vacations.link_directory(data['employees'],users);return revision,data,updated

def scope(connect,identity,users):
    return None if permissions.has(identity,connect,'ferias') else reports(identity,users)|{identity['email']}
def read(connect,identity,admin_session=None):
    users=directory(connect);emails=scope(connect,identity,users)
    with connect() as c:revision,data,updated=loaded(c,users)
    selected=[e for e in data['employees'] if emails is None or e.get('email') in emails]
    mine=[e for e in selected if e.get('email')==identity['email']]
    return {**data,'employees':selected,'revision':revision,'updatedAt':updated,'currentEmployeeId':mine[0]['id'] if len(mine)==1 else None,'canPropose':bool(admin_session) and permissions.has(identity,connect,'ferias'),'canApprove':bool(reports(identity,users)),'scope':'admin' if emails is None else 'leadership' if reports(identity,users) else 'individual'}
def requests(connect,identity):
    users=directory(connect);admin=permissions.has(identity,connect,'ferias');by_email={u['email']:u for u in users};out=[]
    with connect() as c:rows=c.execute("SELECT id,employee,email,before_data,after_data,requester,approver,status,version,created,reviewer,reviewed,reason FROM cj_vacation_requests ORDER BY CASE WHEN status='pending' THEN 0 ELSE 1 END,created DESC LIMIT 1000").fetchall()
    for r in rows:
        p=dict(zip(('id','employee','email','before','after','requester','approver','status','version','created','reviewer','reviewed','reason'),r));current=leader_email(by_email.get(p['email']),users)
        can_review=current==identity['email'] and p['status']=='pending'
        if not (admin or current==identity['email'] or p['email']==identity['email']):continue
        p['before']=json.loads(p['before']);p['after']=json.loads(p['after']);p['canReview']=can_review;p['canCancel']=p['status']=='pending' and (admin or p['requester']==identity['email']);p['currentApprover']=short(by_email.get(current,{}).get('name','Liderança não localizada'));p['name']=short((p['after'] or p['before'])['name']);out.append(p)
    return {'requests':out,'csrf':identity.get('csrf','')}
def propose(connect,identity,p):
    users=directory(connect);by_email={u['email']:u for u in users};vacations.validate(p)
    with connect() as c:
        c.execute('LOCK TABLE vacations_state,cj_vacation_requests IN EXCLUSIVE MODE' if hasattr(c,'connection') else 'BEGIN IMMEDIATE')
        revision,data,updated=loaded(c,users)
        if p.get('revision')!=revision:return 409,{'error':'As férias mudaram. Reabra o calendário antes de solicitar.'}
        if p.get('planningYear')!=data['planningYear'] or p.get('source','')!=data.get('source',''):raise ValueError('Esta tela altera os períodos. Preserve o ano de planejamento e a fonte.')
        old={e['id']:e for e in data['employees']};new={e['id']:e for e in p['employees']};changes=[]
        for key in old.keys()|new.keys():
            before=old.get(key);after=new.get(key)
            # Ignore field defaults added by the original calendar editor.
            def clean(e):
                if e is None:return None
                return {**{k:e.get(k,'') for k in vacations.FIELDS},'id':e['id'],'periods':e['periods'],**({'sourceRow':e['sourceRow']} if 'sourceRow' in e else {})}
            before=clean(before);after=clean(after)
            if before==after:continue
            employee=after or before;email=employee.get('email');profile=by_email.get(email);approver=leader_email(profile,users)
            if not profile or not approver or not by_email.get(approver,{}).get('active',True):raise ValueError('Cadastre o e-mail e a liderança válida de '+employee['name']+' em Usuários e e-mails.')
            if before and after and before.get('email') and before.get('email')!=after.get('email'):raise ValueError('Não altere o vínculo do integrante nesta solicitação.')
            if c.execute("SELECT id FROM cj_vacation_requests WHERE employee=? AND status='pending'",(key,)).fetchone():raise ValueError('Já há uma solicitação pendente para '+employee['name']+'. Revise ou cancele antes de enviar outra.')
            changes.append((key,email,before,after,approver))
        if len(changes)>50:raise ValueError('Envie até 50 alterações por vez.')
        for key,email,before,after,approver in changes:c.execute('INSERT INTO cj_vacation_requests VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',(secrets.token_urlsafe(18),key,email,dumps(before),dumps(after),identity['email'],approver,'pending',1,time.time(),'',0,''))
    return 200,{'ok':True,'revision':revision,'pendingCount':len(changes),'message':'Alterações enviadas à liderança. As datas atuais continuam válidas até a aprovação.'}
def decide(connect,identity,p):
    users=directory(connect);by_email={u['email']:u for u in users};action=p.get('action');reason=str(p.get('reason','')).strip()[:1000]
    if action not in ('approve','reject','cancel'):raise ValueError('Ação inválida.')
    if action=='reject' and not reason:raise ValueError('Informe o motivo da recusa.')
    with connect() as c:
        c.execute('LOCK TABLE vacations_state,cj_vacation_requests IN EXCLUSIVE MODE' if hasattr(c,'connection') else 'BEGIN IMMEDIATE')
        row=c.execute('SELECT employee,email,before_data,after_data,requester,status,version FROM cj_vacation_requests WHERE id=?',(p.get('id'),)).fetchone()
        if not row or row[5]!='pending' or p.get('version')!=row[6]:return 409,{'error':'A solicitação já foi analisada ou mudou.'}
        if action=='cancel':
            if identity['email']!=row[4] and not permissions.has(identity,connect,'ferias'):return 403,{'error':'Sem permissão para cancelar.'}
        elif leader_email(by_email.get(row[1]),users)!=identity['email']:return 403,{'error':'Somente a liderança atual deste integrante pode decidir.'}
        if action=='approve':
            revision,data,updated=loaded(c,users);before=json.loads(row[2]);after=json.loads(row[3]);current=next((e for e in data['employees'] if e['id']==row[0]),None)
            def clean(e):
                if e is None:return None
                return {**{k:e.get(k,'') for k in vacations.FIELDS},'id':e['id'],'periods':e['periods'],**({'sourceRow':e['sourceRow']} if 'sourceRow' in e else {})}
            if clean(current)!=before:return 409,{'error':'As datas desse integrante mudaram depois do pedido. Cancele e gere uma nova solicitação.'}
            data['employees']=[e for e in data['employees'] if e['id']!=row[0]]
            if after:data['employees'].append(after)
            vacations.validate(data)
            c.execute('UPDATE vacations_state SET revision=?,data=?,updated=? WHERE id=1',(revision+1,dumps(data),time.time()))
        c.execute('UPDATE cj_vacation_requests SET status=?,version=version+1,reviewer=?,reviewed=?,reason=? WHERE id=?',({'approve':'approved','reject':'rejected','cancel':'cancelled'}[action],identity['email'],time.time(),reason,p['id']))
    return 200,{'ok':True}
def handle(env,start,server):
    identity=server.sso_auth.current(env,server.connect)
    if not identity:return reply(start,401,{'error':'Entre na Central.'})
    method=env.get('REQUEST_METHOD','GET');path=env['PATH_INFO'];active=server.session(env)
    try:
        if method=='GET':return reply(start,200,requests(server.connect,identity) if path.endswith('/requests') else read(server.connect,identity,active))
        if method!='POST':return reply(start,405,{})
        if env.get('HTTP_ORIGIN')!=server.PUBLIC_URL:return reply(start,403,{})
        if path.endswith('/requests'):
            if not identity.get('csrf') or not hmac.compare_digest(env.get('HTTP_X_CSRF_TOKEN',''),identity['csrf']):return reply(start,403,{'error':'Atualize a sessão.'})
            code,out=decide(server.connect,identity,payload(env));return reply(start,code,out)
        if not permissions.has(identity,server.connect,'ferias') or not active or not hmac.compare_digest(env.get('HTTP_X_CSRF_TOKEN',''),active[1]):return reply(start,403,{'error':'Entre como admin de Férias para solicitar uma alteração.'})
        code,out=propose(server.connect,identity,payload(env,2000000));return reply(start,code,out)
    except (ValueError,KeyError,TypeError) as e:return reply(start,400,{'error':str(e) or 'Confira a solicitação.'})
