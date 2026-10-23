"""Entrada adicional da Central: Painel NAC e otimizações, sem substituir os arquivos do núcleo."""
import gzip,time
from pathlib import Path
import nac_people
import cj_results
import rai_results
import server
import fast_db
import nac_addon
fast_db.install(server)
nac_addon.setup(server.connect)
cj_results.setup(server.connect)
rai_results.setup(server.connect)
NAV='''<style>#nacModuleTab{position:relative;isolation:isolate;padding:10px 18px;border-radius:12px;font-weight:700;background:linear-gradient(120deg,#311353,#532275)!important;color:#fff!important;border:1px solid #a471db!important;box-shadow:0 0 12px #753aab66,0 0 26px #8f5bc433;overflow:visible}#nacModuleTab:before{content:'';position:absolute;inset:-3px;border-radius:inherit;border:1px solid #d2aff588;pointer-events:none;animation:nacHalo 3s ease-in-out infinite}#nacModuleTab:after{content:'\\2726';color:#e9ceff;position:absolute;top:-8px;right:5px;text-shadow:0 0 10px #fff;animation:nacSpark 2s ease-in-out infinite}@keyframes nacHalo{50%{box-shadow:0 0 18px #ae6ff0aa;opacity:.45}}@keyframes nacSpark{50%{opacity:.35;transform:scale(.7) rotate(25deg)}}@media(prefers-reduced-motion:reduce){#nacModuleTab:before,#nacModuleTab:after{animation:none}}</style><script data-nac-addon="1">(()=>{const nav=document.querySelector('.central-module-tabs');if(!nav||document.getElementById('nacModuleTab'))return;const button=document.createElement('button');button.type='button';button.id='nacModuleTab';button.textContent='Painel NAC';button.setAttribute('aria-label','Painel NAC');button.onclick=()=>{location.href='/nac'};nav.append(button)})();</script>'''.encode()
ROUTES={'/nac','/nac/','/api/nac/state','/api/nac/agreements','/api/nac/goal','/api/nac/import','/api/nac/template','/api/nac/dashboard'}

def accepts_gzip(value):
    for item in value.lower().split(','):
        parts=[part.strip() for part in item.split(';')]
        if parts[0]!='gzip':continue
        try:quality=next((float(part.split('=',1)[1]) for part in parts[1:] if part.startswith('q=')),1.0)
        except (ValueError,IndexError):quality=0
        if quality>0:return True
    return False

CJ_ROUTES={'/resultados-cj','/api/cj/results','/api/cj/original'}

PEOPLE_ROUTES={'/api/nac/people','/api/nac/photo','/api/nac/celebration'}

def application(env,start_response):
    scope,token=fast_db.begin(server,env.get('REQUEST_METHOD','GET'));started=time.perf_counter();captured={}
    def capture(status,headers,exc_info=None):captured.update(status=status,headers=headers)
    try:
        path=env.get('PATH_INFO','');response=(rai_results.handle(env,capture,server) if path=='/api/cj/rai' else cj_results.handle(env,capture,server) if path in CJ_ROUTES else nac_people.handle(env,capture,server) if path in PEOPLE_ROUTES else nac_addon.application(env,capture,server) if path in ROUTES else server.application(env,capture))
        try:body=b''.join(response)
        finally:
            if hasattr(response,'close'):response.close()
        headers=captured['headers'];is_html=any(k.lower()=='content-type' and 'text/html' in v for k,v in headers)
        if path=='/central' and captured['status'].startswith('200 ') and is_html:body=body.replace(b'</body>',NAV+b'</body>',1)
        if path in ('/central','/nac','/nac/') and captured['status'].startswith('200 ') and is_html:
            assets=Path(__file__).parent/'nac'
            scripts=(('<script>'+ (assets/'people_admin.js').read_text()+'</script>') if path=='/central' else '')+'<script>'+(assets/'celebration.js').read_text()+'</script>'
            body=body.replace(b'</body>',scripts.encode()+b'</body>',1)
        if captured['status'].startswith('200 ') and is_html:
            assets=Path(__file__).parent/'cj'
            names=['central_results.js'] if path=='/central' else ['figures.js','more_charts.js','results.js','rai.js'] if path=='/resultados-cj' else ['figures.js','login_motion.js'] if path in ('/','/index.html') else []
            if names:body=body.replace(b'</body>',(''.join('<script>'+ (assets/name).read_text()+'</script>' for name in names)).encode()+b'</body>',1)
        if env.get('REQUEST_METHOD')=='POST' and path in ('/auth/profile/photo','/api/admin/users') and captured['status'].startswith('200 '):
            with server.connect() as c:nac_people.bump(c)
        if path=='/carregando' and captured['status'].startswith('200 ') and is_html:
            body=body.replace(b'(now-start)/100',b'(now-start)/8').replace(b'now-start>=10000',b'now-start>=800')
        # Compression is optional and negotiated. JSON containing profile/session data remains uncompressed.
        if is_html and len(body)>2048 and accepts_gzip(env.get('HTTP_ACCEPT_ENCODING','')) and captured['status'].startswith('200 '):
            body=gzip.compress(body,compresslevel=3);headers=[*headers,('Content-Encoding','gzip'),('Vary','Accept-Encoding')]
        headers=[(k,v) for k,v in headers if k.lower()!='content-length']+[('Content-Length',str(len(body))),('Server-Timing','app;dur='+str(round((time.perf_counter()-started)*1000,1)))]
        start_response(captured['status'],headers);return [body]
    finally:fast_db.end(scope,token)
