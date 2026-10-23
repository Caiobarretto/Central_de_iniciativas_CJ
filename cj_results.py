"""Dashboard CJ adicional: dados dos relatórios existentes e edição compartilhada."""
import base64,hashlib,hmac,json,math,re,time
from pathlib import Path
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from urllib.parse import parse_qs
ROOT=Path(__file__).resolve().parent
TITLES=['Produtividade CJ','Chamados GLPI','Ações','Horas de Treinamento']

def setup(connect):
    with connect() as c:c.execute('CREATE TABLE IF NOT EXISTS cj_dashboards (month TEXT PRIMARY KEY,data TEXT NOT NULL,revision INTEGER NOT NULL,source TEXT NOT NULL,updated DOUBLE PRECISION NOT NULL)')
def month_value(value):
    if not isinstance(value,str) or not re.fullmatch(r'20\d\d-(0[1-9]|1[0-2])',value):raise ValueError('Selecione um mês válido.')
    return value
def default_month():return (datetime.now(ZoneInfo('America/Sao_Paulo')).date().replace(day=1)-timedelta(days=1)).isoformat()[:7]
def number(value):
    text=str(value).strip()
    if not re.fullmatch(r'[+−-]?\d[\d. ]*(?:,\d+)?%?',text):return None
    text=text.replace('−','-').replace(' ','').replace('.','').replace(',','.').replace('%','')
    try:n=float(text);return n if math.isfinite(n) else None
    except ValueError:return None

def from_report(report):
    sections=[]
    for i,slide in enumerate((report.get('deck') or {}).get('slides',[])[:8]):
        section={'title':str(slide.get('title') or (TITLES[i] if i<4 else 'Indicadores')),'metrics':[],'charts':[],'notes':[]};scope='Geral';texts=slide.get('texts',[])
        for n,text in enumerate(texts):
            text=str(text).strip()
            if not text or text.startswith('Report Mensal'):continue
            if re.match(r'Acumulado\s+20\d\d',text,re.I):scope='Acumulado';continue
            if re.fullmatch(r'[A-Za-zÀ-ÿ]+\s+20\d\d',text):scope='Mensal';continue
            nxt=number(texts[n+1]) if n+1<len(texts) else None
            if number(text) is None and nxt is not None:
                raw=str(texts[n+1]);section['metrics'].append({'label':text,'value':nxt,'unit':'%' if '%' in raw else '', 'scope':scope})
            elif text.startswith('*'):section['notes'].append(text.lstrip('*').strip())
        chart_titles={0:['Volume por rotina · mês','Volume por rotina · acumulado'],1:['Prazo por tipo de chamado · mês','Prazo por tipo de chamado · acumulado'],2:['Distribuição de status','Ações por núcleo e status','Desempenho por núcleo','Ações por responsável']}.get(i,[])
        for j,chart in enumerate(slide.get('charts',[])[:12]):
            title=chart.get('title') or (chart_titles[j] if j<len(chart_titles) else 'Indicadores do relatório')
            graph={'title':str(title),'scope':('Mensal' if j==0 else 'Acumulado') if i<2 else 'Geral','series':[]}
            for series in chart.get('series',[])[:12]:
                values=series.get('values',[])[:150];cats=series.get('categories',[])[:150]
                pct='%' in str(series.get('format','')) or '%' in str(series.get('name','')) or (i==2 and j==2)
                graph['series'].append({'name':str(series.get('name') or 'Quantidade').strip(),'unit':'%' if pct else '', 'rows':[{'label':str(cat),'value':(None if k>=len(values) or values[k] is None else float(values[k])*(100 if pct else 1))} for k,cat in enumerate(cats)]})
            if graph['series']:section['charts'].append(graph)
        if i==2:
            # O material original contém fontes divergentes; não substituir silenciosamente.
            delayed=next((m['value'] for m in section['metrics'] if m['label'].lower()=='atrasado'),None)
            try:
                s=section['charts'][0]['series'][0];v=next(r['value'] for r in s['rows'] if r['label'].lower()=='atrasado')
                if delayed is not None and delayed!=v:section['notes'].append('Conferência do relatório: o resumo informa '+str(int(delayed))+' ações atrasadas, e o gráfico de distribuição informa '+str(int(v))+'. Os valores originais foram preservados para revisão pelo admin.')
            except (IndexError,StopIteration):pass
        # Valores legíveis na imagem do relatório-base de setembro, apenas quando a imagem é a mesma.
        if i==3:
            reference=json.loads((ROOT/'cj'/'training_reference.json').read_text())
            pics=slide.get('pictures',[])
            if any(hashlib.sha256(str(p.get('data','')).encode()).hexdigest()==reference['imageHash'] for p in pics):
                section['metrics']=reference['metrics'];section['charts']=reference['charts'];section['notes'].append(reference['note'])
            elif not section['metrics'] and slide.get('pictures'):section['notes'].append('Os dados de treinamento deste relatório estão em imagem. Cadastre os indicadores em Editar painel para apresentá-los como dashboard.')
        sections.append(section)
    if not sections:sections=[{'title':title,'metrics':[],'charts':[],'notes':[]} for title in TITLES]
    return {'sections':sections,'note':str(report.get('text','')),'headline':'Resultados que tornam nossa evolução visível.'}

