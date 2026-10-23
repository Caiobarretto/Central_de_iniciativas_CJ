"""Carregamento e novidades da Central sem modificar o index original."""
import re
HEAD='''<style>html.cj-catalog-loading main>:not(#centralLoading){display:none!important}#centralLoading{min-height:380px;display:grid;place-content:center;justify-items:center;text-align:center;padding:40px 24px;color:#64447e}html:not(.cj-catalog-loading) #centralLoading{display:none}#centralLoading h2{margin:22px 0 5px;font-size:23px}#centralLoading p{color:#9584a3;font-size:13px}.cj-load-orbit{width:72px;height:72px;border:3px solid #e8dff0;border-top-color:#8956aa;border-radius:50%;display:grid;place-items:center;animation:cjLoadSpin 1.5s linear infinite}.cj-load-orbit span{font-size:23px;animation:cjLoadCounter 1.5s linear infinite}#centralLoadRetry{margin-top:18px}@keyframes cjLoadSpin{to{transform:rotate(360deg)}}@keyframes cjLoadCounter{to{transform:rotate(-360deg)}}@media(prefers-reduced-motion:reduce){.cj-load-orbit,.cj-load-orbit span{animation:none}}</style><script>document.documentElement.classList.add('cj-catalog-loading');</script>'''
LOADER='''<section id="centralLoading" role="status" aria-live="polite"><div class="cj-load-orbit" aria-hidden="true"><span>✦</span></div><h2 id="centralLoadTitle">Preparando sua Central</h2><p id="centralLoadText">Carregando as iniciativas da equipe…</p><button id="centralLoadRetry" class="btn" hidden onclick="location.reload()">Tentar novamente</button></section>'''
def prepare(body):
    text=body.decode('utf-8')
    text=text.replace('</head>',HEAD+'</head>',1)
    text=re.sub(r'(<main\b[^>]*>)',lambda m:m[0]+LOADER,text,count=1)
    text=text.replace('remoteReady=true;render()',"remoteReady=true;render();window.dispatchEvent(new Event('cj-catalog-ready'))",1)
    # Keep the welcome function and its manual button, suppress only the initial invocation.
    text=text.replace('showWelcome()}',"window.dispatchEvent(new Event('cj-catalog-settled'))}",1)
    return text.encode()
