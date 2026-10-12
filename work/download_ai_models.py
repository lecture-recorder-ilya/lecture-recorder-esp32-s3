from pathlib import Path
import os,json
root=Path(__file__).resolve().parent
os.environ['HF_HOME']=str(root/'hf-cache')
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
os.environ['HF_HUB_DISABLE_XET']='1'
from huggingface_hub import snapshot_download,HfApi
manifest={}
for repo,target in [('mlx-community/whisper-large-v3-turbo','whisper'),('mlx-community/Qwen2.5-7B-Instruct-4bit','lecture')]:
 print('Downloading',target,flush=True)
 commit=HfApi().model_info(repo).sha
 snapshot_download(repo_id=repo,revision=commit,local_dir=root/'models'/target,allow_patterns=['*.json','*.safetensors','*.txt','*.model','*.tiktoken'],max_workers=3)
 manifest[target]={'repo':repo,'revision':commit}
 print('Ready',target,flush=True)
(root/'models'/'manifest.json').write_text(json.dumps(manifest,indent=2))
