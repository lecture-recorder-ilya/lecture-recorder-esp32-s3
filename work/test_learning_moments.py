import sys,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path('outputs/recorder').resolve()))
import ai_worker as worker,illustrations
from learning_moments import date_supported,safe_image_query,moments_for_report
class MomentsTest(unittest.TestCase):
 def test_dates_need_quoted_support(self):
  self.assertTrue(date_supported('1380 год','В 1380 году была битва.'))
  self.assertFalse(date_supported('1382','В 1380 году была битва.'))
  self.assertFalse(date_supported('8 сентября 1380','В 1380 году была битва.'))
 def test_anchored_moment(self):
  segments=[dict(id=7,start=10,end=15,text='В 1380 году была Куликовская битва.')]
  moment=dict(kind='date',date='1380',title='Куликовская битва',description='Событие, названное преподавателем.',quote=segments[0]['text'],segment_id=7,image_query='Куликовская битва')
  valid=worker.validate_part({'moments':[moment]},segments)['moments'];self.assertEqual(valid[0]['start'],10)
  self.assertEqual(worker.validate_part({'moments':[dict(moment,date='1382')]},segments)['moments'],[])
  self.assertEqual(worker.validate_part({'moments':[dict(moment,quote='Это придумано')]},segments)['moments'],[])
 def test_existing_history_and_not_math(self):
  report={'segments':[dict(id=0,start=50,end=60,text='В 1380 году была Куликовская битва.')]}
  items=moments_for_report(report,'История России');self.assertEqual(items[0]['date'],'1380');self.assertEqual(items[0]['image_query'],'Куликовская битва')
  self.assertEqual(moments_for_report({'segments':[dict(id=0,start=0,end=1,text='В 1380 году родился автор')]},'Физика'),[])
 def test_only_anchored_public_queries(self):
  self.assertIsNone(safe_image_query('Имя преподавателя','Имя преподавателя'))
  self.assertIsNone(safe_image_query('https://site','https://site'))
  self.assertIsNone(safe_image_query('Личная тема','Куликовская битва'))
 def test_image_source_validation_and_license(self):
  page={'query':{'pages':[{'title':'Битва','pageimage':'Image.jpg','thumbnail':{'source':'https://evil.example/x'}}]}}
  with patch.object(illustrations,'wiki',return_value=page):self.assertEqual(illustrations.lookup('Тестовый объект')['status'],'unavailable')
  with tempfile.TemporaryDirectory() as d,patch.object(illustrations,'CACHE',Path(d)):
   page['query']['pages'][0]['thumbnail']['source']='https://upload.wikimedia.org/x.jpg'
   meta={'query':{'pages':[{'imageinfo':[{'extmetadata':{'LicenseShortName':{'value':'Public domain'},'Artist':{'value':'<b>Artist</b>'}}}]}]}}
   with patch.object(illustrations,'wiki',side_effect=[page,meta]) as request:
    result=illustrations.lookup('Тестовый объект');self.assertEqual(result['license'],'Public domain');self.assertEqual(result['author'],'Artist');self.assertTrue(result['source_url'].startswith('https://commons.wikimedia.org/'))
    self.assertEqual(illustrations.lookup('Тестовый объект'),result);self.assertEqual(request.call_count,2)
 def test_date_illustration_uses_named_event(self):
  report={'segments':[dict(id=0,start=10,end=20,text='В 1812 году началась Отечественная война.')]}
  self.assertEqual(moments_for_report(report,'История России')[0]['image_query'],'Отечественная война')
 def test_unknown_year_does_not_invent_image(self):
  report={'segments':[dict(id=0,start=0,end=5,text='В 1820 году произошло это событие.')]}
  self.assertIsNone(moments_for_report(report,'История России')[0]['image_query'])
unittest.main()
