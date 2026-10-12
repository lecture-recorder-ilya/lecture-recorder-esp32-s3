"""Lesson metadata and optional user-supplied spelling hints for ASR."""
import json
import re
from pathlib import Path
import lesson_schedule

ROOT=Path(__file__).resolve().parent

def read(path):
 try:return json.loads(path.read_text())
 except (OSError,ValueError):return {}

def context_for_recording(name,offset=0,root=None,_depth=0):
 root=Path(root) if root else ROOT
 meta=read(root/'study/folders.json').get(name) or lesson_schedule.metadata(name) or {}
 # A combined track may contain different lessons. Use the source at this timestamp.
 parts=read(root/'study'/(Path(name).stem+'.notes.json')).get('parts',[])
 if parts and _depth<4:
  part=next((p for p in parts if p.get('start',0)<=offset<p.get('start',0)+p.get('duration',0)),None)
  if part and part.get('file')!=name:
   return context_for_recording(part['file'],offset-part['start'],root,_depth+1)
 subject=meta.get('subject')
 # Only explicit user spellings, never generated lesson prose or invented names.
 terms=read(root/'study'/(Path(name).stem+'.notes.json')).get('asr_terms','')
 prompt=normalize_terms(terms) if isinstance(terms,str) else ''
 return {'subject':subject,'prompt':prompt or None}

def normalize_terms(value):
 if not isinstance(value,str) or len(value)>300:raise ValueError("Не больше 300 символов")
 terms=[v.strip() for v in re.split(r"[,;\n]+",value) if v.strip()]
 if any(not re.fullmatch(r"[\w -]{1,60}",v) for v in terms):raise ValueError("Укажи фамилии или термины через запятую, без предложений")
 return ", ".join(dict.fromkeys(terms))
