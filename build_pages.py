"""Prepare only the public website files for GitHub Pages."""
from pathlib import Path
import shutil
root=Path(__file__).resolve().parent
out=root/'_site'
if out.exists():shutil.rmtree(out)
out.mkdir()
html=(root/'index.html').read_text(encoding='utf-8')
point=html.rfind('<script>')
if point<0:raise RuntimeError('Script principal não encontrado.')
html=html[:point]+'<script>window.CJ_STATIC_PREVIEW=true;</script>'+html[point:]
(out/'index.html').write_text(html,encoding='utf-8')
shutil.copyfile(root/'favicon.png',out/'favicon.png')
shutil.copytree(root/'ferramentas',out/'ferramentas')
(out/'.nojekyll').write_text('')
print('Versão estática preparada em _site/')
