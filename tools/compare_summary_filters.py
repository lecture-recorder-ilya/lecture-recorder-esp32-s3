"""Сравнить версии фильтров на одних сохранённых ответах, без запуска модели и ASR."""
import argparse
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'outputs/recorder'),str(ROOT/'work')]
import ai_worker
from test_phone_summary_state import JSON_SHA256

HARNESS = r'''package ru.ilya.lecturerecorder;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import org.json.*;
public final class EvidenceReplay {
 public static void main(String[] args) throws Exception {
  JSONArray cases=new JSONArray(new String(Files.readAllBytes(Paths.get(args[0])),StandardCharsets.UTF_8));
  JSONArray results=new JSONArray();
  for(int i=0;i<cases.length();i++) {
   JSONObject item=cases.getJSONObject(i);JSONArray rows=item.getJSONArray("rows");
   JSONArray points=new JSONArray(),sources=new JSONArray(),tasks=new JSONArray();
   PhoneSummaryEvidence.add(item.getString("android_response"),0,rows.length(),rows,
     points,sources,tasks,new HashSet<>(),new HashSet<>());
   results.put(new JSONObject().put("summary",points).put("summary_evidence",sources).put("homework",tasks));
  }
  System.out.println(results.toString());
 }
}'''


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def source(ref,path):
    return subprocess.check_output(['git','show',ref+':'+path],cwd=ROOT,text=True)


def mac(ref,items):
    if ref is None:return [ai_worker.validate_part(copy.deepcopy(c['proposal']),copy.deepcopy(c['rows'])) for c in items]
    # Старый модуль получает и старые зависимости, а не новые функции из sys.modules.
    with tempfile.TemporaryDirectory(prefix='summary-version-') as temp:
        root=Path(temp);payload=subprocess.check_output(['git','archive',ref,'outputs/recorder'],cwd=ROOT)
        with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
            for item in archive:
                parts=Path(item.name).parts
                if item.isfile() and Path(item.name).suffix in ('.py','.json') and parts[:2]==('outputs','recorder') and '..' not in parts:
                    path=root/item.name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(archive.extractfile(item).read())
        data=root/'inputs.json';data.write_text(json.dumps(items,ensure_ascii=False),encoding='utf-8')
        runner="import json,sys;sys.path.insert(0,sys.argv[1]);import ai_worker;items=json.load(open(sys.argv[2]));print(json.dumps([ai_worker.validate_part(c['proposal'],c['rows']) for c in items],ensure_ascii=False))"
        completed=subprocess.run([sys.executable,'-c',runner,root/'outputs/recorder',data],text=True,capture_output=True)
        if completed.returncode:raise RuntimeError(ref+': '+completed.stderr)
        return json.loads(completed.stdout)


def android(ref,items,jdk,jar):
    with tempfile.TemporaryDirectory(prefix='summary-replay-') as temp:
        root=Path(temp)
        (root/'PhoneSummaryEvidence.java').write_text(
            source(ref,'outputs/android/src/ru/ilya/lecturerecorder/PhoneSummaryEvidence.java') if ref else
            (ROOT/'outputs/android/src/ru/ilya/lecturerecorder/PhoneSummaryEvidence.java').read_text(),encoding='utf-8')
        (root/'EvidenceReplay.java').write_text(HARNESS,encoding='utf-8')
        current=ROOT/'outputs/android/src/ru/ilya/lecturerecorder/HomeworkEvidence.java'
        if ref:
            exists=subprocess.run(['git','cat-file','-e',ref+':outputs/android/src/ru/ilya/lecturerecorder/HomeworkEvidence.java'],cwd=ROOT,capture_output=True).returncode==0
            if exists:(root/'HomeworkEvidence.java').write_text(source(ref,'outputs/android/src/ru/ilya/lecturerecorder/HomeworkEvidence.java'),encoding='utf-8')
        elif current.exists():(root/'HomeworkEvidence.java').write_text(current.read_text(),encoding='utf-8')
        (root/'inputs.json').write_text(json.dumps(items,ensure_ascii=False),encoding='utf-8')
        subprocess.run([jdk/'bin/javac','--release','8','-encoding','UTF-8','-cp',jar,'-d',root,
                        *root.glob('*.java')],check=True,capture_output=True)
        result=subprocess.check_output([jdk/'bin/java','-cp',os.pathsep.join((str(root),str(jar))),
                                        'ru.ilya.lecturerecorder.EvidenceReplay',root/'inputs.json'],text=True)
        return json.loads(result)


