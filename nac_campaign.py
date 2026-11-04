"""Campanha GOL temporária; recorte por cliente/data, sem alterar equipes nem metas mensais."""
import json,re,time
from pathlib import Path
import users_directory
from nac_addon import norm,display,today,roster,month_value
ROOT=Path(__file__).parent/'nac'
EXTRAS={
 'caiobarretto@queirozcavalcanti.adv.br':('Caio Barretto',['Caio Costa Barretto','Caio Barretto']),
 'daniellerodrigues@queirozcavalcanti.adv.br':('Danielle Rodrigues',['Danielle Rodrigues','Danielle da Silva Rodrigues']),
 'rayannerocha@queirozcavalcanti.adv.br':('Rayanne Rocha',['Rayanne Rocha','Rayanne Aurora Alves da Rocha Oliveira'])}

DEFAULT_CONFIG={'id': 'gol-20261106', 'title': 'Mutirão GOL', 'date': '2026-11-06', 'previewFrom': '2026-11-04', 'goal': 600, 'client': 'GOL', 'policyDate': '15/05/2025', 'timeZone': 'America/Sao_Paulo', 'notes': 'Meta exclusiva de acordos GOL com Data Preenchimento em 06/11/2026. Participantes extras temporários; cadastro e permissões da Central preservados.'}

def config():
 try:
  value=json.loads((ROOT/'gol_campaign.json').read_text())
  if isinstance(value,dict) and all(k in value for k in DEFAULT_CONFIG):return value
 except (OSError,ValueError):pass
 return dict(DEFAULT_CONFIG)
def metadata():
 c=config();day=today()
 return {**c,'today':day,'autoActive':c['previewFrom']<=day<=c['date'],'registrationOpen':day==c['date'],'ended':day>c['date']}

def aliases():return {norm(name):email for email,(_,names) in EXTRAS.items() for name in names}
def alias_name(label,people):
 email=aliases().get(norm(label))
 return email if email in people else None

def participants(connect):
 import nac_people
 result={p['email']:p for p in roster(connect)}
 with connect() as c:
  users={u['email']:u for u in users_directory.list_users(c) if u.get('active',True)}
  photos=nac_people.photos(c,list(EXTRAS))
 for email,(label,_) in EXTRAS.items():
  if email in users:result[email]={'email':email,'name':label,'photoUrl':photos.get(email,''),'campaignGuest':True}
 return list(result.values())

def is_gol(client,extra=None):
 extra=extra or {}
 # Whole word avoids attributing unrelated "GOL..." names (e.g. GOLLOG) to GOL.
 values=[client]+[extra.get(k,'') for k in ('client','costCenter','cell')]
 return any(re.search(r'\bgol\b',norm(v)) for v in values)

def matches(row):return row['date']==config()['date'] and is_gol(row.get('client',''),row.get('extra'))
def saved(c):
 rows=c.execute('SELECT a.id,a.email,a.name,a.closed,a.reference,a.client,a.note,a.created,a.updated,a.active,d.data FROM nac_agreements a LEFT JOIN nac_details d ON d.agreement_id=a.id WHERE a.closed=?',(config()['date'],)).fetchall()
 result=[]
 for r in rows:
  extra=json.loads(r[10]) if r[10] else {}
  if not is_gol(r[5],extra):continue
  result.append({'id':r[0],'email':r[1],'name':r[2],'date':r[3],'reference':r[4],'client':r[5],'note':r[6],'created':r[7],'updated':r[8],'active':r[9],'extra':extra})
 return result

def canonical(row,people):
 return row['email'] if row['email'] in people else alias_name(row['extra'].get('responsible',row['name']),people) or row['email']

def state(connect,identity,admin):
 c=metadata();people={p['email']:p for p in participants(connect)}
 with connect() as con:
  revision=con.execute('SELECT revision FROM nac_meta WHERE id=1').fetchone()[0];rows=saved(con)
 totals={};latest=0
 for row in rows:
  key=canonical(row,people);row['email']=key
  if key not in people:people[key]={'email':key,'name':display(row['name']),'historical':True,'external':True,'photoUrl':''}
  row['name']=people[key]['name']
  if row['active']:totals[key]=totals.get(key,0)+1;latest=max(latest,row['created'])
 ranking=sorted([{**p,'count':totals.get(key,0),'todayCount':totals.get(key,0) if c['registrationOpen'] else 0} for key,p in people.items()],key=lambda p:(-p['count'],norm(p['name'])))
 last=None;rank=0
 for i,p in enumerate(ranking):
  if p['count']!=last:rank=i+1;last=p['count']
  p['rank']=rank
 visible=sorted((r for r in rows if admin or r['active']),key=lambda r:(r['created'],r['id']),reverse=True)[:100]
 return {'campaign':c,'revision':revision,'month':c['date'][:7],'today':today(),'serverTime':time.time(),'dateBasis':'Data Preenchimento · somente GOL em '+c['date'],'goal':c['goal'],'total':sum(totals.values()),'todayCount':sum(totals.values()) if c['registrationOpen'] else 0,'ranking':ranking,'roster':list(people.values()),'records':[{k:v for k,v in r.items() if k!='extra'} for r in visible],'canAdmin':admin,'canImport':admin,'canRegister':c['registrationOpen'] and (admin or identity['email'] in {p['email'] for p in participants(connect)}),'user':{'email':identity['email'],'name':display(identity['name'])},'latest':latest}

def scope_import(plan,c):
 accepted=[r for r in plan['valid'] if matches(r)];
 for row in accepted:
  if row['email'] in EXTRAS:row['name']=EXTRAS[row['email']][0]
 excluded=len(plan['valid'])-len(accepted);current=saved(c)
 plan['valid']=accepted;plan['months']=sorted({r['date'][:7] for r in accepted});plan['campaign']=metadata();plan['mode']='replace_campaign'
 plan['replacementCount']=len(accepted);plan['currentCount']=sum(bool(r['active']) for r in current)
 plan['removedCount']=sum(bool(r['active']) and norm(r['reference']) not in {norm(x['reference']) for x in accepted} for r in current)
 plan['excludedCount']=excluded
 count=c.execute('SELECT COUNT(*) FROM nac_agreements WHERE active=1').fetchone()[0]
 plan['preservedCount']=count-plan['currentCount']
 return plan

def materials(name):
 allowed={'logo-gol.png':('image/png',False),'politica-travelbank.pptx':('application/vnd.openxmlformats-officedocument.presentationml.presentation',True),'minuta-travelbank.docx':('application/vnd.openxmlformats-officedocument.wordprocessingml.document',True),'politica-travelbank.pdf':('application/pdf',False),'minuta-travelbank.pdf':('application/pdf',False)}
 if name not in allowed:return None
 mime,download=allowed[name];path=ROOT/'gol'/name
 if not path.is_file():return None
 return path.read_bytes(),mime,[('Content-Disposition',('attachment' if download else 'inline')+'; filename="'+name+'"')]
