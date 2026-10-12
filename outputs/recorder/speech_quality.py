"""Reject decoder repetition and low-confidence noise; keep source audio intact."""
import re
from collections import Counter

def repetition(text):
    words=re.findall(r'\w+',text.casefold())
    if len(words)>=4:
        count=max(Counter(words).values())
        if count>=4 and count/len(words)>=.5:return True
    if len(words)<20:return False
    for width,limit in ((3,5),(5,4),(8,3)):
        counts=Counter(tuple(words[i:i+width]) for i in range(len(words)-width+1))
        if counts and max(counts.values())>=limit:return True
    return False

def subtitle_credit(text):
    return bool(re.fullmatch(r'\s*субтитры\s+(?:от|сделал[аи]?|делал[аи]?|создавал[аи]?|создал[аи]?|подготовил[аи]?|подогнал[аи]?)\s+[\w@-]+(?:[ \t]+[\w@-]+){0,3}[.!…]*\s*',text,re.IGNORECASE))

def decoder_boilerplate(text):
    return bool(re.fullmatch(r'\s*(?:продолжение следует|лекция|предмет|подписывайтесь|подписывающиеся|подписывающие(?:ся|сь))(?:\s+на\s+канал)?[.!…]*\s*',text,re.IGNORECASE))

def clean_asr_text(text):
    clauses=re.split(r'(?<=[.!?])\s+|\n+',text.strip())
    return ' '.join(clause for clause in clauses if not subtitle_credit(clause) and not decoder_boilerplate(clause)).strip()

def usable(segment):
    text=clean_asr_text(segment.get('text',''))
    return bool(re.search(r'[^\W_]',text)) and not repetition(text) and segment.get('compression_ratio',0)<=2.4 and segment.get('no_speech_prob',0)<=.8 and segment.get('avg_logprob',0)>=-1.2
