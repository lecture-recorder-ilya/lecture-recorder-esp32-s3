"""Preliminary teacher advice/organization with original words and anchors."""
import re
IMPORTANT=re.compile(r'при\s+(?:создании|подготовке|оформлении)\s+презентац|(?:в|для)\s+(?:вашей\s+|этой\s+)?презентац\w*[^.!?]{0,160}(?:нужно|надо|следует|долж|лучше)|(?:на|в)\s+слайд\w*[^.!?]{0,120}(?:нужно|надо|долж|лучше|не\s+пиш)|(?:нужно|надо|следует|долж\w*)[^.!?]{0,100}(?:презентац|слайд|источник|список литературы)|(?:будет|спрошу|вопрос)\s+на\s+(?:экзамен|зач[её]т)|(?:обязательно|важно)\s+(?:запис|запомн|указ|добав|сдат)|не\s+забуд\w*[^.!?]{0,80}(?:сдат|добав|указ|подпис)|домашн\w*\s+задани|к\s+следующ\w*\s+(?:пар|заняти)[^.!?]{0,100}(?:подготов|сдат|сдела)|обратите\s+внимание',re.I)
ORGANIZATION=re.compile(r'говори\w*\s+(?:громче|тише)|погромче|потише|не\s+шумите|(?:сядьте|садитесь|откройте окно|закройте окно)|провер\w*\s+(?:звук|микрофон)|переключ\w*\s+слайд',re.I)
SELF=re.compile(r'(?:в моей презентации|мне надо|я должен|я должна|я хочу)',re.I)

def remarks(segments,speaker_roles,existing=()):
 result=[];seen=set()
 for item in existing:
  if item.get('quote') and item.get('category') in ('important','other'):
   result.append(item);seen.add(item.get('segment_id'))
 for s in segments:
  if s['id'] in seen:continue
  text=s.get('text','');role=speaker_roles.get(str(s['id']),{}).get('role')
  category='important' if IMPORTANT.search(text) else 'other' if ORGANIZATION.search(text) else None
  if not category or SELF.search(text):continue
  # Short explicit classroom instructions may reveal a teacher intervention.
  if role=='student' and not (ORGANIZATION.search(text) or re.search(r'вашей|вашем|вам\s+нужно|обратите внимание',text,re.I)):continue
  result.append({'segment_id':s['id'],'segment_ids':[s['id']],'start':s['start'],'end':s['end'],'quote':text,'category':category,'estimated':True})
 return sorted(result,key=lambda r:r['start'])
