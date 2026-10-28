"""Painel NAC compartilhado; usa banco, identidade e sessão administrativa da Central."""
import hmac,json,re,secrets,time,unicodedata,logging
from datetime import datetime,date
from zoneinfo import ZoneInfo
from pathlib import Path
from urllib.parse import parse_qs
import users_directory
TZ=ZoneInfo('America/Sao_Paulo')
EXCLUDED={'layscampos@queirozcavalcanti.adv.br','leticiasantana@queirozcavalcanti.adv.br'}
ROOT=Path(__file__).resolve().parent

def norm(v):return ' '.join(''.join(c for c in unicodedata.normalize('NFD',str(v).casefold()) if not unicodedata.combining(c)).split())
def display(v):
    words=str(v).split('|')[0].strip().split()
    return ' '.join([words[0],words[-1]] if len(words)>1 else words).title()
def today():return datetime.now(TZ).date().isoformat()
def setup(connect):
    with connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS nac_meta (id INTEGER PRIMARY KEY,revision INTEGER NOT NULL)')
        c.execute('INSERT INTO nac_meta VALUES (1,1) ON CONFLICT (id) DO NOTHING')
        c.execute('CREATE TABLE IF NOT EXISTS nac_agreements (id TEXT PRIMARY KEY,email TEXT NOT NULL,name TEXT NOT NULL,closed TEXT NOT NULL,reference TEXT NOT NULL,client TEXT NOT NULL,note TEXT NOT NULL,created_by TEXT NOT NULL,created DOUBLE PRECISION NOT NULL,updated DOUBLE PRECISION NOT NULL,active INTEGER NOT NULL,request_key TEXT UNIQUE NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS nac_goals (month TEXT PRIMARY KEY,target INTEGER NOT NULL)')
        import nac_report
        nac_report.setup(c)
    import nac_people
    nac_people.setup(connect)
def lock(c):c.execute('LOCK TABLE nac_meta,nac_agreements,nac_goals,nac_details IN EXCLUSIVE MODE' if hasattr(c,'connection') else 'BEGIN IMMEDIATE')
def roster(connect,include_inactive=False):
    import nac_people
    with connect() as c:
        users=users_directory.list_users(c);externals=nac_people.external(c)
        people=[{'email':u['email'],'name':display(u['name'])} for u in users if (include_inactive or u.get('active',True)) and norm(u.get('subunit',''))=='nac' and u['email'].lower() not in EXCLUDED and not norm(u['name']).startswith(('lays giselle','leticia amelia'))]
        people += [{'email':u['key'],'name':display(u['name']),'external':True,'contactEmail':u['email']} for u in externals if include_inactive or u['active']]
        urls=nac_people.photos(c,[p['email'] for p in people])
    return [{**p,'photoUrl':urls.get(p['email'],'')} for p in people]
def historical_key(name):
    import hashlib
    return 'historical:'+hashlib.sha256(norm(name).encode()).hexdigest()[:32]

def reporting_roster(connect,month=None):
    # Saved production remains part of NAC after a directory move/deactivation/deletion.
    people={p['email']:p for p in roster(connect)}
    with connect() as c:
        rows=c.execute('SELECT email,name FROM nac_agreements WHERE active=1'+(' AND closed LIKE ?' if month else '')+' ORDER BY updated DESC',((month+'-%',) if month else ())).fetchall()
        for email,name in rows:
            if email not in people:people[email]={'email':email,'name':display(name),'historical':True,'external':True,'photoUrl':''}
    return list(people.values())

def month_value(value):
    if not isinstance(value,str) or not re.fullmatch(r'20\d\d-(0[1-9]|1[0-2])',value):raise ValueError('Selecione um mês válido.')
    return value

