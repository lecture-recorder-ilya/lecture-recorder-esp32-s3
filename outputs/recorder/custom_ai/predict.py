import argparse
import hashlib
import json
import wave
from pathlib import Path
import numpy as np
import torch
from .models import SpeechModel,NotesModel,features,decode

def load(path):
    path=Path(path)
    manifest=json.loads((path.parent/'manifest.json').read_text())
    if not manifest.get('completed') or manifest.get('initialized_from')!='random':
        raise ValueError('Нужен завершённый эксперимент нашей модели')
    if hashlib.sha256(path.read_bytes()).hexdigest()!=manifest.get('checkpoint_sha256'):
        raise ValueError('Контрольная сумма модели не совпала')
    state=torch.load(path,map_location='cpu',weights_only=True)
    if state.get('architecture')!='lecture-own-v1' or state.get('task')!=manifest['task']:
        raise ValueError('Несовместимая модель')
    model=SpeechModel() if state['task']=='speech' else NotesModel()
    model.load_state_dict(state['state_dict'],strict=True);model.eval()
    return model,manifest

def main():
    parser=argparse.ArgumentParser();parser.add_argument('checkpoint',type=Path)
    parser.add_argument('--audio',type=Path);parser.add_argument('--text',type=Path)
    args=parser.parse_args();torch.set_num_threads(2)
    model,manifest=load(args.checkpoint)
    with torch.inference_mode():
        if manifest['task']=='speech':
            if args.audio is None:parser.error('Нужен --audio с коротким WAV')
            with wave.open(str(args.audio),'rb') as source:
                if (source.getnchannels(),source.getsampwidth(),source.getframerate())!=(1,2,16000) or not 8000<=source.getnframes()<=320000:
                    parser.error('Нужен WAV PCM16, моно, 16 кГц, от 0,5 до 20 секунд')
                samples=np.frombuffer(source.readframes(source.getnframes()),dtype='<i2').astype(np.float32)/32768
            result=dict(text=decode(model(features(samples))[:,0].argmax(-1).tolist()))
        else:
            if args.text is None:parser.error('Нужен --text с фрагментами, разделёнными пустой строкой')
            result=model.extract(args.text.read_text().split('\n\n'))
    print(json.dumps(dict(result=result,experimental=True,production_ready=False),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
