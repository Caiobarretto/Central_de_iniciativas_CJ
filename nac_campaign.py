"""Campanha GOL temporária; recorte por cliente/data, sem alterar equipes nem metas mensais."""
import json,re,time
from pathlib import Path
import users_directory
from nac_addon import norm,display,today,roster,month_value
ROOT=Path(__file__).parent/'nac'
EXCLUDED_PARTICIPANTS={'external:arruda','external:igor'}
EXTRAS={
 'layscampos@queirozcavalcanti.adv.br':('Lays Giselle',['Lays Giselle','Lays Campos','Lays Giselle Teixeira Campos']),
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
def metadata(connect=None):
 c=config();opened=True
 if connect:
  with connect() as db:
   row=db.execute('SELECT registration_open FROM nac_campaign_settings WHERE id=?',(c['id'],)).fetchone()
   if row:opened=bool(row[0])
 return {**c,'today':today(),'autoActive':False,'registrationOpen':opened,'ended':not opened,'dateLimited':False}

def set_registration(connect,identity,admin,data):
 if not admin:return 403,{'error':'Apenas o admin NAC pode abrir ou encerrar registros.'}
 if data.get('action')!='registration' or type(data.get('open')) is not bool:raise ValueError('Informe se os registros devem ficar abertos.')
 from nac_addon import lock
 with connect() as c:
  lock(c);revision=c.execute('SELECT revision FROM nac_meta WHERE id=1').fetchone()[0]
  if type(data.get('revision')) is not int or data['revision']!=revision:return 409,{'error':'O painel mudou. Atualize antes de alterar a abertura.'}
  c.execute('INSERT INTO nac_campaign_settings VALUES (?,?,?,?) ON CONFLICT (id) DO UPDATE SET registration_open=excluded.registration_open,actor=excluded.actor,updated=excluded.updated',(config()['id'],int(data['open']),identity['email'],time.time()))
  c.execute('UPDATE nac_meta SET revision=revision+1 WHERE id=1')
 return 200,{'ok':True,'registrationOpen':data['open'],'revision':revision+1}

def aliases():return {norm(name):email for email,(_,names) in EXTRAS.items() for name in names}
def alias_name(label,people):
 email=aliases().get(norm(label))
 return email if email in people else None

def participants(connect):
 import nac_people
 result={p['email']:p for p in roster(connect) if p['email'] not in EXCLUDED_PARTICIPANTS}
 with connect() as c:
  users={u['email']:u for u in users_directory.list_users(c) if u.get('active',True)}
  photos=nac_people.photos(c,list(EXTRAS))
 with connect() as c:
  saved_people=saved(c);urls=nac_people.photos(c,[r['email'] for r in saved_people if r['email'] in users and r['email'] not in result and r['email'] not in EXTRAS])
 for row in saved_people:
  email=row['email']
  if email in users and email not in EXCLUDED_PARTICIPANTS:
   result.setdefault(email,{'email':email,'name':display(users[email]['name']),'photoUrl':urls.get(email,''),'campaignGuest':True})
 for email,(label,_) in EXTRAS.items():
  if email in users:result[email]={'email':email,'name':label,'photoUrl':photos.get(email,''),'campaignGuest':True}
 return list(result.values())

def is_gol(client,extra=None):
 extra=extra or {}
 # Whole word avoids attributing unrelated "GOL..." names (e.g. GOLLOG) to GOL.
 values=[client]+[extra.get(k,'') for k in ('client','costCenter','cell')]
 return any(re.search(r'\bgol\b',norm(v)) for v in values)

def matches(row):return is_gol(row.get('client',''),row.get('extra'))
def saved(c):
 campaign=config()
 rows=c.execute('SELECT a.id,a.email,a.name,a.closed,a.reference,a.client,a.note,a.created,a.updated,a.active,d.data FROM nac_agreements a LEFT JOIN nac_details d ON d.agreement_id=a.id WHERE a.closed=? OR d.data LIKE ?',(campaign['date'],'%'+campaign['id']+'%')).fetchall()
 result=[]
 for r in rows:
  extra=json.loads(r[10]) if r[10] else {}
  if not is_gol(r[5],extra) or not (r[3]==campaign['date'] or extra.get('campaignId')==campaign['id']):continue
  result.append({'id':r[0],'email':r[1],'name':r[2],'date':r[3],'reference':r[4],'client':r[5],'note':r[6],'created':r[7],'updated':r[8],'active':r[9],'extra':extra})
 return result

def canonical(row,people):
 return row['email'] if row['email'] in people else alias_name(row['extra'].get('responsible',row['name']),people) or row['email']

def state(connect,identity,admin):
 c=metadata(connect);people={p['email']:p for p in participants(connect)}
 with connect() as con:
  revision=con.execute('SELECT revision FROM nac_meta WHERE id=1').fetchone()[0];rows=saved(con)
 totals={};today_counts={};latest=0
 for row in rows:
  key=canonical(row,people);row['email']=key
  if key not in people and key not in EXCLUDED_PARTICIPANTS:people[key]={'email':key,'name':display(row['name']),'historical':True,'external':True,'photoUrl':''}
  row['name']=people.get(key,{}).get('name',row['name'])
  if row['active']:
   totals[key]=totals.get(key,0)+1;latest=max(latest,row['created'])
   if row['date']==today():today_counts[key]=today_counts.get(key,0)+1
 ranking=sorted([{**p,'count':totals.get(key,0),'todayCount':today_counts.get(key,0)} for key,p in people.items()],key=lambda p:(-p['count'],norm(p['name'])))
 last=None;rank=0
 for i,p in enumerate(ranking):
  if p['count']!=last:rank=i+1;last=p['count']
  p['rank']=rank
 visible=sorted((r for r in rows if admin or r['active']),key=lambda r:(r['created'],r['id']),reverse=True)[:100]
 return {'campaign':c,'revision':revision,'month':c['date'][:7],'today':today(),'serverTime':time.time(),'dateBasis':'Campanha GOL · datas reais dos acordos','goal':c['goal'],'total':sum(totals.values()),'todayCount':sum(today_counts.values()),'ranking':ranking,'roster':list(people.values()),'records':[{k:v for k,v in r.items() if k!='extra'} for r in visible],'canAdmin':admin,'canImport':admin,'canRegister':c['registrationOpen'] and (admin or identity['email'] in {p['email'] for p in participants(connect)}),'user':{'email':identity['email'],'name':display(identity['name'])},'latest':latest}

def scope_import(plan,c):
 current=saved(c);tagged={(norm(r['reference']),r['date']) for r in current if r['extra'].get('campaignId')==config()['id']}
 accepted=[]
 for row in plan['valid']:
  manual=(norm(row['reference']),row['date']) in tagged and is_gol(row['client'],row.get('extra'))
  if matches(row) or manual:
   row.setdefault('extra',{})['campaignId']=config()['id']
   if row['email'] in EXTRAS:row['name']=EXTRAS[row['email']][0]
   accepted.append(row)
 excluded=len(plan['valid'])-len(accepted)
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
