from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pathlib import Path
from datetime import datetime
from typing import Optional, Any
import sqlite3, hashlib, json, os, re, shutil, logging, math

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = Path(os.getenv('DATABASE_URL', ROOT / 'organizer.db'))
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('organizer')

app = FastAPI(title='AI Desktop Organizer API', version='1.0.0', description='Local-first semantic file intelligence API')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])

def db():
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row; return conn

def init_db():
    conn=db(); conn.executescript('''
    CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, name TEXT, ext TEXT, size INTEGER, created REAL, modified REAL, sha256 TEXT, text TEXT, category TEXT, topics TEXT, summary TEXT, importance TEXT, confidence REAL, status TEXT DEFAULT 'indexed', error TEXT, is_demo INTEGER DEFAULT 0);
    CREATE INDEX IF NOT EXISTS idx_files_hash ON files(sha256); CREATE INDEX IF NOT EXISTS idx_files_category ON files(category);
    CREATE TABLE IF NOT EXISTS operations(id INTEGER PRIMARY KEY, action TEXT, source TEXT, destination TEXT, created_at TEXT, undone INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS scans(id INTEGER PRIMARY KEY, root TEXT, status TEXT, discovered INTEGER DEFAULT 0, processed INTEGER DEFAULT 0, errors INTEGER DEFAULT 0, started_at TEXT, finished_at TEXT);
    '''); conn.commit(); conn.close()
init_db()

TEXT_EXT = {'.txt','.md','.csv','.json','.xml','.py','.js','.ts','.tsx','.jsx','.html','.css','.sql','.java','.c','.cpp','.h','.yml','.yaml','.log'}
CAT_RULES = [('Resume',['resume','cv']),('Certificates',['certificate','certification']),('College',['dbms','java','algorithm','datastructure','assignment','lecture','unit','semester','notes']),('Projects',['project','agri','smart','cart','app','src']),('Finance',['invoice','bank','tax','budget']),('Work',['meeting','client','report','proposal']),('Images',['screenshot','img','photo','scan']),('Archives',['zip','rar','7z','tar']),('Documents',['document','letter','contract'])]

def now(): return datetime.now().isoformat(timespec='seconds')
def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()
def extract(path):
    ext=path.suffix.lower()
    try:
        if ext in TEXT_EXT: return path.read_text(errors='ignore')[:100000]
        if ext=='.docx':
            from docx import Document
            return '\n'.join(p.text for p in Document(path).paragraphs)[:100000]
        if ext=='.pdf':
            try:
                from pypdf import PdfReader
                return '\n'.join((p.extract_text() or '') for p in PdfReader(str(path)).pages)[:100000]
            except Exception: return ''
        if ext in {'.jpg','.jpeg','.png','.webp'}:
            try:
                import pytesseract
                from PIL import Image
                return pytesseract.image_to_string(Image.open(path))[:100000]
            except Exception: return ''
    except Exception as e: log.warning('extract failed for %s: %s', path, e)
    return ''
def classify(name,text):
    hay=(name+' '+text[:5000]).lower()
    scores=[]
    for cat, words in CAT_RULES:
        score=sum(1 for w in words if w in hay)
        if score: scores.append((score,cat))
    if not scores: return ('Miscellaneous',0.62)
    score,cat=max(scores); return (cat,min(.98,.70+score*.06))
def topics(text,name):
    vocab=['normalization','functional dependencies','3nf','bcnf','inheritance','python','java','machine learning','database','react','finance','resume','assignment','project','agriculture','image','invoice']
    hay=(name+' '+text).lower(); return [x.title() for x in vocab if x in hay][:8]
def file_row(r):
    d=dict(r); d['topics']=json.loads(d['topics'] or '[]'); d['isDuplicate']=False; d['duplicateCount']=1; return d

