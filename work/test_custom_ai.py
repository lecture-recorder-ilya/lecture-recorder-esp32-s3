import hashlib
import io
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np
import torch

sys.path.insert(0,str(Path('outputs/recorder').resolve()))
from custom_ai.corpus import Corpus
from custom_ai.models import SpeechModel,NotesModel,features,encode,decode,edit_distance
from custom_ai.train import train
from custom_ai.predict import load
from custom_ai import server

class CustomTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.recorder=self.root/'recorder';(self.recorder/'recordings').mkdir(parents=True)
        self.corpus=Corpus(self.recorder,self.root/'private')
        self.originals={}
        for n in range(3):
            name=f'lecture-{n}.wav';path=self.recorder/'recordings'/name
            x=(np.sin(np.arange(16000)*2*np.pi*400/16000)*4000).astype('<i2')
            x=np.concatenate([x,np.zeros(32000,dtype='<i2')])
            with wave.open(str(path),'wb') as out:
                out.setparams((1,2,16000,0,'NONE','none'));out.writeframes(x.tobytes())
            self.originals[path]=hashlib.sha256(path.read_bytes()).hexdigest()
    def tearDown(self):
        for path,digest in self.originals.items():self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),digest)
        self.tmp.cleanup()
    def body(self,n=0,**kwargs):
        return dict(file=f'lecture-{n}.wav',start=0,end=.8,text='Домашнее задание решить пример',
                    labels=['homework'],silence=False,reviewed=True,**kwargs)
    def test_originals_and_verified_audio_are_preserved(self):
        row=self.corpus.review(self.body())
        with wave.open(io.BytesIO(self.corpus.clip('lecture-0.wav',0,.8)),'rb') as source:
            self.assertEqual(source.getnframes(),12800)
        self.assertEqual(len(self.corpus.verified()),1)
        path=self.corpus.root/(row['id']+'.wav');path.write_bytes(path.read_bytes()[:-2]+b'xx')
        with self.assertRaisesRegex(ValueError,'Контрольная'):self.corpus.verified()
    def test_automatic_or_ambiguous_labels_cannot_be_accepted(self):
        for overrides in [dict(reviewed=False),dict(silence=True),dict(text=''),dict(labels=['unknown'])]:
            body=self.body();body.update(overrides)
            with self.assertRaises(ValueError):self.corpus.review(body)
        body=self.body();body.update(silence=True,text='',labels=[])
        self.assertTrue(self.corpus.review(body)['silence'])
    def test_path_escape_and_invalid_ranges_are_rejected(self):
        for name in ['../lecture-0.wav','/tmp/lecture-0.wav','lecture-0.wav\0']:
            with self.assertRaises(ValueError):self.corpus.clip(name,0,.8)
        for start,end in [(0,21),(-1,.8),(0,float('nan')),(0,4),(True,.8)]:
            with self.assertRaises(ValueError):self.corpus.clip('lecture-0.wav',start,end)
    def test_same_lesson_and_merged_sources_do_not_leak_between_splits(self):
        rows=[self.corpus.review(self.body(n)) for n in range(3)]
        a,b=self.corpus.split(rows);self.assertFalse({r['file'] for r in a}&{r['file'] for r in b})
        study=self.recorder/'study';study.mkdir()
        (study/'lecture-1.notes.json').write_text(json.dumps({'parts':[{'file':'lecture-0.wav'}]}))
        with self.assertRaises(ValueError):self.corpus.split(rows)
        (study/'lecture-1.notes.json').unlink()
        lesson=self.recorder/'lessons'/'one';lesson.mkdir(parents=True)
        (lesson/'занятие.json').write_text(json.dumps({'recordings':['lecture-0.wav','lecture-1.wav']}))
        with self.assertRaises(ValueError):self.corpus.split(rows)
    def test_training_without_reviewed_data_is_refused(self):
        with self.assertRaisesRegex(ValueError,'20'):train('speech',self.corpus,1)
        self.assertFalse((self.corpus.root/'runs').exists())
    def test_speech_training_has_finite_gradients_on_speech_and_silence(self):
        torch.set_num_threads(2);torch.manual_seed(42)
        model=SpeechModel();optimizer=torch.optim.Adam(model.parameters(),lr=.002)
        x=features(np.sin(np.arange(8000)*2*np.pi*400/16000).astype(np.float32)*.2)
        target=encode('а');loss_fn=torch.nn.CTCLoss()
        losses=[]
        for _ in range(8):
            optimizer.zero_grad();scores=model(x)
            loss=loss_fn(scores,target,torch.tensor([len(scores)]),torch.tensor([len(target)]))
            self.assertTrue(torch.isfinite(loss));loss.backward();optimizer.step();losses.append(float(loss.detach()))
        self.assertLess(losses[-1],losses[0])
        scores=model(features(np.zeros(8000,dtype=np.float32)))
        loss=loss_fn(scores,encode(''),torch.tensor([len(scores)]),torch.tensor([0]))
        self.assertTrue(torch.isfinite(loss))
        self.assertEqual(decode([0,1,1,0,1,2,2]),'а')
        self.assertEqual(edit_distance('а б'.split(),'а в'.split()),1)
    def test_notes_preserve_whole_formula_and_learn_from_random_weights(self):
        torch.set_num_threads(2);torch.manual_seed(42)
        model=NotesModel();optimizer=torch.optim.Adam(model.parameters(),lr=.003)
        text='Формула решения: x = (-b + sqrt(b² - 4ac)) / (2a).'
        target=torch.tensor([0.,0.,1.,0.,0.]);losses=[]
        for _ in range(15):
            optimizer.zero_grad();loss=torch.nn.functional.binary_cross_entropy_with_logits(model(text),target)
            loss.backward();optimizer.step();losses.append(float(loss.detach()))
        self.assertLess(losses[-1],losses[0])
        self.assertEqual(model.extract([text])['formula'],[text])
    def test_training_artifact_is_explicitly_experimental(self):
        for n in range(3):
            for i in range(7):
                body=self.body(n);body.update(start=i*.025,end=.8+i*.025)
                self.corpus.review(body)
        run=train('notes',self.corpus,1)
        manifest=json.loads((run/'manifest.json').read_text())
        self.assertEqual(manifest['initialized_from'],'random')
        self.assertFalse(manifest['pretrained_weights_used']);self.assertFalse(manifest['production_ready'])
        state=torch.load(run/'candidate.pt',weights_only=True)
        self.assertEqual(state['task'],'notes')
        model,loaded=load(run/'candidate.pt')
        self.assertFalse(loaded['production_ready'])
        self.assertIn('homework',model.extract(['Домашнее задание решить пример']))
        (run/'candidate.pt').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'Контрольная'):load(run/'candidate.pt')
    def test_complete_speech_training_on_synthetic_control_audio(self):
        for n in range(3):
            for i in range(7):
                body=self.body(n)
                body.update(start=i*.025,end=.5+i*.025,text='а',labels=[])
                if i==6:body.update(start=1.1,end=1.6,text='',silence=True)
                self.corpus.review(body)
        run=train('speech',self.corpus,1)
        manifest=json.loads((run/'manifest.json').read_text())
        self.assertEqual(manifest['parameter_count'],526759)
        self.assertFalse(manifest['production_ready'])
        result=json.loads((run/'evaluation.json').read_text())
        self.assertIsNotNone(result['false_text_on_silence'])
        self.assertEqual(len(result['examples']),7)

