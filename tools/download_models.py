"""Download the selected local models; no microphone/audio files are accessed."""
import hashlib,json,os
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
os.environ.update(HF_HUB_DISABLE_TELEMETRY='1',HF_HUB_DISABLE_XET='1')
from huggingface_hub import HfApi,snapshot_download,hf_hub_download
models=ROOT/'work/models';models.mkdir(parents=True,exist_ok=True)
specs=json.loads((ROOT/'installer/models.json').read_text())
for spec in specs:
 folder=spec['folder']
 if folder not in ('gigaam','gigaam-rnnt','gigaam-beam'):continue
 dest=models/folder
 for file in spec['files']:
  name=file['name']
  path=Path(hf_hub_download(spec['repo'],name,revision=spec['revision'],local_dir=dest))
  if path.stat().st_size!=file['bytes']:raise ValueError('Неверный размер '+name)
  with path.open('rb') as source:
   if hashlib.file_digest(source,'sha256').hexdigest()!=file['sha256']:raise ValueError('Неверный SHA-256 '+name)
 temporary=models/(folder+'-manifest.'+str(os.getpid())+'.tmp')
 try:
  temporary.write_text(json.dumps(spec,indent=2))
  temporary.replace(models/(folder+'-manifest.json'))
 finally:
  temporary.unlink(missing_ok=True)
 print(folder+' готов',flush=True)
manifest={}
for repo,folder in [('mlx-community/Qwen2.5-7B-Instruct-4bit','lecture'),('mlx-community/whisper-large-v3-turbo','whisper')]:
 commit=HfApi().model_info(repo).sha
 snapshot_download(repo,revision=commit,local_dir=models/folder,allow_patterns=['*.json','*.safetensors','*.txt','*.model','*.tiktoken'],max_workers=3)
 manifest[folder]={'repo':repo,'revision':commit}
(models/'manifest.json').write_text(json.dumps(manifest,indent=2))
print('Модели готовы; последующая обработка работает локально.')
