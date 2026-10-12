"""Download the selected local models; no microphone/audio files are accessed."""
import hashlib,json,os
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
os.environ.update(HF_HUB_DISABLE_TELEMETRY='1',HF_HUB_DISABLE_XET='1')
from huggingface_hub import HfApi,snapshot_download,hf_hub_download
models=ROOT/'work/models';models.mkdir(parents=True,exist_ok=True)
repo='istupakov/gigaam-v3-onnx';revision='322c3b29492673eb7d0b434bfa9dfb8653e34d02'
sets={'gigaam':['config.json','v3_e2e_ctc.int8.onnx','v3_e2e_ctc_vocab.txt'],
      'gigaam-rnnt':['config.json','v3_e2e_rnnt_encoder.onnx','v3_e2e_rnnt_decoder.onnx','v3_e2e_rnnt_joint.onnx','v3_e2e_rnnt_vocab.txt'],
      'gigaam-beam':['config.json','v3_ctc.onnx','v3_vocab.txt']}
metadata={f.rfilename:f for f in HfApi().model_info(repo,revision=revision,files_metadata=True).siblings}
for folder,names in sets.items():
 dest=models/folder;files=[]
 for name in names:
  path=Path(hf_hub_download(repo,name,revision=revision,local_dir=dest))
  digest=hashlib.sha256()
  with path.open('rb') as f:
   for block in iter(lambda:f.read(1024*1024),b''):digest.update(block)
  sha=digest.hexdigest();remote=metadata[name]
  if remote.size is not None and path.stat().st_size!=remote.size:raise ValueError('Неверный размер '+name)
  if remote.lfs and remote.lfs.sha256!=sha:raise ValueError('Неверный SHA-256 '+name)
  files.append({'name':name,'bytes':path.stat().st_size,'sha256':sha})
 (models/(folder+'-manifest.json')).write_text(json.dumps({'repo':repo,'revision':revision,'files':files},indent=2))
 print(folder+' готов',flush=True)
manifest={}
for repo,folder in [('mlx-community/Qwen2.5-7B-Instruct-4bit','lecture'),('mlx-community/whisper-large-v3-turbo','whisper')]:
 commit=HfApi().model_info(repo).sha
 snapshot_download(repo,revision=commit,local_dir=models/folder,allow_patterns=['*.json','*.safetensors','*.txt','*.model','*.tiktoken'],max_workers=3)
 manifest[folder]={'repo':repo,'revision':commit}
(models/'manifest.json').write_text(json.dumps(manifest,indent=2))
print('Модели готовы; последующая обработка работает локально.')
