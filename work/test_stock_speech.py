import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path('outputs/recorder').resolve()))
from speech_gate import supported_words
class StockTest(unittest.TestCase):
 def item(self,p=.95):return {'text':'Спасибо.','words':[{'start':1.,'end':1.6,'probability':p}]}
 def test_unvoiced(self):self.assertFalse(supported_words(self.item(),[(.5,2)],[]))
 def test_uncertain(self):self.assertFalse(supported_words(self.item(.5),[(.5,2)],[(1,1.6)]))
 def test_real_thanks(self):self.assertTrue(supported_words(self.item(),[(.5,2)],[(1,1.6)]))
 def test_other_speech(self):self.assertTrue(supported_words({'text':'Даниил выступает.'},[(0,2)]))
 def test_low_confidence_words(self):self.assertFalse(supported_words({'text':'и','words':[{'probability':.04}]},[(0,2)]))
unittest.main()
