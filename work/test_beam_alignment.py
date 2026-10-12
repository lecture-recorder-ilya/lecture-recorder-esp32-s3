import unittest,numpy as np
from beam_quality_prototype import aligned_result
class AlignmentTests(unittest.TestCase):
 def test_repeated_letters_need_blank(self):
  labels=['','а','б',' '];target='ааб';p=np.full((8,4),-12,dtype=np.float32)
  for i,c in enumerate([0,1,0,1,0,2,0,0]):p[i,c]=-.01
  r=aligned_result(target,p,labels,0);self.assertEqual(r.tokens,list(target));self.assertEqual(r.timestamps,[.04,.12,.2]);self.assertTrue(all(v>-.1 for v in r.logprobs))
 def test_impossible_alignment_rejected(self):
  r=aligned_result('аа',np.zeros((1,2)),['','а'],0);self.assertEqual(r.tokens,[])
 def test_unknown_character_rejected(self):
  r=aligned_result('!',np.zeros((3,2)),['','а'],0);self.assertEqual(r.tokens,[])
 def test_empty_text_is_safe(self):
  self.assertEqual(aligned_result('',np.zeros((3,2)),['','а'],0).tokens,[])
if __name__=='__main__':unittest.main()
