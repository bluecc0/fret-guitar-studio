"""Local Mac companion: Audiveris job runner + OpenAI-compatible VLM adapter."""
import asyncio
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .musicxml import parse_musicxml, ScoreError
from . import vlm

ROOT=Path(__file__).resolve().parents[1]
# Minimal dotenv loader, never exposes values in responses or logs.
for envfile in (ROOT/'.env',ROOT/'.env.local'):
    if envfile.is_file():
        for line in envfile.read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                k,v=line.split('=',1);os.environ.setdefault(k.strip(),v.strip().strip('\"\''))
MAX_UPLOAD=20*1024*1024
jobs={};lock=threading.Lock();pool=ThreadPoolExecutor(max_workers=1)

def audiveris_bin():
    value=os.getenv('AUDIVERIS_BIN','').strip()
    candidates=[value,shutil.which('Audiveris'),shutil.which('audiveris'),'/Applications/Audiveris.app/Contents/MacOS/Audiveris']
    return next((str(Path(c).expanduser()) for c in candidates if c and Path(c).expanduser().is_file() and os.access(Path(c).expanduser(),os.X_OK)),None)

@asynccontextmanager
async def lifespan(app):
    yield
    pool.shutdown(wait=False,cancel_futures=True)
app=FastAPI(title='Fret Recognition Service',lifespan=lifespan)
origins=[s.strip() for s in os.getenv('FRET_ALLOWED_ORIGINS','https://fret-guitar-studio.jovialpark131.chatgpt.site').split(',') if s.strip()]
origins += ['http://127.0.0.1:8765','http://localhost:8765']
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_methods=['GET','POST','OPTIONS'],allow_headers=['Content-Type'])

@app.middleware('http')
async def origin_and_size(request:Request,call_next):
    from fastapi.responses import JSONResponse
    origin=request.headers.get('origin')
    if origin and origin not in origins: return JSONResponse({'detail':'Origin 不被允许'},status_code=403)
    size=request.headers.get('content-length')
    if size and int(size)>MAX_UPLOAD+65536: return JSONResponse({'detail':'文件超过 20 MB'},status_code=413)
    if request.url.path.startswith('/api/') and request.headers.get('host','').split(':')[0] not in ('127.0.0.1','localhost','testserver'):
        return JSONResponse({'detail':'本地服务仅接受 localhost Host；远程部署需加上认证网关。'},status_code=403)
    response=await call_next(request)
    if origin in origins: response.headers['Access-Control-Allow-Private-Network']='true'
    return response

@app.get('/api/health')
def health():
    return {'service':'fret-recognition','audiveris':{'configured':bool(audiveris_bin())},'vlm':vlm.config_status(),'limits':{'maxMB':20,'maxPDFPages':12},'storage':'temporary-files-deleted-after-job'}

def update(jid,**values):
    with lock: jobs[jid].update(values)