def report_from_db(c,month):
    row=c.execute('SELECT data FROM state WHERE id=1').fetchone();all_reports=json.loads(row[0]).get('results',{}) if row else {};report=all_reports.get(month,{})
    return report,all_reports

def source_hash(report):
    # Só os dados necessários: nenhuma imagem é devolvida no dashboard.
    compact={**report};compact.pop('original',None);compact.pop('image',None)
    return hashlib.sha256(json.dumps(compact,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def read(connect,month,admin=False,csrf=''):
    with connect() as c:
        report,reports=report_from_db(c,month);row=c.execute('SELECT data,revision,source FROM cj_dashboards WHERE month=?',(month,)).fetchone();extra=c.execute('SELECT month FROM cj_dashboards WHERE data<>?',('',)).fetchall()
    fingerprint=source_hash(report);manual=bool(row and row[0]);doc=json.loads(row[0]) if manual else from_report(report)
    return {'month':month,'months':sorted(set(reports)|{r[0] for r in extra},reverse=True),'revision':row[1] if row else 0,'source':fingerprint,'manual':manual,'sourceChanged':bool(manual and row[2]!=fingerprint),'available':bool(report) or manual,'canAdmin':admin,'csrf':csrf if admin else '', 'data':doc,'hasOriginal':bool(report.get('original'))}

def validate(data):
    if not isinstance(data,dict) or not isinstance(data.get('sections'),list) or not 1<=len(data['sections'])<=8:raise ValueError('Use de uma a oito áreas de resultados.')
    def text(v,size=250):
        if not isinstance(v,str) or len(v)>size or any(ord(ch)<32 and ch not in '\n\t' for ch in v):raise ValueError('Texto inválido ou muito longo.')
        return v.strip()
    def value(v):
        if v is None:return None
        if type(v) not in (float,int) or not math.isfinite(v) or abs(v)>1e15:raise ValueError('Confira os valores numéricos.')
        return v
    out={'headline':text(data.get('headline',''),250),'note':text(data.get('note',''),30000),'sections':[]}
    for section in data['sections']:
        if not isinstance(section,dict):raise ValueError('Área inválida.')
        metrics=section.get('metrics',[]);charts=section.get('charts',[]);notes=section.get('notes',[])
        if not isinstance(metrics,list) or len(metrics)>60 or not isinstance(charts,list) or len(charts)>12 or not isinstance(notes,list) or len(notes)>20:raise ValueError('Confira a quantidade de indicadores e gráficos.')
        item={'title':text(section.get('title','')),'metrics':[],'charts':[],'notes':[text(n,4000) for n in notes]}
        for m in metrics:
            scope=text(m.get('scope','Geral'),20)
            if scope not in ('Geral','Mensal','Acumulado'):raise ValueError('Período inválido.')
            item['metrics'].append({'label':text(m.get('label','')),'value':value(m.get('value')),'unit':text(m.get('unit',''),20),'scope':scope})
        for g in charts:
            series=g.get('series',[])
            if not isinstance(series,list) or len(series)>12:raise ValueError('Gráfico inválido.')
            graph={'title':text(g.get('title','')),'scope':text(g.get('scope','Geral'),20),'series':[]}
            if graph['scope'] not in ('Geral','Mensal','Acumulado'):raise ValueError('Período inválido.')
            for series_item in series:
                rows=series_item.get('rows',[])
                if not isinstance(rows,list) or len(rows)>150:raise ValueError('Use até 150 categorias por série.')
                graph['series'].append({'name':text(series_item.get('name','')),'unit':text(series_item.get('unit',''),20),'rows':[{'label':text(r.get('label',''),400),'value':value(r.get('value'))} for r in rows]})
            item['charts'].append(graph)
        out['sections'].append(item)
    return out

def write(connect,month,payload):
    action=payload.get('action','save')
    if action not in ('save','reset'):raise ValueError('Ação inválida.')
    data=validate(payload.get('data')) if action=='save' else None
    with connect() as c:
        c.execute('LOCK TABLE cj_dashboards,state IN EXCLUSIVE MODE' if hasattr(c,'connection') else 'BEGIN IMMEDIATE')
        row=c.execute('SELECT revision FROM cj_dashboards WHERE month=?',(month,)).fetchone();revision=row[0] if row else 0
        report,_=report_from_db(c,month);fingerprint=source_hash(report)
        if payload.get('revision')!=revision or payload.get('source')!=fingerprint:return 409,{'error':'O relatório mudou. Recarregue o painel antes de salvar.'}
        c.execute('INSERT INTO cj_dashboards VALUES (?,?,?,?,?) ON CONFLICT (month) DO UPDATE SET data=excluded.data,revision=excluded.revision,source=excluded.source,updated=excluded.updated',(month,json.dumps(data,ensure_ascii=False) if data else '',revision+1,fingerprint,time.time()))
    return 200,{'ok':True}

def handle(env,start,server):
    def reply(code,data=None,body=None,mime='application/json; charset=utf-8',extra=()):
        raw=body if body is not None else json.dumps(data or {},ensure_ascii=False).encode();start(str(code)+' '+{200:'OK',302:'Found',400:'Bad Request',401:'Unauthorized',403:'Forbidden',404:'Not Found',405:'Method Not Allowed',409:'Conflict'}[code],[('Content-Type',mime),('Content-Length',str(len(raw))),('Cache-Control','no-store'),('X-Content-Type-Options','nosniff')]+list(extra));return [raw]
    path=env.get('PATH_INFO','');method=env.get('REQUEST_METHOD','GET');user=server.sso_auth.current(env,server.connect)
    if not user:return reply(302,extra=[('Location','/')]) if path=='/resultados-cj' else reply(401,{'error':'Entre na Central para visualizar os resultados.'})
    if path=='/resultados-cj':return reply(200,body=(ROOT/'cj'/'resultados.html').read_bytes(),mime='text/html; charset=utf-8') if method=='GET' else reply(405)
    try:
        active=server.session(env);admin=bool(active);month=month_value(parse_qs(env.get('QUERY_STRING','')).get('month',[default_month()])[0])
        if method=='GET' and path=='/api/cj/original':
            with server.connect() as c:report,_=report_from_db(c,month)
            original=report.get('original') or {};encoded=original.get('data','')
            if not isinstance(encoded,str) or ';base64,' not in encoded or len(encoded)>29_000_000:return reply(404,{'error':'PowerPoint original não disponível.'})
            raw=base64.b64decode(encoded.split(';base64,',1)[1],validate=True)
            if not raw.startswith(b'PK'):raise ValueError('Arquivo original inválido.')
            return reply(200,body=raw,mime='application/vnd.openxmlformats-officedocument.presentationml.presentation',extra=[('Content-Disposition','attachment; filename="Resultados_CJ_'+month+'.pptx"')])
        if method=='GET':return reply(200,read(server.connect,month,admin,active[1] if active else ''))
        if method!='POST' or path=='/api/cj/original':return reply(405)
        if not admin or env.get('HTTP_ORIGIN')!=server.PUBLIC_URL or not hmac.compare_digest(env.get('HTTP_X_CSRF_TOKEN',''),active[1]):return reply(403,{'error':'Entre como administrador para editar os resultados.'})
        size=int(env.get('CONTENT_LENGTH') or 0)
        if not 0<size<=1_000_000 or 'application/json' not in env.get('CONTENT_TYPE',''):raise ValueError('Dados inválidos.')
        payload=json.loads(env['wsgi.input'].read(size))
        if not isinstance(payload,dict):raise ValueError('Dados inválidos.')
        code,out=write(server.connect,month,payload);return reply(code,out)
    except (ValueError,TypeError,KeyError,AttributeError,UnicodeDecodeError) as e:return reply(400,{'error':str(e) or 'Confira os dados do painel.'})