def state(connect,identity,admin,month):
    month=month_value(month);people=reporting_roster(connect,month);emails=[p['email'] for p in people];today_value=today();marks=','.join('?' for _ in emails) or 'NULL';where='closed LIKE ? AND email IN ('+marks+')';params=(month+'-%',*emails)
    with connect() as c:
        revision=c.execute('SELECT revision FROM nac_meta WHERE id=1').fetchone()[0];goal=c.execute('SELECT target FROM nac_goals WHERE month=?',(month,)).fetchone()
        totals=c.execute('SELECT email,COUNT(*),SUM(CASE WHEN closed=? THEN 1 ELSE 0 END),MAX(created) FROM nac_agreements WHERE '+where+' AND active=1 GROUP BY email',(today_value,*params)).fetchall()
        rows=c.execute('SELECT id,email,name,closed,reference,client,note,created,updated,active FROM nac_agreements WHERE '+where+('' if admin else ' AND active=1')+' ORDER BY closed DESC,created DESC,id DESC LIMIT 100',params).fetchall()
    records=[dict(zip(('id','email','name','date','reference','client','note','created','updated','active'),r)) for r in rows];counts={r[0]:r[1] for r in totals}
    names={p['email']:p['name'] for p in people}
    for record in records:record['name']=names.get(record['email'],record['name'])
    ranking=sorted([{**p,'count':counts.get(p['email'],0),'todayCount':next((r[2] or 0 for r in totals if r[0]==p['email']),0)} for p in people],key=lambda p:(-p['count'],norm(p['name'])))
    last=None;position=0
    for i,row in enumerate(ranking):
        if row['count']!=last:position=i+1;last=row['count']
        row['rank']=position
    return {'revision':revision,'month':month,'today':today_value,'serverTime':time.time(),'dateBasis':'Data Preenchimento','goal':goal[0] if goal else 0,'total':sum(r[1] for r in totals),'todayCount':sum(r[2] or 0 for r in totals),'ranking':ranking,'roster':people,'records':records,'canAdmin':admin,'canImport':admin,'canRegister':admin or identity['email'] in {p['email'] for p in roster(connect)},'user':{'email':identity['email'],'name':display(identity['name'])},'latest':max((r[3] for r in totals),default=0)}

def text_field(data,key,limit):
    value=data.get(key,'')
    if not isinstance(value,str) or len(value)>limit or any(ord(c)<32 and c not in '\n\t' for c in value):raise ValueError('Confira o campo '+key+'.')
    return value.strip()
