import os,json,hashlib,time,concurrent.futures
from pathlib import Path
os.environ['HF_HUB_DISABLE_XET']='1';os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
from huggingface_hub import HfApi,hf_hub_download
repo='istupakov/gigaam-v3-onnx';m=HfApi().model_info(repo,files_metadata=True);dest=Path('work/models/gigaam-rnnt');dest.mkdir(exist_ok=True)
names=['v3_e2e_rnnt_encoder.onnx','v3_e2e_rnnt_decoder.onnx','v3_e2e_rnnt_joint.onnx','v3_e2e_rnnt_vocab.txt','config.json']
for name in names:
 f=next((f for f in m.siblings if f.rfilename==name),None)
 if not f:continue
 print('Downloading',name,f.size,flush=True)
 path=Path(hf_hub_download(repo,name,revision=m.sha,local_dir=dest))
 if f.lfs:
  expected=f.lfs.sha256 if hasattr(f.lfs,'sha256') else f.lfs['sha256'];h=hashlib.sha256()
  with path.open('rb') as source:
   for block in iter(lambda:source.read(1024*1024),b''):h.update(block)
  assert h.hexdigest()==expected
 print('Verified',name,flush=True)
Path('work/models/gigaam-rnnt-manifest.json').write_text(json.dumps({'repo':repo,'revision':m.sha,'files':names},indent=2))