def scan_folder(root:Path, scan_id:int):
    conn=db(); files=[]; errors=0
    try: files=[p for p in root.rglob('*') if p.is_file() and not any(x in {'.git','node_modules','venv','__pycache__'} for x in p.parts)]
    except Exception as e: log.error('scan discovery: %s',e)
    conn.execute('UPDATE scans SET discovered=? WHERE id=?',(len(files),scan_id)); conn.commit()
    for i,p in enumerate(files,1):
        try:
            st=p.stat(); text=extract(p); cat,conf=classify(p.name,text); digest=sha(p)
            conn.execute('''INSERT INTO files(path,name,ext,size,created,modified,sha256,text,category,topics,summary,importance,confidence,status,is_demo) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET size=excluded.size,modified=excluded.modified,sha256=excluded.sha256,text=excluded.text,category=excluded.category,topics=excluded.topics,summary=excluded.summary,confidence=excluded.confidence,status='indexed',error=NULL''', (str(p),p.name,p.suffix.lower(),st.st_size,st.st_ctime,st.st_mtime,digest,text,cat,json.dumps(topics(text,p.name)),(text.strip().replace('\n',' ')[:240] if text else f'{p.suffix.upper()[1:] or "File"} ready for review.'),'High' if conf>.88 else 'Medium',conf,'indexed', int('demo_files' in p.parts)))
        except Exception as e:
            errors+=1; conn.execute('INSERT OR REPLACE INTO files(path,name,status,error) VALUES(?,?,?,?)',(str(p),p.name,'error',str(e)))
        conn.execute('UPDATE scans SET processed=?,errors=? WHERE id=?',(i,errors,scan_id)); conn.commit()
    conn.execute('UPDATE scans SET status=?,finished_at=? WHERE id=?',('complete',now(),scan_id)); conn.commit(); conn.close()

class ScanRequest(BaseModel): root: str
class PlanAction(BaseModel): id:int; destination:str; approved:bool=True
class ApplyRequest(BaseModel): actions:list[PlanAction]
class Settings(BaseModel): values: dict[str,Any]

@app.get('/health')
def health(): return {'status':'ok','service':'ai-desktop-organizer','mode':'local' if os.getenv('AI_PROVIDER','local') in {'local','demo',''} else 'external'}
@app.post('/scan')
def scan(req:ScanRequest):
    root=Path(req.root).expanduser().resolve()
    if not root.exists() or not root.is_dir(): raise HTTPException(400,'Folder does not exist or is not readable')
    conn=db(); cur=conn.execute('INSERT INTO scans(root,status,started_at) VALUES(?,?,?)',(str(root),'running',now())); sid=cur.lastrowid; conn.commit(); conn.close()
    # synchronous is deterministic for API; frontend uses progress endpoint; production wrapper can enqueue this worker
    scan_folder(root,sid); return {'id':sid,'status':'complete'}
@app.get('/scan/{sid}')
def scan_status(sid:int):
    r=db().execute('SELECT * FROM scans WHERE id=?',(sid,)).fetchone();
    if not r: raise HTTPException(404,'Scan not found')
    return dict(r)
@app.get('/files')
def files(q:Optional[str]=None, category:Optional[str]=None, limit:int=100, offset:int=0):
    conn=db(); where=[]; vals=[]
    if q: where.append('(name LIKE ? OR text LIKE ? OR category LIKE ? OR topics LIKE ?)'); vals += [f'%{q}%']*4
    if category: where.append('category=?'); vals.append(category)
    clause=' WHERE '+' AND '.join(where) if where else ''
    rows=conn.execute(f'SELECT * FROM files{clause} ORDER BY modified DESC LIMIT ? OFFSET ?',(*vals,limit,offset)).fetchall(); allrows=conn.execute(f'SELECT COUNT(*) c FROM files{clause}',vals).fetchone()['c']; conn.close()
    return {'items':[file_row(x) for x in rows],'total':allrows}
@app.get('/files/{fid}')
def file_detail(fid:int):
    r=db().execute('SELECT * FROM files WHERE id=?',(fid,)).fetchone()
    if not r: raise HTTPException(404,'File not found')
    return file_row(r)
@app.get('/stats')
def stats():
    c=db(); total=c.execute('SELECT COUNT(*) c FROM files').fetchone()['c']; size=c.execute('SELECT COALESCE(SUM(size),0) s FROM files').fetchone()['s']; dup=c.execute('SELECT COUNT(*) c FROM (SELECT sha256 FROM files GROUP BY sha256 HAVING COUNT(*)>1)').fetchone()['c']; cats=c.execute('SELECT category,COUNT(*) count FROM files GROUP BY category ORDER BY count DESC').fetchall(); c.close(); return {'totalFiles':total,'totalBytes':size,'analyzed':total,'duplicates':dup,'oldVersions':max(0,dup-1),'needsReview':0,'categories':[dict(x) for x in cats]}
@app.get('/duplicates')
def duplicates():
    c=db(); groups=[]
    for r in c.execute('SELECT sha256,COUNT(*) count FROM files GROUP BY sha256 HAVING count>1'):
        groups.append({'hash':r['sha256'],'count':r['count'],'files':[file_row(x) for x in c.execute('SELECT * FROM files WHERE sha256=?',(r['sha256'],))]})
    c.close(); return groups
