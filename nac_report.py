"""Importa relatório de realizados e produz agregações apenas dos participantes do Painel NAC."""
import json,secrets,time,re
from decimal import Decimal,InvalidOperation,ROUND_HALF_UP
from datetime import datetime,date
from collections import Counter
from nac_addon import norm,roster,today,lock,display,historical_key,reporting_roster
EXTERNAL=[{'email':'external:arruda','name':'Arruda','external':True},{'email':'external:igor','name':'Igor Pereira','external':True}]

def setup(c):
    c.execute('CREATE TABLE IF NOT EXISTS nac_details (agreement_id TEXT PRIMARY KEY,data TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS nac_import_backups (id TEXT PRIMARY KEY,created DOUBLE PRECISION NOT NULL,actor TEXT NOT NULL,data TEXT NOT NULL)')
    c.execute('CREATE INDEX IF NOT EXISTS nac_month_active ON nac_agreements(closed,active)')
    c.execute('CREATE INDEX IF NOT EXISTS nac_by_reference ON nac_agreements(reference)')

def money(value):
    text=str(value or '').strip().replace('R$','').replace(' ','')
    if not text:return None
    if ',' in text:text=text.replace('.','').replace(',','.')
    try:
        result=Decimal(text)
        if not result.is_finite() or result<0 or result>Decimal('1000000000000'):raise ValueError('Valor acordado inválido.')
        return int((result*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    except InvalidOperation:raise ValueError('Valor acordado inválido.') from None

def day(value):
    value=str(value or '').strip()
    if not value:return ''
    for pattern in ('%Y-%m-%d','%d/%m/%Y','%d-%m-%Y','%Y-%m-%dT%H:%M:%S'):
        try:return datetime.strptime(value,pattern).date().isoformat()
        except ValueError:pass
    raise ValueError('Data inválida.')

def is_report(rows):return bool(rows) and 'responsavel pelo acordo' in {norm(v) for v in rows[0]}

def plan(connect,identity,admin,rows,c):
    from users_directory import list_users
    people={p['email']:p for p in roster(connect,include_inactive=True)};mapping={norm(p['name']):p['email'] for p in people.values()}
    with connect() as con:
        for u in list_users(con):
            people.setdefault(u['email'],{'email':u['email'],'name':display(u['name'])})
            mapping[norm(u['name'].split('|')[0])]=u['email']
    mapping.update({'arruda adv':'external:arruda','arruda':'external:arruda','igor':'external:igor','acordo - igor ribeiro pereira':'external:igor','igor ribeiro pereira':'external:igor','igor pereira':'external:igor'})
    for participant in reporting_roster(connect):
        people.setdefault(participant['email'],participant)
        mapping.setdefault(norm(participant['name']),participant['email'])
    header={norm(v):i for i,v in enumerate(rows[0])}
    valid=[];updates=[];errors=[];duplicates=[];ignored=[];seen={}
    specs={'stage':'Etapa da Realização do Acordo','cell':'Célula','costCenter':'Centro de Custo','client':'Cliente','uf':'UF','segment':'Segmento','project':'Projeto','product':'Produto','strategy':'Estratégia','pay':'Tem Obrigação Pagar','do':'Tem Obrigação Fazer','processId':'Id Processo','process':'Número Processo','pa':'Id PA','hearing':'Data Audiencia','agreementDate':'Data Acordo Realizado','filledDate':'Data Preenchimento','phase':'Fase','processStatus':'Status Processo'}
    for number,row in enumerate(rows[1:],2):
        def get(label):
            i=header.get(norm(label));return str(row[i]).strip() if i is not None and i<len(row) else ''
        if not any(row):continue
        raw_name=get('Responsável pelo Acordo');email=mapping.get(norm(raw_name))
        if not raw_name:
            errors.append({'row':number,'error':'Informe o nome do responsável pelo acordo.'});continue
        if email not in people:
            email=historical_key(raw_name);people[email]={'email':email,'name':display(raw_name)}
        try:
            identifier=get('Id PA') or get('Id Processo')
            if not identifier or len(identifier)>100:raise ValueError('Id PA/Id Processo ausente ou inválido.')
            extra={key:get(label)[:300] for key,label in specs.items()};closed=day(extra['filledDate'] or extra['agreementDate'])
            if not closed or closed>today() or closed<'2000-01-01':raise ValueError('Data de preenchimento ausente, inválida ou futura.')
            for field in ('filledDate','agreementDate','hearing'):
                if extra[field]:extra[field]=day(extra[field])
            extra.update(amountCents=money(get('Valor Acordado')),source='realizados',responsible=raw_name)
            client=extra['client'] or extra['costCenter'] or extra['cell'];serialized=json.dumps(extra,ensure_ascii=False,sort_keys=True)
            candidate={'row':number,'email':email,'name':people[email]['name'],'date':closed,'reference':identifier,'client':client[:120],'note':'','extra':extra};key=norm(identifier)
            if key in seen:
                if seen[key]!=serialized:raise ValueError('Mesmo identificador aparece com dados diferentes no arquivo.')
                duplicates.append({'row':number,'reference':identifier});continue
            seen[key]=serialized;valid.append(candidate)
        except ValueError as e:errors.append({'row':number,'error':str(e)})
    return {'format':'relatorio_realizados','dateBasis':'Data Preenchimento','valid':valid,'updates':updates,'errors':errors,'duplicates':duplicates,'ignored':ignored,'ignoredCount':len(ignored),'totalRows':len(rows)-1,'sourceSheet':'Geral' if 'data acordo realizado' in header else 'Resultado'}

def commit(c,identity,plan):
    # Caller holds the NAC lock; validation, backup and replacement share one transaction.
    if plan['errors']:return 400,{'error':'Corrija as linhas inválidas. A base anterior foi preservada.',**plan}
    if not plan['valid']:return 400,{'error':'A planilha não contém acordos válidos. A base anterior foi preservada.'}
    now=time.time();agreements=[];details=[]
    for r in plan['valid']:
        identifier=secrets.token_urlsafe(20)
        agreements.append((identifier,r['email'],r['name'],r['date'],r['reference'],r['client'],r['note'],identity['email'],now,now,1,'import-'+identifier))
        if 'extra' in r:details.append((identifier,json.dumps(r['extra'],ensure_ascii=False,sort_keys=True)))
    backup={'agreements':[list(r) for r in c.execute('SELECT * FROM nac_agreements').fetchall()],
            'details':[list(r) for r in c.execute('SELECT * FROM nac_details').fetchall()],
            'revision':plan['revision']}
    c.execute('INSERT INTO nac_import_backups VALUES (?,?,?,?)',(secrets.token_urlsafe(20),now,identity['email'],json.dumps(backup,ensure_ascii=False)))
    c.execute('DELETE FROM nac_details')
    c.execute('DELETE FROM nac_agreements')
    for start in range(0,len(agreements),50):
        batch=agreements[start:start+50]
        c.execute('INSERT INTO nac_agreements VALUES '+','.join(['('+','.join(['?']*12)+')']*len(batch)),tuple(v for row in batch for v in row))
    for start in range(0,len(details),100):
        batch=details[start:start+100]
        c.execute('INSERT INTO nac_details VALUES '+','.join(['(?,?)']*len(batch)),tuple(v for row in batch for v in row))
    c.execute('UPDATE nac_meta SET revision=revision+1 WHERE id=1')
    return 200,{'ok':True,'mode':'replace_all','imported':len(agreements),'total':len(agreements),'removed':plan['removedCount'],'skipped':len(plan['duplicates']),'revision':plan['revision']+1}

def dashboard(connect,month,participant='',client=''):
    from nac_addon import month_value
    month=month_value(month);allowed={p['email']:p['name'] for p in reporting_roster(connect,month)}
    with connect() as c:
        rows=c.execute('SELECT a.id,a.email,a.name,a.closed,a.reference,a.client,d.data FROM nac_agreements a LEFT JOIN nac_details d ON d.agreement_id=a.id WHERE a.active=1 AND a.closed LIKE ? ORDER BY a.closed DESC,a.id',(month+'-%',)).fetchall()
    records=[]
    for r in rows:
        if r[1] not in allowed:continue
        extra=json.loads(r[6]) if r[6] else {}
        records.append({'id':r[0],'email':r[1],'name':allowed[r[1]],'date':r[3],'reference':r[4],'client':r[5],**extra})
    clients=sorted({r['client'] for r in records if r.get('client')})
    records=[r for r in records if (not participant or r['email']==participant) and (not client or r['client']==client)]
    values=[r['amountCents'] for r in records if r.get('amountCents') is not None];total=sum(values)
    def group(field):
        counts={}
        for r in records:
            label=r.get(field) or 'Não informado';v=counts.setdefault(label,{'label':label,'count':0,'amountCents':0});v['count']+=1;v['amountCents']+=r.get('amountCents') or 0
        return sorted(counts.values(),key=lambda x:(-x['count'],x['label']))
    return {'month':month,'dateBasis':'Data Preenchimento','total':len(records),'amountCents':total,'amountCount':len(values),'averageCents':round(total/len(values)) if values else None,'withoutAmount':len(records)-len(values),'withPay':sum(norm(r.get('pay',''))=='sim' for r in records),'withDo':sum(norm(r.get('do',''))=='sim' for r in records),'stages':group('stage'),'clients':group('client'),'states':group('uf'),'cells':group('cell'),'costCenters':group('costCenter'),'segments':group('segment'),'projects':group('project'),'products':group('product'),'strategies':group('strategy'),'phases':group('phase'),'processStatuses':group('processStatus'),'daily':sorted(group('date'),key=lambda x:x['label']),'negotiators':group('name'),'clientOptions':clients,'records':records[:100],'reported':sum(r.get('source')=='realizados' for r in records)}
