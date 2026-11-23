import hashlib,json,os
from pathlib import Path
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
from huggingface_hub import HfApi,snapshot_download
ROOT=Path(__file__).resolve().parent.parent
REPO='mlx-community/Qwen3-VL-4B-Instruct-4bit'
REVISION='2fd8dacbdb8f1e54b8c005f081ec5bf79c56376b'
def main():
 dest=ROOT/'work/models/board-vision'
 snapshot_download(REPO,revision=REVISION,local_dir=dest,allow_patterns=['*.json','*.safetensors','*.txt','*.jinja','*.model'],max_workers=3)
 metadata=HfApi().model_info(REPO,revision=REVISION,files_metadata=True)
 files=[]
 for remote in metadata.siblings:
  path=dest/remote.rfilename
  if not path.is_file():continue
  digest=hashlib.sha256()
  with path.open('rb') as source:
   for block in iter(lambda:source.read(1024*1024),b''):digest.update(block)
  sha=digest.hexdigest()
  if remote.size is not None and path.stat().st_size!=remote.size:raise ValueError('Неверный размер '+remote.rfilename)
  if remote.lfs and remote.lfs.sha256!=sha:raise ValueError('Неверный SHA-256 '+remote.rfilename)
  files.append({'name':remote.rfilename,'bytes':path.stat().st_size,'sha256':sha})
 if not any(f['name'].endswith('.safetensors') for f in files):raise ValueError('Нет весов модели')
 manifest=dest.parent/'board-vision-manifest.json';temp=manifest.with_suffix('.tmp')
 temp.write_text(json.dumps({'repo':REPO,'revision':REVISION,'files':files},indent=2));temp.replace(manifest)
 print('Модель чтения доски готова. Фото обрабатываются локально.',flush=True)
if __name__=='__main__':main()