@app.get('/versions')
def versions():
    c=db(); rows=c.execute("SELECT * FROM files WHERE name LIKE '%final%' OR name LIKE '%latest%' OR name LIKE '%old%' OR name LIKE '%v%'").fetchall(); c.close(); return [file_row(x) for x in rows]
@app.get('/search')
def search(q:str):
    tokens=set(re.findall(r'[a-z0-9]+',q.lower())); c=db(); rows=c.execute('SELECT * FROM files').fetchall(); out=[]
    for r in rows:
        words=set(re.findall(r'[a-z0-9]+',(r['name']+' '+(r['text'] or '')+' '+(r['category'] or '')+' '+(r['topics'] or '')).lower())); score=len(tokens&words)/max(1,len(tokens));
        if score>0: out.append((score,file_row(r)))
    c.close(); out.sort(key=lambda x:x[0],reverse=True); return [{'relevance':round(min(.99,.45+x[0]*.55),2),'matchedConcepts':list(tokens & set(re.findall(r'[a-z0-9]+',x[1]['name'].lower())))[:4],'explanation':f'Matches {len(tokens & set(re.findall(r"[a-z0-9]+", (x[1]["text"] or "").lower())))} concepts from your query.',**x[1]} for _,x in out[:50]]
@app.post('/organize/preview')
def organize_preview():
    c=db(); rows=c.execute("SELECT * FROM files WHERE status='indexed' ORDER BY confidence DESC").fetchall(); c.close(); actions=[]
    for r in rows:
        p=Path(r['path']); dest=Path('Organized')/r['category'];
        if r['topics']: dest/=r['topics'][0]
        dest=dest/p.name
        actions.append({'id':r['id'],'source':r['path'],'destination':str(p.parent/dest),'confidence':r['confidence'],'reason':f"Content and filename align with {r['category']}; detected topics: {', '.join(json.loads(r['topics'] or '[]')) or 'general file context'}.",'approved':r['confidence']>=.85})
    return {'actions':actions}
@app.post('/organize/apply')
def organize_apply(req:ApplyRequest):
    c=db(); done=[]
    for a in req.actions:
        r=c.execute('SELECT path FROM files WHERE id=?',(a.id,)).fetchone()
        if not r or not a.approved: continue
        src=Path(r['path']); dst=Path(a.destination).expanduser().resolve()
        try:
            if src.resolve()==dst: continue
            dst.parent.mkdir(parents=True,exist_ok=True); final=dst
            if final.exists(): final=dst.with_name(dst.stem+'_copy'+dst.suffix)
            shutil.move(str(src),str(final)); c.execute('UPDATE files SET path=? WHERE id=?',(str(final),a.id)); c.execute('INSERT INTO operations(action,source,destination,created_at) VALUES(?,?,?,?)',('move',str(src),str(final),now())); done.append({'id':a.id,'source':str(src),'destination':str(final)})
        except Exception as e: log.warning('move failed: %s',e)
    c.commit(); c.close(); return {'moved':done}
@app.get('/activity')
def activity():
    c=db(); rows=c.execute('SELECT * FROM operations ORDER BY id DESC LIMIT 50').fetchall(); c.close(); return [dict(x) for x in rows]
@app.post('/operations/{oid}/undo')
def undo(oid:int):
    c=db(); r=c.execute('SELECT * FROM operations WHERE id=? AND undone=0',(oid,)).fetchone()
    if not r: raise HTTPException(404,'Operation not found or already undone')
    try:
        Path(r['source']).parent.mkdir(parents=True,exist_ok=True); shutil.move(r['destination'],r['source']); c.execute('UPDATE files SET path=? WHERE path=?',(r['source'],r['destination'])); c.execute('UPDATE operations SET undone=1 WHERE id=?',(oid,)); c.commit(); return {'status':'undone'}
    except Exception as e: raise HTTPException(400,str(e))
@app.get('/settings')
def get_settings():
    c=db(); vals={r['key']:json.loads(r['value']) for r in c.execute('SELECT * FROM settings')}; c.close(); return vals
@app.put('/settings')
def put_settings(s:Settings):
    c=db();
    for k,v in s.values.items(): c.execute('INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)',(k,json.dumps(v)))
    c.commit(); c.close(); return s.values
