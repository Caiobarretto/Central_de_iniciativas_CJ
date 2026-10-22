"""Importa relatório de realizados e produz agregações apenas dos participantes do Painel NAC."""
import json,secrets,time,re
from decimal import Decimal,InvalidOperation,ROUND_HALF_UP
from datetime import datetime,date
from collections import Counter
from nac_addon import norm,roster,today,lock
EXTERNAL=[{'email':'external:arruda','name':'Arruda','external':True},{'email':'external:igor','name':'Igor Pereira','external':True}]

def setup(c):
    c.execute('CREATE TABLE IF NOT EXISTS nac_details (agreement_id TEXT PRIMARY KEY,data TEXT NOT NULL)')
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
    people={p['email']:p for p in roster(connect)};mapping={norm(p['name']):p['email'] for p in people.values()}
    with connect() as con:
        for u in list_users(con):
            if u['email'] in people:mapping[norm(u['name'].split('|')[0])]=u['email']
    mapping.update({'arruda adv':'external:arruda','arruda':'external:arruda','igor':'external:igor','acordo - igor ribeiro pereira':'external:igor','igor ribeiro pereira':'external:igor','igor pereira':'external:igor'})
    header={norm(v):i for i,v in enumerate(rows[0])}
    existing={norm(r[1]):r for r in c.execute('SELECT id,reference,email,closed,client,note,active FROM nac_agreements').fetchall() if r[1]}
    detail={r[0]:r[1] for r in c.execute('SELECT agreement_id,data FROM nac_details').fetchall()}
    valid=[];updates=[];errors=[];duplicates=[];ignored=[];seen={}
    specs={'stage':'Etapa da Realização do Acordo','cell':'Célula','costCenter':'Centro de Custo','client':'Cliente','uf':'UF','segment':'Segmento','project':'Projeto','product':'Produto','strategy':'Estratégia','pay':'Tem Obrigação Pagar','do':'Tem Obrigação Fazer','processId':'Id Processo','process':'Número Processo','pa':'Id PA','hearing':'Data Audiencia','agreementDate':'Data Acordo Realizado','filledDate':'Data Preenchimento','phase':'Fase','processStatus':'Status Processo'}
    for number,row in enumerate(rows[1:],2):
        def get(label):
            i=header.get(norm(label));return str(row[i]).strip() if i is not None and i<len(row) else ''
        if not any(row):continue
        raw_name=get('Responsável pelo Acordo');email=mapping.get(norm(raw_name))
        if email not in people or (not admin and email!=identity['email']):ignored.append({'row':number,'reason':'Fora dos participantes autorizados neste envio.'});continue
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
            seen[key]=serialized;old=existing.get(key)
            if old:
                if not old[6]:ignored.append({'row':number,'reason':'Registro cancelado no painel: não será reativado.'});continue
                if not admin and old[2]!=email:raise ValueError('Apenas o admin pode mudar a atribuição de um registro existente.')
                candidate['id']=old[0]
                if old[2:5]==(email,closed,client[:120]) and detail.get(old[0])==serialized:duplicates.append({'row':number,'reference':identifier})
                else:updates.append(candidate)
            else:valid.append(candidate)
        except ValueError as e:errors.append({'row':number,'error':str(e)})
    return {'format':'relatorio_realizados','dateBasis':'Data Preenchimento','valid':valid,'updates':updates,'errors':errors,'duplicates':duplicates,'ignored':ignored,'ignoredCount':len(ignored),'totalRows':len(rows)-1,'sourceSheet':'Geral' if 'data acordo realizado' in header else 'Resultado'}

def commit(c,identity,plan):
    if plan['errors']:return 400,{'error':'Corrija as linhas inválidas. Nenhuma alteração foi salva.',**plan}
    now=time.time();agreements=[];details=[]
    for r in plan['valid']+plan['updates']:
        identifier=r.get('id') or secrets.token_urlsafe(20);r['id']=identifier
        agreements.append((identifier,r['email'],r['name'],r['date'],r['reference'],r['client'],r['note'],identity['email'],now,now,1,'report-'+secrets.token_urlsafe(24)))
        details.append((identifier,json.dumps(r['extra'],ensure_ascii=False,sort_keys=True)))
    # Multi-row statements avoid a separate database round trip for every agreement.
    for start in range(0,len(agreements),50):
        batch=agreements[start:start+50]
        c.execute('INSERT INTO nac_agreements VALUES '+','.join(['('+','.join(['?']*12)+')']*len(batch))+' ON CONFLICT (id) DO UPDATE SET email=excluded.email,name=excluded.name,closed=excluded.closed,client=excluded.client,updated=excluded.updated',tuple(v for row in batch for v in row))
    for start in range(0,len(details),100):
        batch=details[start:start+100]
        c.execute('INSERT INTO nac_details VALUES '+','.join(['(?,?)']*len(batch))+' ON CONFLICT (agreement_id) DO UPDATE SET data=excluded.data',tuple(v for row in batch for v in row))
    if plan['valid'] or plan['updates']:c.execute('UPDATE nac_meta SET revision=revision+1 WHERE id=1')
    return 200,{'ok':True,'imported':len(plan['valid']),'updated':len(plan['updates']),'skipped':len(plan['duplicates']),'ignored':len(plan['ignored'])}

def dashboard(connect,month,participant='',client=''):
    from nac_addon import month_value
    month=month_value(month);allowed={p['email']:p['name'] for p in roster(connect)}
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
