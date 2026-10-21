"""Entrada adicional: preserva server.py/index.html e delega as rotas anteriores."""
import server
import nac_addon
nac_addon.setup(server.connect)
NAV=b'''<script data-nac-addon="1">(()=>{const nav=document.querySelector('.central-module-tabs');if(!nav||document.getElementById('nacModuleTab'))return;const button=document.createElement('button');button.type='button';button.id='nacModuleTab';button.textContent='Acordos NAC';button.onclick=()=>{location.href='/nac'};nav.append(button)})();</script>'''

def application(environ,start_response):
    path=environ.get('PATH_INFO','/')
    if path in ('/nac','/nac/','/api/nac/state','/api/nac/agreements','/api/nac/goal','/api/nac/import','/api/nac/template'):
        return nac_addon.application(environ,start_response,server)
    if path!='/central':return server.application(environ,start_response)
    # Adds navigation to the response only; no Central file is edited or replaced.
    captured={}
    def capture(status,headers,exc_info=None):captured.update(status=status,headers=headers)
    response=server.application(environ,capture)
    try:body=b''.join(response)
    finally:
        if hasattr(response,'close'):response.close()
    headers=captured['headers']
    if captured['status'].startswith('200 ') and any(k.lower()=='content-type' and 'text/html' in v for k,v in headers):
        body=body.replace(b'</body>',NAV+b'</body>',1)
        headers=[(k,v) for k,v in headers if k.lower()!='content-length']+[('Content-Length',str(len(body)))]
    start_response(captured['status'],headers)
    return [body]
