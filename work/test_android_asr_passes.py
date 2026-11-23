"""Пустой/одиночный проход нельзя уточнить через соседний якорь."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from profile_android_asr import prepare_sources


class Tests(unittest.TestCase):
    def test_java_skip_is_equivalent_and_protected_words_stay(self):
        jdk_path = os.environ.get('CLIPMIC_ASR_JDK') or os.environ.get('JAVA_HOME')
        deps_path = os.environ.get('CLIPMIC_ASR_DEPS')
        if not jdk_path or not deps_path:
            self.skipTest('Для стенда нужны JAVA_HOME и CLIPMIC_ASR_DEPS с ort.jar и android-json.jar')
        jdk, deps = Path(jdk_path), Path(deps_path)
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'java';prepare_sources(ROOT,folder,False)
            (folder/'PassTests.java').write_text('''package ru.ilya.lecturerecorder;
import org.json.*;
public class PassTests {
 static JSONObject w(String s,double c)throws Exception{return new JSONObject().put("word",s).put("start",0).put("end",.2).put("conf",c);}
 public static void main(String[] args)throws Exception {
  float[] lookahead={0,0,1};
  assert PhoneSpeechWindow.constant(lookahead,2);
  assert !PhoneSpeechWindow.constant(lookahead,3);
  assert !PhoneGigaAm.shouldRefine(.001f,new JSONArray());
  assert !PhoneGigaAm.shouldRefine(.001f,new JSONArray().put(w("не",.1)));
  JSONArray clear=new JSONArray().put(w("пять",.99)).put(w("метров",.99));
  assert !PhoneGigaAm.shouldRefine(.1f,clear);
  assert PhoneGigaAm.shouldRefine(.01f,clear);
  assert PhoneGigaAm.shouldRefine(.1f,new JSONArray().put(w("тихо",.1)).put(w("слово",.99)));
  for(int i=0;i<100;i++) {
   JSONArray base=new JSONArray();if(i%2==0)base.put(w(i%3==0?"15":"не",.1));
   String before=base.toString();JSONArray other=new JSONArray().put(w("50",.99)).put(w("метров",.99));
   PhoneGigaAm.reconcile(base,other);assert before.equals(base.toString());
  }
  JSONArray base=new JSONArray().put(w("15",.1)).put(w("метров",.99));
  JSONArray other=new JSONArray().put(w("50",.99)).put(w("метров",.99));
  PhoneGigaAm.reconcile(base,other);assert base.getJSONObject(0).getString("word").equals("15");
  System.out.println("Одиночные проходы неизменны; числовая подмена запрещена");
 }
}''')
            cp=os.pathsep.join(map(str,[deps/'ort.jar',deps/'android-json.jar',folder]))
            subprocess.run([jdk/'bin/javac','--release','8','-encoding','UTF-8','-cp',cp,'-d',folder,*folder.glob('*.java')],check=True)
            subprocess.run([jdk/'bin/java','-ea','-cp',cp,'ru.ilya.lecturerecorder.PassTests'],check=True)


if __name__=='__main__':unittest.main()