def agreement(connect,identity,admin,data):
    action=data.get('action','create');email=str(data.get('email','')).strip().lower();people={p['email']:p for p in roster(connect)}
    if action not in ('create','edit','cancel'):raise ValueError('Ação inválida.')
    if action!='create' and not admin:return 403,{'error':'Apenas o admin pode corrigir ou cancelar registros.'}
    if action=='create' and not admin:email=identity['email']
    if action!='cancel':
        if email not in people:return 403,{'error':'Selecione uma negociadora ativa do NAC.'}
        closed=text_field(data,'date',10)
        try:parsed=date.fromisoformat(closed)
        except ValueError:raise ValueError('Informe uma data válida.') from None
        if not re.fullmatch(r'20\d\d-\d\d-\d\d',closed) or closed>today():raise ValueError('Use uma data de fechamento válida, até hoje.')
        reference=text_field(data,'reference',100);client=text_field(data,'client',120);note=text_field(data,'note',500)
    request_key=data.get('requestKey','')
    if action=='create' and (not isinstance(request_key,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{20,100}',request_key)):raise ValueError('Reabra o formulário para registrar.')
    with connect() as c:
        lock(c)
        revision=c.execute('SELECT revision FROM nac_meta WHERE id=1').fetchone()[0]
        if action=='create':
            old=c.execute('SELECT id,created_by FROM nac_agreements WHERE request_key=?',(request_key,)).fetchone()
            if old:
                if old[1]!=identity['email']:return 409,{'error':'Pedido já utilizado.'}
                return 200,{'ok':True,'id':old[0],'revision':revision,'repeated':True}
            identifier=secrets.token_urlsafe(20)
        else:
            identifier=text_field(data,'id',100)
            old=c.execute('SELECT active,updated FROM nac_agreements WHERE id=?',(identifier,)).fetchone()
            if not old:return 404,{'error':'Registro não encontrado.'}
            if not old[0]:return 409,{'error':'Este registro já foi cancelado.'}
            if data.get('expectedUpdated')!=old[1]:return 409,{'error':'O registro mudou. Atualize o painel antes de corrigir.'}
        if action!='cancel' and reference:
            duplicates=c.execute('SELECT id,reference FROM nac_agreements WHERE active=1').fetchall()
            if any(r[0]!=identifier and norm(r[1])==norm(reference) for r in duplicates):return 409,{'error':'Já existe um acordo ativo com esse identificador.'}
        now=time.time()
        if action=='create':c.execute('INSERT INTO nac_agreements VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(identifier,email,people[email]['name'],closed,reference,client,note,identity['email'],now,now,1,request_key))
        elif action=='edit':c.execute('UPDATE nac_agreements SET email=?,name=?,closed=?,reference=?,client=?,note=?,updated=? WHERE id=?',(email,people[email]['name'],closed,reference,client,note,now,identifier))
        else:c.execute('UPDATE nac_agreements SET active=0,updated=? WHERE id=?',(now,identifier))
        c.execute('UPDATE nac_meta SET revision=? WHERE id=1',(revision+1,))
    return 200,{'ok':True,'id':identifier,'revision':revision+1}

def application(env,start,server):
    def reply(code,data=None,body=None,mime='application/json; charset=utf-8',extra=None):
        raw=body if body is not None else json.dumps(data or {},ensure_ascii=False).encode()
        start(str(code)+' '+{200:'OK',302:'Found',400:'Bad Request',401:'Unauthorized',403:'Forbidden',404:'Not Found',405:'Method Not Allowed',409:'Conflict',500:'Internal Server Error'}[code],[('Content-Type',mime),('Content-Length',str(len(raw))),('Cache-Control','no-store'),('X-Content-Type-Options','nosniff'),('Referrer-Policy','same-origin')]+(extra or []));return [raw]
    path=env.get('PATH_INFO','');method=env.get('REQUEST_METHOD','GET')
    try:
        identity=server.sso_auth.current(env,server.connect)
        if not identity:
            if path in ('/nac','/nac/'):return reply(302,extra=[('Location','/')])
            return reply(401,{'error':'Entre na Central para acessar o painel NAC.'})
        admin_session=server.session(env);admin=bool(admin_session)
        if path in ('/nac','/nac/'):
            if method!='GET':return reply(405)
            return reply(200,body=(ROOT/'nac'/'painel.html').read_bytes(),mime='text/html; charset=utf-8')
        if path=='/api/nac/template':
            if method!='GET':return reply(405)
            return reply(200,body=(ROOT/'nac'/'Modelo_Importacao_Acordos.xlsx').read_bytes(),mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',extra=[('Content-Disposition','attachment; filename=Modelo_Importacao_Acordos.xlsx')])
        if path=='/api/nac/dashboard':
            if method!='GET':return reply(405)
            import nac_report
            q=parse_qs(env.get('QUERY_STRING',''))
            return reply(200,nac_report.dashboard(server.connect,q.get('month',[today()[:7]])[0],q.get('participant',[''])[0],q.get('client',[''])[0]))
        if path=='/api/nac/state':
            if method!='GET':return reply(405)
            month=parse_qs(env.get('QUERY_STRING','')).get('month',[today()[:7]])[0]
            q=parse_qs(env.get('QUERY_STRING',''))
            if q.get('since'):
                with server.connect() as c:revision=c.execute('SELECT revision FROM nac_meta WHERE id=1').fetchone()[0]
                if q['since']==[str(revision)]:return reply(200,{'unchanged':True,'revision':revision,'canAdmin':admin})
            out=state(server.connect,identity,admin,month);out['csrf']=identity.get('csrf','');out['adminCsrf']=admin_session[1] if admin_session else '';return reply(200,out)
        if method!='POST':return reply(405)
        supplied=env.get('HTTP_X_CSRF_TOKEN','')
        valid=bool(identity.get('csrf')) and hmac.compare_digest(supplied,identity['csrf'])
        if path=='/api/nac/goal':valid=bool(admin_session) and hmac.compare_digest(supplied,admin_session[1])
        if env.get('HTTP_ORIGIN')!=server.PUBLIC_URL or not valid:return reply(403,{'error':'Sessão inválida. Atualize o painel e tente novamente.'})
        size=int(env.get('CONTENT_LENGTH') or 0)
        if not 0<size<=(7_100_000 if path=='/api/nac/import' else 10000) or 'application/json' not in env.get('CONTENT_TYPE',''):raise ValueError('Dados inválidos.')
        data=json.loads(env['wsgi.input'].read(size))
        if not isinstance(data,dict):raise ValueError('Dados inválidos.')
        if path=='/api/nac/import':
            code,out=import_agreements(server.connect,identity,admin,data);return reply(code,out)
        if path=='/api/nac/agreements':
            code,out=agreement(server.connect,identity,admin,data);return reply(code,out)
        if not admin:return reply(403,{'error':'Entre na administração da Central para definir a meta.'})
        month=month_value(data.get('month'));target=data.get('target')
        if type(target)!=int or not 0<=target<=100000:raise ValueError('Informe uma meta entre 0 e 100.000.')
        with server.connect() as c:
            lock(c);revision=c.execute('SELECT revision FROM nac_meta WHERE id=1').fetchone()[0]
            if data.get('revision')!=revision:return reply(409,{'error':'O painel mudou. Atualize antes de salvar a meta.'})
            c.execute('INSERT INTO nac_goals VALUES (?,?) ON CONFLICT (month) DO UPDATE SET target=excluded.target',(month,target));c.execute('UPDATE nac_meta SET revision=? WHERE id=1',(revision+1,))
        return reply(200,{'ok':True})
    except (ValueError,UnicodeDecodeError) as e:return reply(400,{'error':str(e) or 'Confira os campos e o formato do arquivo.'})
    except Exception:
        logging.exception('Falha no módulo adicional NAC')
        return reply(500,{'error':'Não foi possível acessar o painel. Tente novamente em instantes.'})

def decode_file(data):
    import base64,binascii
    name=data.get('filename','');encoded=data.get('file','')
    if not isinstance(name,str) or not name.lower().endswith(('.xlsx','.csv')) or not isinstance(encoded,str):raise ValueError('Envie uma planilha .xlsx ou .csv.')
    if len(encoded)>7_000_000:raise ValueError('O arquivo deve ter até 5 MB.')
    try:raw=base64.b64decode(encoded,validate=True)
    except (ValueError,binascii.Error):raise ValueError('Arquivo inválido.') from None
    if not raw or len(raw)>5*1024*1024:raise ValueError('O arquivo deve ter até 5 MB.')
    return name,raw

def sheet_rows(name,raw,sheet_name=None):
    import csv,io,zipfile,posixpath
    from xml.etree import ElementTree as ET
    from datetime import timedelta
    if name.lower().endswith('.csv'):
        try:text=raw.decode('utf-8-sig')
        except UnicodeDecodeError:text=raw.decode('cp1252')
        if not text.strip():raise ValueError('A planilha está vazia.')
        delimiter=';' if text.splitlines()[0].count(';')>=text.splitlines()[0].count(',') else ','
        rows=[]
        for row in csv.reader(io.StringIO(text),delimiter=delimiter):
            rows.append(row)
            if len(rows)>2001:raise ValueError('Importe até 2.000 acordos por arquivo.')
        return rows
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            if len(z.infolist())>1000 or sum(i.file_size for i in z.infolist())>32*1024*1024:raise ValueError('Planilha muito grande após descompactação.')
            def xml(path,limit=16*1024*1024):
                if z.getinfo(path).file_size>limit:raise ValueError('Planilha muito grande.')
                source=z.read(path)
                if b'<!DOCTYPE' in source.upper() or b'<!ENTITY' in source.upper():raise ValueError('Estrutura XML não permitida.')
                return ET.fromstring(source)
            ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            wb=xml('xl/workbook.xml',1_000_000);props=wb.find('m:workbookPr',ns);epoch=date(1904,1,1) if props is not None and props.get('date1904') in ('1','true') else date(1899,12,30)
            sheet=next((x for x in wb.findall('m:sheets/m:sheet',ns) if norm(x.get('name',''))==norm(sheet_name)),None) if sheet_name else wb.find('m:sheets/m:sheet',ns)
            if sheet is None:raise ValueError('A primeira aba não foi encontrada.')
            rid=sheet.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
            rels=xml('xl/_rels/workbook.xml.rels',1_000_000);target=next((r.get('Target') for r in rels if r.get('Id')==rid and r.get('TargetMode')!='External'),None)
            if not target:raise ValueError('A primeira aba não foi encontrada.')
            path=posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'xl/'+target)
            if not path.startswith('xl/worksheets/'):raise ValueError('Formato da aba não suportado.')
            shared=[]
            if 'xl/sharedStrings.xml' in z.namelist():shared=[''.join(si.itertext()) for si in xml('xl/sharedStrings.xml',8*1024*1024)]
            root=xml(path);rows=[]
            for row in root.findall('m:sheetData/m:row',ns):
                values=[]
                for cell in row.findall('m:c',ns):
                    reference=cell.get('r','');letters=re.sub('[^A-Z]','',reference);col=0
                    for char in letters:col=col*26+ord(char)-64
                    if not 1<=col<=200:raise ValueError('Limite de 200 colunas por planilha.')
                    while len(values)<col:values.append('')
                    value=cell.find('m:v',ns);text=value.text or '' if value is not None else ''
                    kind=cell.get('t','')
                    if cell.find('m:f',ns) is not None:text='[FÓRMULA NÃO ACEITA]'
                    elif kind=='inlineStr':text=''.join(cell.find('m:is',ns).itertext()) if cell.find('m:is',ns) is not None else ''
                    elif kind=='s':text=shared[int(text)]
                    values[col-1]=text
                number=int(row.get('r',str(len(rows)+1)))
                if number>2001 and not any(values):continue
                if not 1<=number<=2001:raise ValueError('Importe até 2.000 acordos por arquivo.')
                while len(rows)<number-1:rows.append([])
                rows.append(values)
                if len(rows)>2001:raise ValueError('Importe até 2.000 acordos por arquivo.')
            # Date conversion is restricted to the mapped date column, not IDs.
            if rows:
                aliases={'data','data de fechamento','data fechamento','fechamento','data do acordo','data acordo','data preenchimento','data acordo realizado','data audiencia'}
                for col,value in enumerate(rows[0]):
                    if norm(value) in aliases:
                        for row in rows[1:]:
                            if col<len(row) and re.fullmatch(r'\d+(\.\d+)?',row[col]):
                                serial=float(row[col])
                                if 1<=serial<=73050:row[col]=(epoch+timedelta(days=int(serial))).isoformat()
            return rows
    except (zipfile.BadZipFile,KeyError,ET.ParseError,IndexError,TypeError) as e:raise ValueError('Não foi possível ler o Excel. Salve como .xlsx ou use CSV UTF-8.') from None

def import_plan(connect,identity,admin,rows,c):
    aliases={'date':{'data','data de fechamento','data fechamento','fechamento','data do acordo','data acordo'},'reference':{'id','id acordo','id do acordo','identificador','identificador interno','referencia','processo'},'email':{'email','e-mail','e-mail da negociadora','email negociadora'},'name':{'negociadora','nome','nome da negociadora'},'client':{'cliente','carteira','carteira / cliente','carteira/cliente'},'note':{'observacao','observacoes','nota'}}
    if not rows:raise ValueError('A planilha está vazia.')
    headers={norm(v):i for i,v in enumerate(rows[0])};columns={k:next((i for v,i in headers.items() if v in names),None) for k,names in aliases.items()}
    if columns['date'] is None or columns['reference'] is None:raise ValueError('Inclua as colunas Data e Identificador na primeira linha.')
    people={p['email']:p for p in roster(connect,include_inactive=True)};name_map={}
    with connect() as directory:
        users=users_directory.list_users(directory)
    for u in users:
        people.setdefault(u['email'],{'email':u['email'],'name':display(u['name'])})
        if u['email'] in people:
            for label in (u['name'].split('|')[0],display(u['name'])):name_map.setdefault(norm(label),set()).add(u['email'])
    for p in people.values():name_map.setdefault(norm(p['name']),set()).add(p['email'])
    name_map.update({'arruda adv':{'external:arruda'},'acordo - igor ribeiro pereira':{'external:igor'},'igor ribeiro pereira':{'external:igor'},'igor pereira':{'external:igor'},'arruda':{'external:arruda'}})
    seen={};valid=[];errors=[];duplicates=[]
    for number,row in enumerate(rows[1:],2):
        if not any(str(v).strip() for v in row):continue
        def get(key):
            index=columns[key];return str(row[index]).strip() if index is not None and index<len(row) else ''
        try:
            if any('[FÓRMULA NÃO ACEITA]' in str(v) for v in row):raise ValueError('A linha contém fórmula. Cole os resultados como valores antes de importar.')
            email=get('email').lower();label=get('name');candidates=name_map.get(norm(label),set()) if label else set()
            if email and label and (len(candidates)!=1 or email not in candidates):raise ValueError('Nome e e-mail não correspondem à mesma negociadora.')
            if not email and len(candidates)==1:email=next(iter(candidates))
            if not email and not label and not admin:email=identity['email']
            if email not in people:
                if not label:raise ValueError('Informe o nome do responsável para preservar sua autoria no histórico.')
                email=historical_key(label);people[email]={'email':email,'name':display(label)}
            value=get('date');parsed=None
            for pattern in ('%Y-%m-%d','%d/%m/%Y','%d-%m-%Y'):
                try:parsed=datetime.strptime(value,pattern).date();break
                except ValueError:pass
            if parsed is None or parsed.year<2000 or parsed.isoformat()>today():raise ValueError('Data inválida ou futura.')
            reference=get('reference');client=get('client');note=get('note')
            if not reference:raise ValueError('Informe um identificador único para o acordo.')
            fields={'reference':reference,'client':client,'note':note}
            for key,limit in (('reference',100),('client',120),('note',500)):text_field(fields,key,limit)
            key=norm(reference)
            candidate={'row':number,'email':email,'name':people[email]['name'],'date':parsed.isoformat(),**fields}
            signature={k:v for k,v in candidate.items() if k!='row'}
            if key in seen:
                if seen[key]!=signature:raise ValueError('Mesmo identificador aparece com dados diferentes no arquivo.')
                duplicates.append({'row':number,'reference':reference});continue
            seen[key]=signature;valid.append(candidate)
        except ValueError as e:errors.append({'row':number,'error':str(e)})
    if len(valid)+len(errors)+len(duplicates)>2000:raise ValueError('Importe até 2.000 acordos por arquivo.')
    return {'valid':valid,'errors':errors,'duplicates':duplicates,'totalRows':len(valid)+len(errors)+len(duplicates)}

def import_agreements(connect,identity,admin,data):
    if not admin:return 403,{'error':'Apenas o admin pode importar planilhas do NAC.'}
    import hashlib
    name,raw=decode_file(data)
    try:rows=sheet_rows(name,raw,sheet_name='Geral') if name.lower().endswith('.xlsx') else sheet_rows(name,raw)
    except ValueError as e:
        if 'primeira aba' not in str(e):raise
        rows=sheet_rows(name,raw)
    action=data.get('action','preview')
    if action not in ('preview','commit'):raise ValueError('Ação inválida.')
    with connect() as c:
        if action=='commit':lock(c)
        import nac_report
        plan=nac_report.plan(connect,identity,admin,rows,c) if nac_report.is_report(rows) else import_plan(connect,identity,admin,rows,c)
        revision=c.execute('SELECT revision FROM nac_meta WHERE id=1').fetchone()[0]
        current=c.execute('SELECT reference FROM nac_agreements WHERE active=1').fetchall()
        incoming={norm(r['reference']) for r in plan['valid']}
        plan.update(mode='replace_all',revision=revision,currentCount=len(current),replacementCount=len(plan['valid']),removedCount=sum(norm(r[0]) not in incoming for r in current))
        if action=='preview':return 200,plan
        if data.get('replaceAll') is not True or type(data.get('revision')) is not int or data['revision']!=revision:
            return 409,{'error':'Analise a planilha novamente e confirme a substituição de toda a base do NAC.'}
        return nac_report.commit(c,identity,plan)