def worker(jid,data,suffix,engine):
    update(jid,status='running',stage='正在读取乐谱' if suffix in ('.xml','.musicxml','.mxl') else '正在运行识谱引擎')
    try:
        with tempfile.TemporaryDirectory(prefix='fret-omr-') as directory:
            folder=Path(directory);source=folder/('score'+suffix);source.write_bytes(data)
            if suffix in ('.xml','.musicxml','.mxl'):
                score=parse_musicxml(data)
            elif engine=='vlm':
                if suffix=='.pdf':
                    # Standard chat-completions image input: rasterize locally, no provider-specific PDF payload.
                    pdf=shutil.which('pdftoppm')
                    if not pdf: raise ScoreError('VLM PDF 输入需要 pdftoppm（Mac: brew install poppler）。可先导出为 PNG。')
                    p=subprocess.run([pdf,'-scale-to','1800','-png',str(source),str(folder/'page')],capture_output=True,timeout=90)
                    pages=sorted(folder.glob('page-*.png'))
                    if p.returncode or not pages: raise ScoreError('PDF 页面转换失败')
                    images=[(p.read_bytes(),'image/png') for p in pages]
                else: images=[(data,{'.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png','.webp':'image/webp'}[suffix])]
                if sum(len(v) for v,m in images)>MAX_UPLOAD: raise ScoreError('VLM 图像总大小超过 20 MB，请减少页数。')
                answer=vlm.transcribe(images);score=parse_musicxml(answer['musicxml'].encode());score['source']='vlm'
                score['warnings']+= [str(w)[:500] for w in answer.get('warnings',[])][:100]
            else:
                binary=audiveris_bin()
                if not binary: raise ScoreError('未安装或配置 Audiveris，请在 .env.local 设置 AUDIVERIS_BIN。')
                out=folder/'output';out.mkdir()
                command=[binary,'-batch','-transcribe','-export','-output',str(out),'--',str(source)]
                try: p=subprocess.run(command,capture_output=True,timeout=int(os.getenv('AUDIVERIS_TIMEOUT','300')),cwd=folder)
                except subprocess.TimeoutExpired: raise ScoreError('Audiveris 识谱超时，请减少页数或提高图像清晰度。') from None
                files=list(out.rglob('*.mxl'))+list(out.rglob('*.musicxml'))+list(out.rglob('*.xml'))
                files=[p for p in files if p.name!='container.xml']
                if not files: raise ScoreError('Audiveris 没有导出 MusicXML，请先在其桌面界面检查谱面、OCR 语言包与运行日志。六线谱可切换 VLM（配置后可用）。')
                if len(files)>1: raise ScoreError('Audiveris 导出了多个乐章，请拆分文件分别导入，避免遗漏。')
                score=parse_musicxml(files[0].read_bytes());score['source']='audiveris'
            update(jid,status='completed',stage='识谱完成，等待校对',score=score)
    except Exception as exc:
        safe=str(exc) if isinstance(exc,(ScoreError,vlm.VLMNotConfigured)) else '识谱服务处理失败，请检查输入文件与服务端配置。'
        update(jid,status='failed',stage='识谱失败',error=safe)

@app.post('/api/recognitions',status_code=202)
async def recognize(file:UploadFile=File(...),engine:str=Form('audiveris')):
    if engine not in ('audiveris','vlm'): raise HTTPException(400,'无效的识谱引擎')
    suffix=Path(file.filename or '').suffix.lower()
    if suffix not in ('.pdf','.png','.jpg','.jpeg','.webp','.xml','.musicxml','.mxl'): raise HTTPException(415,'不支持的文件类型')
    data=await file.read(MAX_UPLOAD+1);await file.close()
    if not data or len(data)>MAX_UPLOAD: raise HTTPException(413,'文件为空或超过 20 MB')
    isxml=suffix in ('.xml','.musicxml','.mxl')
    if not isxml:
        if engine=='audiveris' and not audiveris_bin(): raise HTTPException(503,'Audiveris 未配置，请安装后设置 AUDIVERIS_BIN。')
        if engine=='vlm' and not vlm.config_status()['configured']: raise HTTPException(503,'VLM 尚未配置；请在服务端填写 Base URL、模型名和 Key。')
        if suffix=='.pdf':
            if not data.startswith(b'%PDF'): raise HTTPException(400,'无效的 PDF')
            try:
                from pypdf import PdfReader
                from io import BytesIO
                pdf=PdfReader(BytesIO(data))
                if pdf.is_encrypted: raise ValueError()
                if len(pdf.pages)>12: raise HTTPException(400,'单次最多 12 页，请拆分 PDF。')
            except HTTPException: raise
            except Exception: raise HTTPException(400,'PDF 损坏或已加密') from None
        elif not (data.startswith(b'\x89PNG') or data.startswith(b'\xff\xd8\xff') or data.startswith(b'RIFF') and data[8:12]==b'WEBP'):
            raise HTTPException(400,'图像内容与格式不符')
    with lock:
        now=time.time()
        for old in [k for k,v in jobs.items() if now-v['created']>3600 and v['status'] in ('completed','failed')]: del jobs[old]
        if sum(j['status'] in ('queued','running') for j in jobs.values())>=3: raise HTTPException(429,'识谱队列已满，请稍后重试')
        if len(jobs)>=100: raise HTTPException(429,'识谱记录达到上限，请稍后重试或重启本地服务')
        jid=uuid.uuid4().hex;jobs[jid]={'id':jid,'status':'queued','stage':'等待识谱','created':now}
    pool.submit(worker,jid,data,suffix,engine)
    return {'id':jid,'status':'queued'}

@app.get('/api/recognitions/{jid}')
def job(jid:str):
    with lock:
        if jid not in jobs: raise HTTPException(404,'识谱任务不存在或已过期')
        return dict(jobs[jid])

app.mount('/',StaticFiles(directory=ROOT/'dist',html=True),name='frontend')