class HttpTests(unittest.TestCase):
    def test_active_capture_is_protected_from_annotation_and_training(self):
        state=json.dumps({'recording':True,'file':'active.wav'}).encode()
        for name in ('active.wav',None):
            with patch.object(server,'urlopen',return_value=io.BytesIO(state)):
                with self.assertRaises(ValueError):server.inactive(name)
        with patch.object(server,'urlopen',return_value=io.BytesIO(state)):
            server.inactive('saved.wav')
    def test_origin_and_host_guards_and_empty_training(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'recordings').mkdir()
            corpus=Corpus(root,root/'private')
            with patch.object(server,'CORPUS',corpus):
                app=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
                thread=threading.Thread(target=app.serve_forever,daemon=True);thread.start()
                url=f'http://127.0.0.1:{app.server_port}'
                try:
                    self.assertEqual(json.load(urllib.request.urlopen(url+'/status'))['examples'],0)
                    for headers in [{'Origin':'https://example.com'},{'Host':'example.com'}]:
                        request=urllib.request.Request(url+'/review',data=b'{}',headers=headers)
                        with self.assertRaises(urllib.error.HTTPError) as caught:urllib.request.urlopen(request)
                        self.assertEqual(caught.exception.code,403)
                    request=urllib.request.Request(url+'/train',data=b'{"task":"speech"}')
                    with self.assertRaises(urllib.error.HTTPError) as caught:urllib.request.urlopen(request)
                    self.assertEqual(caught.exception.code,400)
                    name='synthetic.wav'
                    with wave.open(str(root/'recordings'/name),'wb') as wav:
                        wav.setparams((1,2,16000,0,'NONE','none'));wav.writeframes(bytes(16000))
                    body=dict(file=name,start=0,end=.5,text='',labels=[],silence=True,reviewed=True)
                    with patch.object(server,'inactive'):
                        request=urllib.request.Request(url+'/review',data=json.dumps(body).encode(),headers={'Origin':url})
                        self.assertTrue(json.load(urllib.request.urlopen(request))['ok'])
                        clip=urllib.request.urlopen(url+'/clip?file='+name+'&start=0&end=0.5').read()
                        with wave.open(io.BytesIO(clip),'rb') as wav:self.assertEqual(wav.getnframes(),8000)
                    self.assertEqual(len(corpus.verified()),1)
                finally:app.shutdown();app.server_close();thread.join()

if __name__=='__main__':unittest.main()
