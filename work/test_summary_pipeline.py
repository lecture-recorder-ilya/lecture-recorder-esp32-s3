import copy
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import wave
import numpy

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'outputs/recorder'))
import ai_worker
from learning_moments import moments_for_report
from summary_history import versions
from transcript_cache import checkpoint,identity
from transcript_quality import markdown,report_for
from phone_notes import documents


class PipelineTests(unittest.TestCase):
    quote='В 1380 году была Куликовская битва.'

    def row(self,**extra):return dict(id=0,start=1,end=4,text=self.quote,**extra)

    def proposal(self):
        return dict(summary=[dict(quote=self.quote,segment_id=0)],moments=[dict(
            kind='date',date='1380',title='Куликовская битва',description='Выдуманное объяснение.',
            quote=self.quote,segment_id=0,image_query='Куликовская битва')])

    def test_same_fixed_proposals_as_version_comparison(self):
        cases=json.loads((ROOT/'tests/fixtures/summary/release.json').read_text())
        for case in cases:
            with self.subTest(case=case['name']):
                result=ai_worker.validate_part(case['proposal'],case['rows'])
                for key,value in case['expected_mac'].items():
                    self.assertEqual(len(result[key.removesuffix('_count')]),value)

    def run_saved_transcript(self,root,rows,proposal):
        audio=root/'recordings/lecture-2026-11-23-100000.wav';audio.parent.mkdir(exist_ok=True)
        if not audio.exists():
            with wave.open(str(audio),'wb') as stream:
                stream.setparams((1,2,16000,0,'NONE','not compressed'));stream.writeframes(b'\0\0'*160000)
        target=root/'analysis'/audio.with_suffix('.json').name;target.parent.mkdir(exist_ok=True)
        expected=identity(audio,ai_worker.WHISPER_ENGINE)
        ai_worker.save(target.with_suffix('.transcript.json'),checkpoint(expected,rows,10,160000,complete=True))
        mx=types.ModuleType('mlx.core');mx.gpu=None;mx.clear_cache=lambda:None;mx.synchronize=lambda *_:None
        mlx=types.ModuleType('mlx');mlx.core=mx
        lm=types.ModuleType('mlx_lm');samplers=types.ModuleType('mlx_lm.sample_utils');samplers.make_sampler=lambda **_:None
        tokenizer=types.SimpleNamespace(apply_chat_template=lambda messages,**_:json.dumps(messages,ensure_ascii=False))
        lm.load=lambda _: (object(),tokenizer)
        def response(_model,_tokenizer,prompt,*_args,**_kwargs):
            messages=json.loads(prompt)
            if messages[0]['content']==ai_worker.SYSTEM:return json.dumps(proposal,ensure_ascii=False)
            return json.dumps(dict(topic='История',selected=[0]))
        def reviewed(segments,*_args):return copy.deepcopy(segments),dict(removed=[])
        with patch.dict(sys.modules,{'mlx':mlx,'mlx.core':mx,'mlx_lm':lm,'mlx_lm.sample_utils':samplers}), \
             patch.object(ai_worker,'review',side_effect=reviewed), \
             patch.object(ai_worker,'context_for_recording',return_value=dict(subject='История России')), \
             patch.object(ai_worker,'streamed_text',side_effect=response) as generator:
            ai_worker.run(audio,target,root/'progress.json')
        return target,json.loads(target.read_text()),generator.call_count

    def test_normal_phrase_keeps_quote_and_time_in_complete_run(self):
        with tempfile.TemporaryDirectory() as folder:
            target,result,_=self.run_saved_transcript(Path(folder),[self.row()],self.proposal())
            self.assertEqual(result['summary'],[self.quote])
            self.assertEqual(result['moments'][0]['quote'],self.quote)
            self.assertEqual((result['moments'][0]['start'],result['moments'][0]['end']),(1,4))
            self.assertNotIn('Выдуманное объяснение',target.with_suffix('.md').read_text())

    def test_same_response_cannot_publish_a_doubtful_phrase(self):
        with tempfile.TemporaryDirectory() as folder:
            _,result,_=self.run_saved_transcript(Path(folder),[self.row(needs_review=True)],self.proposal())
            self.assertEqual(result['summary'],[])
            self.assertEqual(result['moments'],[])
            self.assertEqual(result['segments'][0]['text'],self.quote)
            self.assertTrue(result['segments'][0]['needs_review'])

    def test_recalculation_invalidates_parts_and_preserves_previous_summary(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);target,old,_=self.run_saved_transcript(root,[self.row()],self.proposal())
            original=target.read_bytes()
            target,new,calls=self.run_saved_transcript(root,[self.row(needs_review=True)],self.proposal())
            self.assertEqual(calls,2)
            self.assertEqual(new['summary'],[]);self.assertEqual(new['moments'],[])
            archived=[target.parent/'history'/target.stem/(revision+'.json') for revision in versions(target)]
            self.assertIn(original,[path.read_bytes() for path in archived])
            row=dict(id=7,start=5,end=8,text=self.quote)
            proposal=self.proposal();proposal['summary'][0]['segment_id']=7;proposal['moments'][0]['segment_id']=7
            _,shifted,_=self.run_saved_transcript(root,[row],proposal)
            self.assertEqual(shifted['summary'],old['summary'])
            self.assertEqual(shifted['summary_evidence'][0]['segment_id'],7)
            self.assertEqual((shifted['moments'][0]['start'],shifted['moments'][0]['end']),(5,8))

    def test_old_moment_and_date_fallback_cannot_bypass_source_review(self):
        for quality in [dict(needs_review=True),dict(recognition=dict(uncertain=True))]:
            with self.subTest(quality=quality),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);(root/'analysis').mkdir()
                moment=dict(self.proposal()['moments'][0],start=1,end=4)
                report=dict(segments=[self.row(**quality)],moments=[moment],summary=[],duration=10)
                target=root/'analysis/lecture-2026-11-23-100000.json';ai_worker.save(target,report)
                self.assertEqual(moments_for_report(report,'История России'),[])
                self.assertEqual(report_for(root,target.stem+'.wav')['moments'],[])
                self.assertNotIn('## Даты и понятия',markdown(report))
                self.assertEqual(next(documents(root))[0]['report']['segments'][0]['text'],self.quote)


if __name__=='__main__':unittest.main()
