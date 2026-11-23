import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from profile_android_asr import prepare_sources

JAVA='''package ru.ilya.lecturerecorder;
import java.util.*;
import java.lang.reflect.*;
import org.json.*;
public class EvidenceTests {
 static JSONObject word(String text,double conf,Double speech)throws Exception {
  JSONObject w=new JSONObject().put("word",text).put("start",1.2).put("end",1.4).put("conf",conf);
  if(speech!=null)w.put("speech_conf",speech);return w;
 }
 static JSONArray phrase(JSONObject second)throws Exception {
  PhonePhrases phrases=new PhonePhrases();JSONObject first=word("пример",.99,null).put("start",0).put("end",1);
  phrases.accept(new JSONArray().put(first).put(second));return phrases.finish();
 }
 public static void main(String[] args)throws Exception {
  if(args[0].equals("pieces")) {
   float[][] scores=new float[125][257];for(float[] row:scores)Arrays.fill(row,-20);
   int[] alignment=new int[125];Arrays.fill(alignment,256);alignment[1]=1;alignment[124]=2;
   scores[1][1]=(float)Math.log(.25);scores[124][2]=(float)Math.log(.95);
   String[] tokens=new String[257];Arrays.fill(tokens,"");tokens[1]="▁а";tokens[2]=".";
   Method method=PhoneGigaAm.class.getDeclaredMethod("words",float[][].class,int.class,String[].class,double.class,double.class,double.class,double.class,int[].class);
   method.setAccessible(true);JSONArray words=(JSONArray)method.invoke(null,scores,125,tokens,0.,0.,5.,5.,alignment);
   JSONObject w=words.getJSONObject(0);assert w.getString("word").equals("а.");
   assert Math.abs(w.getDouble("conf")-.6)<1e-6;assert Math.abs(w.getDouble("speech_conf")-.25)<1e-6;
  } else if(args[0].equals("flag")) {
   JSONObject old=word("а.",.6,null),aware=word("а.",.6,.25);
   JSONArray before=phrase(old),after=phrase(aware);
   assert !before.getJSONObject(0).getBoolean("needs_review");assert after.getJSONObject(0).getBoolean("needs_review");
   assert before.getJSONObject(0).getString("text").equals(after.getJSONObject(0).getString("text"));
  } else if(args[0].equals("preserve")) {
   assert phrase(word("не",.4,.99)).getJSONObject(0).getBoolean("needs_review");
   assert phrase(word("три",.99,null).put("needs_review",true)).getJSONObject(0).getBoolean("needs_review");
   assert !phrase(word("да.",.99,.99)).getJSONObject(0).getBoolean("needs_review");
  } else throw new IllegalArgumentException(args[0]);
 }
}'''


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        common=Path(subprocess.check_output(['git','rev-parse','--git-common-dir'],cwd=ROOT,text=True).strip())
        if not common.is_absolute():common=(ROOT/common).resolve()
        main=common.parent;cls.jdk=next((main.parent/'.build-tools/jdk').glob('*/Contents/Home'))
        tmp=tempfile.TemporaryDirectory();cls.addClassCleanup(tmp.cleanup)
        folder=Path(tmp.name)/'java';source=Path(os.environ.get('CLIPMIC_ASR_SOURCE_ROOT',ROOT)).resolve()
        prepare_sources(source,folder,False);(folder/'EvidenceTests.java').write_text(JAVA)
        deps=main/'work/lecture-profile-local-asr/asr-check'
        cls.cp=os.pathsep.join(map(str,[deps/'ort.jar',deps/'android-json.jar',folder]))
        subprocess.run([cls.jdk/'bin/javac','--release','8','-encoding','UTF-8','-cp',cls.cp,'-d',folder,*folder.glob('*.java')],check=True)

    def check(self,name):subprocess.run([self.jdk/'bin/java','-ea','-cp',self.cp,'ru.ilya.lecturerecorder.EvidenceTests',name],check=True)
    def test_punctuation_does_not_raise_speech_evidence(self):self.check('pieces')
    def test_weak_content_marks_the_existing_phrase(self):self.check('flag')
    def test_old_review_and_missing_metadata_keep_behavior(self):self.check('preserve')


if __name__=='__main__':unittest.main()
