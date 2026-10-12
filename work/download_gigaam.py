from pathlib import Path
import os,json,hashlib,time,concurrent.futures
os.environ['HF_HUB_DISABLE_XET']='1';os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
from huggingface_hub import HfApi,snapshot_download
import requests,threading
local=threading.local()
root=Path(__file__).resolve().parent;manifest={}
for repo,target in [('istupakov/gigaam-v3-onnx','gigaam')]:
 m=HfApi().model_info(repo,files_metadata=True);dest=root/'models'/target;dest.mkdir(exist_ok=True)
 snapshot_download(repo_id=repo,revision=m.sha,local_dir=dest,allow_patterns=['*.json','*.txt','*.model','*.tiktoken','*.vocab','*.tokens'],max_workers=3)
 for f in m.siblings:
  if f.rfilename!='v3_e2e_ctc.int8.onnx':continue
  out=dest/f.rfilename
  if out.exists() and out.stat().st_size==f.size:continue
  parts=root/'asr-parts'/target/(f.rfilename+'-1m');parts.mkdir(parents=True,exist_ok=True)
  for old in (root/'asr-parts'/target/f.rfilename).glob('*'):
   if old.name.isdigit() and old.stat().st_size==8*1024*1024:
    data=old.read_bytes()
    for j in range(8):(parts/str(int(old.name)*8+j)).write_bytes(data[j*1024*1024:(j+1)*1024*1024])
  chunk=1024*1024
  # Reuse complete blocks from the interrupted normal download.
  for partial in (dest/'.cache/huggingface/download').glob('*.incomplete'):
   with partial.open('rb') as source:
    for i in range(partial.stat().st_size//chunk):
     block=source.read(chunk);part=parts/str(i)
     if not part.exists():part.write_bytes(block)
  n=(f.size+chunk-1)//chunk
  def fetch(i):
   if not hasattr(local,"session"):local.session=requests.Session()
   part=parts/str(i);a=i*chunk;b=min(f.size,(i+1)*chunk)-1
   if part.exists() and part.stat().st_size==b-a+1:return
   for attempt in range(20):
    try:
     url='https://huggingface.co/'+repo+'/resolve/'+m.sha+'/'+f.rfilename+'?download=true&chunk=1m&part='+str(i)
     with local.session.get(url,headers={'Range':f'bytes={a}-{b}'},stream=True,timeout=(15,60)) as r:
      r.raise_for_status()
      if r.status_code!=206 or not r.headers.get('Content-Range','').startswith(f'bytes {a}-{b}/'):raise ValueError('Unexpected range')
      temp=part.with_suffix('.tmp')
      with temp.open('wb') as file:
       for data in r.iter_content(256*1024):file.write(data)
      if temp.stat().st_size!=b-a+1:raise ValueError('Partial range')
      temp.replace(part)
     return
    except Exception:
     if attempt==19:raise
     time.sleep(min(30,2*(attempt+1)))
  with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
   for done,_ in enumerate(pool.map(fetch,range(n)),1):
    if done%10==0:print(target,done,'/',n,flush=True)
  h=hashlib.sha256();temp=out.with_suffix('.download')
  with temp.open('wb') as file:
   for i in range(n):
    with (parts/str(i)).open('rb') as part:
     while data:=part.read(1024*1024):file.write(data);h.update(data)
  expected=f.lfs.sha256 if hasattr(f.lfs,'sha256') else f.lfs['sha256']
  assert h.hexdigest()==expected,'Checksum mismatch'
  temp.replace(out)
 manifest[target]={'repo':repo,'revision':m.sha}
 print('Ready',target,flush=True)
(root/'models/gigaam-manifest.json').write_text(json.dumps(manifest,indent=2))
