"""Carregamento e novidades da Central sem modificar o index original."""
import re,json
from pathlib import Path
HEAD='''<style>html.cj-catalog-loading main>:not(#centralLoading){display:none!important}#centralLoading{min-height:380px;display:grid;place-content:center;justify-items:center;text-align:center;padding:40px 24px;color:#64447e}html:not(.cj-catalog-loading) #centralLoading{display:none}#centralLoading h2{margin:22px 0 5px;font-size:23px}#centralLoading p{color:#9584a3;font-size:13px}.cj-load-orbit{width:72px;height:72px;border:3px solid #e8dff0;border-top-color:#8956aa;border-radius:50%;display:grid;place-items:center;animation:cjLoadSpin 1.5s linear infinite}.cj-load-orbit span{font-size:23px;animation:cjLoadCounter 1.5s linear infinite}#centralLoadRetry{margin-top:18px}@keyframes cjLoadSpin{to{transform:rotate(360deg)}}@keyframes cjLoadCounter{to{transform:rotate(-360deg)}}@media(prefers-reduced-motion:reduce){.cj-load-orbit,.cj-load-orbit span{animation:none}}</style><script>document.documentElement.classList.add('cj-catalog-loading');</script>'''
LOADER='''<section id="centralLoading" role="status" aria-live="polite"><div class="cj-load-orbit" aria-hidden="true"><span>✦</span></div><h2 id="centralLoadTitle">Preparando sua Central</h2><p id="centralLoadText">Carregando as iniciativas da equipe…</p><button id="centralLoadRetry" class="btn" hidden onclick="location.reload()">Tentar novamente</button></section>'''
def vacation_loading(html):
    loader=(Path(__file__).parent/'cj'/'loading.js').read_text()
    html=html.replace('</head>','<script>'+loader+'</script></head>',1)
    html=html.replace('function render(){',"function render(){return window.CJLoading?CJLoading.paint(document.querySelector('main'),()=>renderData()):renderData()}\nfunction renderData(){",1)
    html=html.replace("(async()=>{try{data=await refresh();remote=true;", "(async()=>{const busyUI=window.CJLoading?.begin(document.querySelector('main'),'Carregando férias da equipe…');try{data=await refresh();remote=true;",1)
    start=html.find("}catch(error){data={...JSON.parse($('vacationSeed').textContent)")
    if start>=0:
        end=html.find('}year=data.planningYear;',start)
        if end>=0:html=html[:start]+"}catch(error){canEdit=false;busyUI?.error(error);return"+html[end:]
    html=html.replace('month=0;filterOptions();render();timer=setInterval','month=0;filterOptions();render();busyUI?.end();timer=setInterval',1)
    html=html.replace('canEdit=!!window.CJ_VACATION_EDIT&&res.ok&&session.authenticated&&session.canAdmin','canEdit=!!data.canPropose',1)
    approved_save="async function requestSave(next){const previous=data;const res=await fetch('/api/vacations',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':session.csrf},body:JSON.stringify({...next,revision:data.revision})});const result=await res.json();if(!res.ok)throw Error(result.error||'Não foi possível solicitar a alteração.');try{data=await refresh()}catch{data=previous}render();return result}"
    html=re.sub(r'async function requestSave\(next\)\{[^\n]*\}',lambda m:approved_save,html,count=1)
    workflow=(Path(__file__).parent/'cj'/'vacation_workflow.js').read_text()
    html=html.replace('</body>','<script>'+workflow+'</script></body>',1)
    return html

def prepare(body):
    text=body.decode('utf-8')
    def patch_vacations(match):
        app=json.loads(match.group(2));return match.group(1)+json.dumps(vacation_loading(app),ensure_ascii=True).replace('<','\\u003c')+match.group(3)
    text=re.sub(r'(<script[^>]*id="vacationsSource"[^>]*>)(.*?)(</script>)',patch_vacations,text,count=1,flags=re.S)
    text=text.replace('</head>',HEAD+'</head>',1)
    text=re.sub(r'(<main\b[^>]*>)',lambda m:m[0]+LOADER,text,count=1)
    text=text.replace('remoteReady=true;render()',"remoteReady=true;render();window.dispatchEvent(new Event('cj-catalog-ready'))",1)
    # Keep the welcome function and its manual button, suppress only the initial invocation.
    text=text.replace('showWelcome()}',"window.dispatchEvent(new Event('cj-catalog-settled'))}",1)
    return text.encode()
