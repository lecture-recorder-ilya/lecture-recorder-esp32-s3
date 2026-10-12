from huggingface_hub import snapshot_download
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
root=Path(__file__).resolve().parent/'models'
def get(pair):
    repo,folder=pair
    snapshot_download(repo, local_dir=root/folder, allow_patterns=['config.json','model.safetensors','pytorch_model.bin','tokenizer.json','tokenizer_config.json','special_tokens_map.json','sentencepiece.bpe.model','preprocessor_config.json'],max_workers=3)
    print(folder+' ready',flush=True)
with ThreadPoolExecutor(2) as pool:
    list(pool.map(get,[('intfloat/multilingual-e5-small','search'),('microsoft/wavlm-base-plus-sv','speakers')]))
