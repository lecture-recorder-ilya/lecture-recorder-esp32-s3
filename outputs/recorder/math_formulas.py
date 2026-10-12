"""Whole spoken expressions across adjacent excerpts, with source anchors."""
import copy
import hashlib
import re

def normalized(value):return re.sub(r'\s+',' ',value).strip().casefold().replace('ё','е')

def wanted(rows):
    text=normalized(' '.join(row.get('text','') for row in rows))
    cues=re.findall(r'предел|синус|косинус|тангенс|интеграл|производн|делен|дроб|плюс|минус|корень|квадрат|степен|равн|эквивалент|стрем',text)
    variable=bool(re.search(r'икс|игрек|альф|бет|\b[xyz]\b',text))
    return (len(set(cues))>=2 and bool(re.search(r'икс|игрек|альф|бет|\b[xyz]\b|\d|нул|нол|три|дв[аеу]|один',text))) or (variable and bool(re.search(r'равн|эквивалент',text)))

FUNCTIONS={'sin':'синус','cos':'косинус','tan':'тангенс','tg':'тангенс','cot':'котангенс',
           'lim':'предел','int':'интеграл','sqrt':'корень','log':'логарифм','ln':'логарифм',
           'alpha':'альф','beta':'бет','gamma':'гамм','pi':r'\bпи\b','infty':'бесконеч',
           'frac':'делен|дроб|частн|отношен|раздел|делим|делит',
           'sim':'эквивалент|приблиз|примерно','approx':'приблиз|примерно|эквивалент',
           'to':'стрем|предел|приближ','rightarrow':'стрем|предел|приближ'}
SAFE=set('begin end left right cdot times div over le ge leq geq neq pm mp lvert rvert vert displaystyle text operatorname quad qquad'.split())
NUMBER_WORDS={0:r'нул\w*|нол\w*',1:r'один|одна|одно|одну|единиц\w*|перв\w*',
              2:r'два|две|двух|двум\w*|втор\w*|квадрат\w*',3:r'три|трех|трем\w*|трет\w*|куб\w*|трикс',
              4:r'четыр\w*|четверт\w*',5:r'пять|пяти|пят\w*',6:r'шесть|шест\w*',
              7:r'семь|сем\w*|седьм\w*',8:r'восемь|восьм\w*',9:r'девять|девят\w*',
              10:r'десять|десят\w*',11:r'одиннадцат\w*',12:r'двенадцат\w*',
              13:r'тринадцат\w*',14:r'четырнадцат\w*',15:r'пятнадцат\w*',16:r'шестнадцат\w*',
              17:r'семнадцат\w*',18:r'восемнадцат\w*',19:r'девятнадцат\w*',
              20:r'двадцат\w*',30:r'тридцат\w*',40:r'сорок\w*',50:r'пятьдесят|пятидесят\w*',
              60:r'шестьдесят|шестидесят\w*',70:r'семьдесят|семидесят\w*',
              80:r'восемьдесят|восьмидесят\w*',90:r'девяност\w*',100:r'сто|сот\w*',1000:r'тысяч\w*'}

def supported_latex(latex,quote):
    if not isinstance(latex,str) or not 1<=len(latex)<=1600:return False
    if any(ord(c)<32 for c in latex) or re.search(r'\.\.\.|…|\\(?:ldots|cdots)|\?|неразбор|unknown',latex,re.I):return False
    depth=0
    for c in latex:
        if c=='{':depth+=1
        if c=='}':depth-=1
        if depth<0:return False
    if depth:return False
    if re.search(r'[=+\-*/^_]\s*$',latex):return False
    text=normalized(quote)
    if text.endswith('?') or not wanted([{'text':quote}]):return False
    commands=re.findall(r'\\([A-Za-z]+)',latex)
    if any(c not in FUNCTIONS and c not in SAFE for c in commands):return False
    if any(c in FUNCTIONS and not re.search(FUNCTIONS[c],text) for c in commands):return False
    if '=' in latex and not re.search(r'равн|получ|ответ|будет|это|итог',text):return False
    if '+' in latex and not re.search(r'плюс|слож|прибав|сумм',text):return False
    if '-' in latex and not re.search(r'минус|выч|отня',text):return False
    if '^' in latex and not re.search(r'степен|квадрат|куб|возвод',text):return False
    # A model cannot add a numerical answer absent from the spoken quotation.
    numbers=set(re.findall(r'\d+(?:[.,]\d+)?',text))
    numbers.update(str(n) for n,p in NUMBER_WORDS.items() if re.search(r'\b(?:'+p+r')\b',text))
    if any(n.replace(',','.') not in {v.replace(',','.') for v in numbers}
           for n in re.findall(r'\d+(?:[.,]\d+)?',latex)):return False
    # Variables must also occur in the quotation, literally or by spoken name.
    body=re.sub(r'\\(?:begin|end)\{[^{}]+\}','',latex)
    body=re.sub(r'\\[A-Za-z]+','',body)
    body=re.sub(r'\{(?:aligned|gathered|cases)\}','',body)
    spoken={'x':r'икс|трикс|\bx\b','y':r'игрек|\by\b','z':r'зет|зэт|\bz\b',
            'a':r'\b[аa]\b','b':r'\b[бb]\b','c':r'\b[сc]\b',
            'n':r'\bэн\b|\bn\b','t':r'\bтэ\b|\bt\b','f':r'функци|\bэф\b|\bf\b'}
    for letter in set(re.findall(r'[A-Za-z]',body)):
        if letter.casefold() not in spoken or not re.search(spoken[letter.casefold()],text):return False
    return True