def anchors_supported(result,rows,positional=False):
    for field in ('summary_evidence','homework','formulas'):
        for item in result.get(field,[]):
            found=False
            for first in range(len(rows)):
                for last in range(first,len(rows)):
                    span=rows[first:last+1]
                    if (item['quote']==' '.join(r['text'].strip() for r in span)
                        and item['start']==span[0]['start'] and item['end']==span[-1]['end']
                        and item['segment_id']==(first if positional else span[0]['id'])):
                        found=True
            if not found:return False
    return True


def mismatches(result,expected):
    failed=[]
    for field,value in expected.items():
        if field.endswith('_count'): actual=len(result.get(field.removesuffix('_count'),[]))
        elif field=='deadline': actual=(result.get('homework') or [{}])[0].get('deadline')
        else: actual=result.get(field)
        if actual!=value:failed.append(dict(field=field,expected=value,actual=actual))
    return failed


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path)
    parser.add_argument('--baseline',action='append',default=[])
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--java-home',type=Path,default=os.environ.get('JAVA_HOME'),required='JAVA_HOME' not in os.environ)
    parser.add_argument('--android-json-jar',type=Path,default=os.environ.get('ANDROID_JSON_JAR'),required='ANDROID_JSON_JAR' not in os.environ)
    args=parser.parse_args()
    if hashlib.sha256(args.android_json_jar.read_bytes()).hexdigest()!=JSON_SHA256:
        raise ValueError('Не совпала контрольная сумма библиотеки Android JSON')
    data=json.loads(args.input.read_text(encoding='utf-8'));items=data.get('cases',[]) if isinstance(data,dict) else data
    for item in items:
        if 'proposal' not in item:
            raise ValueError('Нужен сохранённый ответ в proposal, а не новый ответ модели')
        item['android_response_origin']='из файла' if 'android_response' in item else 'фиксированный выбор строк; Android-модель не запускалась'
        item.setdefault('android_response','KEY: '+','.join(str(i+1) for i in range(min(4,len(item['rows']))))+'\nTASK: ')
    versions=[*args.baseline,'рабочая_копия']
    report=dict(kind='повтор фиксированных ответов; модель и ASR не запускаются',
                input_sha256=hashlib.sha256(args.input.read_bytes()).hexdigest(),
                validator_sha256=hashlib.sha256(Path(ai_worker.__file__).read_bytes()).hexdigest(),
                revisions={ref:subprocess.check_output(['git','rev-parse',ref+'^{}'],cwd=ROOT,text=True).strip() for ref in args.baseline},cases=[])
    report['filter_files_sha256']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [ROOT/'outputs/recorder'/name for name in ('ai_worker.py','formula_evidence.py','homework_evidence.py','summary_sources.py','learning_moments.py')]
        +[ROOT/'outputs/android/src/ru/ilya/lecturerecorder'/name for name in ('PhoneSummaryEvidence.java','HomeworkEvidence.java')] if p.exists()}
    desktop={ref:mac(None if ref=='рабочая_копия' else ref,items) for ref in versions}
    phone={ref:android(None if ref=='рабочая_копия' else ref,items,args.java_home,args.android_json_jar) for ref in versions}
    for index,item in enumerate(items):
        entry=dict(name=item['name'],origin=item.get('origin'),proposal_sha256=digest(item['proposal']),
                   android_response_sha256=digest(item['android_response']),android_response_origin=item['android_response_origin'],versions={})
        for ref in versions:
            mac_result=desktop[ref][index]
            mobile=phone[ref][index]
            entry['versions'][ref]=dict(mac=mac_result,android=mobile,
                mac_anchors_supported=anchors_supported(mac_result,item['rows']),android_anchors_supported=anchors_supported(mobile,item['rows'],True),
                mac_mismatches=mismatches(mac_result,item.get('expected_mac',{})),
                android_mismatches=mismatches(mobile,item.get('expected_android',{})))
        report['cases'].append(entry)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f"Сверены Mac и Android JVM: {len(items)} фрагментов, {len(versions)} версии. {args.output}")
    if any(c['versions']['рабочая_копия']['mac_mismatches'] or c['versions']['рабочая_копия']['android_mismatches']
           for c in report['cases']):raise SystemExit('Ожидания рабочей копии не совпали; смотри отчёт')


if __name__=='__main__':main()
