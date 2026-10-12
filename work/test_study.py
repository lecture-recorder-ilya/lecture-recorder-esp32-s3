import importlib.util
import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outputs/recorder'))
import study_store as store
import study_service as service
import ai_worker as worker

class StudyTests(unittest.TestCase):
    def test_progressive_chronological_merge_keeps_chapters_and_sources(self):
        store.save(store.ROOT/'analysis'/(Path(self.first).stem+'.json'),{'topic':'Векторы','summary':['Сложение векторов']})
        pair=store.merged({'files':[self.second,self.first],'chronological':True},{})
        parts=store.notes(pair['file'])['parts']
        self.assertEqual([v['file'] for v in parts],[self.first,self.second])
        self.assertEqual(parts[0]['topic'],'Векторы')
        self.assertEqual(parts[0]['summary'],'Сложение векторов')
        store.marker({'file':pair['file'],'start':1.5,'title':'Добавлено после объединения'})
        third='lecture-2026-10-07-00-59-00-000001.wav'
        (store.ROOT/'recordings'/third).write_bytes(store.audio(self.first).read_bytes())
        joined=store.merged({'files':[pair['file'],third],'chronological':True},{})
        notes=store.notes(joined['file'])
        self.assertEqual([v['file'] for v in notes['parts']],[third,self.first,self.second])
        self.assertEqual([v['start'] for v in notes['parts']],[0,1,2])
        self.assertIn(pair['file'],notes['source_records'])
        self.assertEqual(notes['markers'][0]['title'],'Добавлено после объединения')
        self.assertEqual(notes['markers'][0]['start'],2.5)
        with self.assertRaises(ValueError):store.merged({'files':[joined['file'],self.first],'chronological':True},{})
    def test_model_json_invalid_latex_escapes(self):
        parsed=worker.parse_json(r'{"latex":"\alpha + \omega", "text":"строка\nдва"}')
        self.assertEqual(parsed['latex'],r'\alpha + \omega')
        self.assertEqual(parsed['text'],'строка\nдва')
        self.assertEqual(worker.parse_json(r'{"latex":"\\frac{a}{b}"}')['latex'],r'\frac{a}{b}')
        self.assertEqual(worker.parse_json(r'{"latex":"\frac{a}{b} + \beta"}')['latex'],r'\frac{a}{b} + \beta')
        with self.assertRaises(json.JSONDecodeError):worker.parse_json('{"x":')
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=store.ROOT;store.ROOT=Path(self.temp.name);service.ROOT=store.ROOT
        (store.ROOT/'recordings').mkdir();(store.ROOT/'analysis').mkdir()
        self.first='lecture-2026-10-07-01-00-00-000001.wav';self.second='lecture-2026-10-07-01-00-00-000002.wav'
        for name,sample in [(self.first,123),(self.second,456)]:
            with wave.open(str(store.ROOT/'recordings'/name),'wb') as out:
                out.setparams((1,2,16000,0,'NONE','none'));out.writeframes(sample.to_bytes(2,'little',signed=True)*16000)
            store.save(store.ROOT/'analysis'/(Path(name).stem+'.transcript.json'),{'complete':True,'segments':[{'id':0,'start':.1,'end':.9,'text':str(sample)}]})
    def tearDown(self):store.ROOT=self.old;service.ROOT=self.old;self.temp.cleanup()
    def test_merge_offsets_and_immutable_sources(self):
        originals=[store.audio(n).read_bytes() for n in (self.first,self.second)]
        store.marker({'file':self.second,'start':.5,'title':''});store.add_photo(self.second,.7,b'\xff\xd8\xfffixture')
        result=store.merged({'files':[self.first,self.second],'folder':'Тема занятия'},{'recording':False})
        with wave.open(str(store.audio(result['file']))) as audio:
            self.assertEqual(audio.getnframes(),32000);self.assertEqual(audio.readframes(32000),originals[0][44:]+originals[1][44:])
        self.assertEqual([store.audio(n).read_bytes() for n in (self.first,self.second)],originals)
        notes=store.notes(result['file']);self.assertEqual(notes['markers'][0]['start'],1.5);self.assertEqual(notes['photos'][0]['start'],1.7)
        transcript=store.read(store.ROOT/'analysis'/(Path(result['file']).stem+'.transcript.json'))
        self.assertEqual(transcript['segments'][1]['id'],1);self.assertEqual(transcript['segments'][1]['start'],1.1)
        with self.assertRaises(ValueError):store.merged({'files':[self.first,self.second]},{'recording':True,'file':self.first})
    def test_folder_move_and_marker_rename(self):
        store.move(self.first,'Первая папка');store.move(self.first,'Вторая папка')
        self.assertTrue(store.audio(self.first).exists());self.assertFalse((store.ROOT/'lessons/Первая папка'/self.first).exists())
        self.assertTrue((store.ROOT/'lessons/Вторая папка'/self.first).exists())
        data=store.marker({'file':self.first,'start':.4});item=data['markers'][0]
        store.marker({'file':self.first,'id':item['id'],'start':item['start'],'title':'Предел'})
        self.assertEqual(store.notes(self.first)['markers'][0]['title'],'Предел')
        for value in ('../bad','/bad','..','bad\\x'):
            with self.assertRaises(ValueError):store.move(self.first,value)
        with self.assertRaises(ValueError):store.marker({'file':self.first,'start':float('nan')})
        with self.assertRaises(ValueError):store.add_photo(self.first,0,b'<script>bad</script>')
    def test_growing_wav_read_does_not_depend_on_header(self):
        path=store.audio(self.first);raw=bytearray(path.read_bytes());raw[40:44]=(0).to_bytes(4,'little');path.write_bytes(raw)
        self.assertEqual(service.read_pcm(path,100,200),bytes(raw[244:444]))
        self.assertEqual(service.read_pcm(path,16000,17000),b'')
    def test_teacher_name_persists_once_and_schedule_wins(self):
        path=store.ROOT/'analysis'/(Path(self.first).stem+'.json')
        store.save(path,{'teacher':'Иван Иванович','evidence':{'teacher':'Иван Иванович, вопрос? Да, слушаю.'}})
        initial={'files':[self.first],'lessons':{self.first:{'folder':'Пара','teachers':[]}}}
        self.assertEqual(store.enrich(initial)['lessons'][self.first]['teacher'],'Иван Иванович')
        store.save(path,{'teacher':'Пётр Петрович','evidence':{'teacher':'Пётр Петрович'}})
        self.assertEqual(store.enrich({'files':[self.first],'lessons':{self.first:{'folder':'Пара','teachers':[]}}})['lessons'][self.first]['teacher'],'Иван Иванович')
        self.assertEqual(store.enrich({'files':[self.first],'lessons':{self.first:{'folder':'Пара','teacher':'Из расписания','teachers':[]}}})['lessons'][self.first]['teacher'],'Из расписания')
    def test_quotes_boundaries_duplicates_and_formula(self):
        segments=[{'id':0,'start':0,'end':2,'text':'Если человек умный,'},{'id':1,'start':2,'end':4,'text':'то он сначала проверит область определения.'},{'id':2,'start':4,'end':6,'text':'Сила равна массе, умноженной на ускорение.'}]
        item={'kind':'recommendation','cue':'Если человек умный','point':'Проверить область определения','quote':'Если человек умный, то он сначала проверит область определения.','segment_id':0}
        data=worker.validate_part({'highlights':[item,dict(item,quote='не сказано')],'formulas':[{'latex':'F=ma','quote':segments[2]['text'],'segment_id':2}]},segments)
        self.assertEqual(len(data['highlights']),1);self.assertEqual(data['highlights'][0]['end'],4)
        self.assertEqual(len(worker.merge_highlights([data,data])),1);self.assertEqual(data['formulas'][0]['latex'],'F=ma')
        self.assertIsNone(worker.highlight_anchor(dict(item,segment_id=True),{s['id']:s for s in segments}))

    def test_repetition_filter_preserves_normal_emphasis(self):
        from speech_quality import repetition, usable
        bad='Время, когда вы получите в результате, '+ 'то есть в результате, '*40
        self.assertTrue(repetition('Идем. Идем. Идем. Идем.'));self.assertTrue(repetition(bad));self.assertFalse(usable({'text':bad,'avg_logprob':-.1}))
        self.assertTrue(usable({'text':'Это важно, очень важно: сначала проверяйте область определения.'}))
        self.assertFalse(usable({'text':'Речь','compression_ratio':3}))

    def test_subtitle_credit_filter(self):
        from speech_quality import usable, clean_asr_text
        for text in ('Субтитры от Дани Узбека', 'Субтитры сделал DimaTorzok.', 'Субтитры создавал DimaTorzok'):
            self.assertFalse(usable({'text':text,'avg_logprob':-.1}))
        self.assertEqual(clean_asr_text('Это важная формула. Субтитры от Дани Узбека. Продолжим пример.'),'Это важная формула. Продолжим пример.')
        for text in ('На этом видео субтитры от студента.', 'Обсудим, как делать субтитры.', 'Субтитры сделал студент, но допустил ошибки.'):
            self.assertEqual(clean_asr_text(text),text)

    def test_photo_time_can_be_corrected(self):
        photo=store.add_photo(self.first,.7,b'\xff\xd8\xfffixture')['photos'][0]
        store.photo_time({'file':self.first,'id':photo['id'],'start':.2})
        self.assertEqual(store.notes(self.first)['photos'][0]['start'],.2)
        with self.assertRaises(ValueError):store.photo_time({'file':self.first,'id':photo['id'],'start':2})

if __name__=='__main__':unittest.main()