def collect(value,answer):
    if not isinstance(answer,dict) or not isinstance(answer.get('formulas'),list):return []
    rows=value['rows'];output=[]
    for item in answer['formulas'][:3]:
        if not isinstance(item,dict) or item.get('complete') is not True:continue
        ids=item.get('rows');quote=item.get('quote');latex=item.get('latex')
        if isinstance(latex,str):latex=re.sub(r'\\\\(?=[A-Za-z])',lambda _: '\\',latex)
        if (not isinstance(ids,list) or not ids or any(type(i) is not int for i in ids)
                or ids!=list(range(ids[0],ids[-1]+1)) or ids[0]<0 or ids[-1]>=len(rows)
                or not isinstance(quote,str) or not quote.strip()):continue
        selected=[rows[i] for i in ids];source=normalized(' '.join(r['text'] for r in selected))
        if normalized(quote) not in source:continue
        if not supported_latex(latex,quote):
            # The model may quote only the expression/result and omit the preceding
            # spoken condition. Expand source anchors, never the expression itself.
            expanded=None
            for count in range(len(ids)+1,len(rows)+1):
                for left in range(max(0,ids[-1]-count+1),min(ids[0],len(rows)-count)+1):
                    span=rows[left:left+count]
                    full_quote=' '.join(r['text'] for r in span)
                    if supported_latex(latex,full_quote):
                        expanded=(list(range(left,left+count)),span,full_quote);break
                if expanded:break
            if not expanded:continue
            ids,selected,quote=expanded;source=normalized(quote)
        # A quoted span must include each claimed row; avoid misleading timestamps.
        position=source.find(normalized(quote));stop=position+len(normalized(quote))
        left=0;used=0
        for row in selected:
            right=left+len(normalized(row['text']))
            used+=int(min(right,stop)>max(left,position));left=right+1
        if used!=len(selected):continue
        start,end=selected[0]['start'],selected[-1]['end']
        key=hashlib.sha256((str(start)+'|'+latex).encode()).hexdigest()[:16]
        explanation=str(item.get('explanation',''))[:600]
        if normalized(explanation) not in normalized(quote):explanation=''
        output.append({'id':key,'latex':latex,'quote':quote,'start':start,'end':end,
                       'segment_id':selected[0].get('id',ids[0]),
                       'segment_ids':[r.get('id',i) for i,r in zip(ids,selected)],
                       'explanation':explanation,
                       'complete':True,'source':'spoken-context-4'})
    return output

def merge(existing,incoming):
    output=copy.deepcopy(existing)
    for item in incoming:
        duplicate=None
        for i,old in enumerate(output):
            overlap=min(old.get('end',old['start']+20),item['end'])-max(old['start'],item['start'])
            if overlap>0 and (normalized(old.get('quote','')) in normalized(item['quote'])
                              or old['latex'].replace(' ','')==item['latex'].replace(' ','')):
                duplicate=i;break
        if duplicate is None:output.append(copy.deepcopy(item))
        elif len(item['quote'])>=len(output[duplicate].get('quote','')):output[duplicate]=copy.deepcopy(item)
    return sorted(output,key=lambda v:v['start'])
