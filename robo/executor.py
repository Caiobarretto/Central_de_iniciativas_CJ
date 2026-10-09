"""Executor no computador anfitrião. Só conexões de saída HTTPS."""
import base64,getpass,json,pathlib,queue,subprocess,sys,tempfile,threading,time,urllib.request,urllib.error,shutil
ROOT=pathlib.Path(__file__).resolve().parent

def main():
    config=json.loads((ROOT/'config.json').read_text());url=config['central_url'].rstrip('/');token=config['worker_token']
    if not url.startswith('https://'):raise SystemExit('Use o endereço HTTPS do Render.')
    password=getpass.getpass('Senha da Lexio (usada só nesta sessão): ')
    def api(path,data):
        request=urllib.request.Request(url+'/api/rpa/worker/'+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
        with urllib.request.urlopen(request,timeout=100) as response:return json.load(response)
    print('Executor ligado. Mantenha computador acordado e sessão do Windows aberta. Ctrl+C encerra.')
    while True:
        try:job=api('claim',{})['job']
        except Exception as e:print('Sem conexão com a Central. Tentando novamente em 60s:',type(e).__name__);time.sleep(60);continue
        if not job:time.sleep(30);continue
        print('Processando:',job['name']);run=pathlib.Path(tempfile.mkdtemp(prefix='cj-lexio-'));proc=None
        try:
            doc=run/pathlib.Path(job['name']).name;doc.write_bytes(base64.b64decode(job['document'],validate=True));result=run/'result.json'
            manifest={'files':[str(doc)],'url':'https://app.lexio.legal/empresa/dashboard','login_email':config['lexio_email'],'login_password':password,'signers':job['metadata']['signers'],'glpi_id':job['metadata'].get('glpi_id',''),'action':job['metadata']['action'],'headless':False,'metadata':job['metadata'],'result_json':str(result)}
            path=run/'manifest.json';path.write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
            proc=subprocess.Popen([sys.executable,'-u',str(ROOT/'lexio_rpa.py'),str(path)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace');logs=queue.Queue()
            def read():
                for line in proc.stdout:logs.put(line.rstrip())
            threading.Thread(target=read,daemon=True).start();start=last=time.monotonic();heartbeat_failures=0
            while proc.poll() is None:
                while not logs.empty():print(logs.get(),flush=True)
                if time.monotonic()-last>15:
                    try:api('report',{'id':job['id'],'state':'running','result':{'message':'Robô executando o documento na Lexio.'}});heartbeat_failures=0
                    except Exception:heartbeat_failures+=1
                    last=time.monotonic()
                if time.monotonic()-start>900 or heartbeat_failures>=4:
                    proc.kill();proc.wait();raise RuntimeError('Execução interrompida por tempo ou conexão. Confira a Lexio antes de reenviar.')
                time.sleep(1)
            while not logs.empty():print(logs.get(),flush=True)
            records=json.loads(result.read_text()).get('results',[]) if result.exists() else []
            ok=next((x for x in records if x.get('status')=='OK' and x.get('url','').startswith('https://app.lexio.legal/')),None)
            if proc.returncode or not ok:raise RuntimeError('O robô não confirmou o envio. Confira a Lexio antes de reenviar.')
            report={'id':job['id'],'state':'done','result':{'link':ok['url'],'message':'Documento enviado para assinatura.' if job['metadata']['action']=='sign' else 'Documento incluído na Lexio.'}}
        except Exception as e:report={'id':job['id'],'state':'uncertain','result':{'error':str(e)}}
        finally:
            if proc and proc.poll() is None:proc.kill();proc.wait()
            shutil.rmtree(run,ignore_errors=True)
        for attempt in range(3):
            try:api('report',report);break
            except Exception:time.sleep(10)
        print('Concluído:',report['state'])

if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:print('\nExecutor encerrado. Confira qualquer envio que estivesse em andamento.')
