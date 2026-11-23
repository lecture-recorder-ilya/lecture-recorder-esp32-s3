import copy
import re
from math_formulas import NUMBER_WORDS,FUNCTIONS,SAFE

REASONS={
 'syntax':'не удалось подтвердить запись выражения', 'number':'числа или их порядок не совпадают с фразой',
 'minus':'минус не совпадает с фразой', 'index':'индекс не подтверждён фразой',
 'power':'степень не подтверждена фразой', 'comparison':'знак сравнения не совпадает с фразой',
 'fraction':'дробь не совпадает с фразой', 'units':'единицы измерения не совпадают с фразой',
 'variable':'обозначения или их порядок не подтверждены фразой', 'source':'источник требует проверки',
 'incomplete':'условие или выражение не закончено', 'ambiguous':'в произнесённой формуле есть неоднозначность',
}

UNITS=[('cm',r'сантиметр(?:а|ов|е|ом|ы|ам|ами|ах)?'),('mm',r'миллиметр(?:а|ов|е|ом|ы|ам|ами|ах)?'),
 ('km',r'километр(?:а|ов|е|ом|ы|ам|ами|ах)?'),('m',r'метр(?:а|ов|е|ом|ы|ам|ами|ах)?'),
 ('kg',r'килограмм(?:а|ов|ы|ами|ах)?'),('g',r'грамм(?:а|ов|ы|ами|ах)?'),
 ('s',r'секунд(?:а|ы|у|е|ой|ами|ах)?'),('min',r'минут(?:а|ы|у|е|ой|ами|ах)?'),('h',r'час(?:а|ов|ы)?'),
 ('V',r'вольт(?:а|ов|ы|ам|ами|ах|е|у|ом)?'),('A',r'ампер(?:а|ов|ы|ам|ами|ах|е|у|ом)?'),('Ohm',r'ом(?:а|ов|ы|ам|ами|ах|е|у|ом)?'),
 ('N',r'ньютон(?:а|ов|ы|ам|ами|ах|е|у|ом)?'),('J',r'джоул(?:ь|я|ей|и|ям|ями|ю|ем)'),('W',r'ватт(?:а|ов|ы|ам|ами|ах|е|у|ом)?'),('Hz',r'герц(?:а|ов|ы|ам|ами|ах|е|у|ом)?')]
ALIASES={'см':'cm','cm':'cm','мм':'mm','mm':'mm','км':'km','km':'km','м':'m','m':'m',
 'кг':'kg','kg':'kg','г':'g','g':'g','с':'s','s':'s','сек':'s','мин':'min','min':'min','ч':'h','h':'h',
 'В':'V','V':'V','А':'A','A':'A','Ом':'Ohm','Ohm':'Ohm','Ω':'Ohm','Н':'N','N':'N','Дж':'J','J':'J',
 'Вт':'W','W':'W','Гц':'Hz','Hz':'Hz'}
VARIABLES={'x':r'икс|трикс|x','y':r'игрек|y','z':r'зет|зэт|z','a':r'ускорен\w*|а|a',
 'b':r'бэ|b','c':r'цэ|c','n':r'эн|n','t':r'врем\w*|тэ|t','f':r'эф|f','F':r'сил(?:а|ы|у|ой|е)',
 'm':r'масс(?:а|ы|у|ой|е)|эм|m','R':r'сопротивлен\w*','U':r'напряжен\w*','I':r'ток(?:а|у|ом|е)?',
 'E':r'энерг\w*','v':r'скорост\w*','s':r'пут(?:ь|и|ем)|расстоян\w*','p':r'давлен\w*',
 'V':r'объем\w*','l':r'длин(?:а|ы|у|ой|е)','h':r'высот\w*','S':r'площад\w*'}


def ordered(text,patterns):
    hits=[]
    for value,pattern in patterns.items():
        hits.extend((m.start(),m.end(),value) for m in re.finditer(r'(?<!\w)(?:'+pattern+r')(?!\w)',text))
    chosen=[];end=-1
    for first,last,value in sorted(hits,key=lambda x:(x[0],-x[1])):
        if first>=end:chosen.append(value);end=last
    return chosen


def number_patterns(text):
    patterns={str(n):p for n,p in NUMBER_WORDS.items()}
    endings=r'(?:ый|ой|ая|ое|ые|ого|ому|ым|ую|ых|ыми|ом)'
    for n,cardinal,stem in [(5,r'пять|пяти|пятью','пят'),(6,r'шесть|шести|шестью','шест'),
                           (7,r'семь|семи|семью','седьм'),(8,r'восемь|восьми|восемью','восьм'),(9,r'девять|девяти|девятью','девят')]:
        patterns[str(n)]=cardinal+'|'+stem+endings
    for value in re.findall(r'\d+(?:[.,]\d+)?',text):patterns[value.replace(',','.')]=re.escape(value)
    return patterns


def numbers(text):return ordered(text,number_patterns(text))


def units(text,latex):
    expected=[];spans=[]
    for unit,pattern in UNITS:
        for match in re.finditer(r'\b'+pattern+r'\b',text):
            prefix=text[:match.start()];power=1;first=match.start()
            squared=re.search(r'(квадратн\w*|кубическ\w*)\s*$',prefix)
            if squared:power=2 if squared.group(1).startswith('квадрат') else 3;first=squared.start()
            if re.search(r'\b(?:в|на|за)\s*$',text[:first]):power=-power
            expected.append((match.start(),unit,power));spans.append((first,match.end()))
    expected=[(u,p) for _,u,p in sorted(expected)];observed=[];invalid=False
    def read_unit(match):
        nonlocal invalid
        value=match.group(1).replace(r'\Omega','Ω').replace('{','').replace('}','')
        value=re.sub(r'\\(?:cdot|times)|\\[,!; ]',' ',value);denominator=False;parts=[];offset=0
        codes='|'.join(re.escape(k) for k in sorted(ALIASES,key=len,reverse=True))
        for item in re.finditer(r'(?<![A-Za-zА-Яа-я])('+codes+r')(?![A-Za-zА-Яа-я])(?:\^(-?\d+))?',value):
            gap=value[offset:item.start()]
            if '/' in gap:denominator=True
            if re.sub(r'[ /.*]','',gap):invalid=True
            parts.append((ALIASES[item.group(1)],int(item.group(2) or 1)*(-1 if denominator else 1)));offset=item.end()
        if not parts or value[offset:].strip():invalid=True
        observed.extend(parts);return ''
    body=re.sub(r'\\(?:mathrm|text)\{((?:[^{}]|\{[^{}]*\})*)\}',read_unit,latex.replace(r'\Omega',r'\mathrm{Ω}'))
    if expected and not observed:
        plain=re.search(r'(?<=\d)\s*([A-Za-zА-Яа-яΩ]+(?:\^-?\d+)?(?:/[A-Za-zА-Яа-яΩ]+(?:\^-?\d+)?)*)\s*$',body)
        if plain:body=body[:plain.start()]+read_unit(plain)
    spoken=text
    for first,last in sorted(spans,reverse=True):spoken=spoken[:first]+' '+spoken[last:]
    return expected==observed and not invalid,spoken,body


COMPARE=re.compile(r'не\s+больш\w*|не\s+меньш\w*|больш\w*\s+или\s+рав\w*|меньш\w*\s+или\s+рав\w*|не\s+рав\w*|эквивалент\w*|(?:примерно|приблизительно)\s+рав\w*|больш\w*|меньш\w*|\bрав(?:ен|на|но|ны|няется)\b')


def comparison_word(word):
    if word.startswith('не больш') or word.startswith('меньш') and 'или' in word:return 'le'
    if word.startswith('не меньш') or word.startswith('больш') and 'или' in word:return 'ge'
    if word.startswith('не рав'):return 'ne'
    if word.startswith('больш'):return 'gt'
    if word.startswith('меньш'):return 'lt'
    if word.startswith('эквивалент'):return 'sim'
    if word.startswith(('примерно','приблизительно')):return 'approx'
    return 'eq'


def check(latex,quote):
    if not isinstance(latex,str) or not 1<=len(latex)<=1500 or any(ord(c)<32 for c in latex):return False,'syntax'
    text=re.sub(r'\s+',' ',quote.lower().replace('ё','е')).strip();depth=0
    for c in latex:
        depth+=(c=='{')-(c=='}')
        if depth<0:return False,'syntax'
    if depth or re.search(r'[=+*/^_-]\s*$|\.\.\.|…|\?',latex):return False,'syntax'
    if re.search(r'неразбор|не расслыш|\bили\b(?!\s+рав)',text):return False,'ambiguous'
    if re.search(r'\b(?:равен|равна|равно|плюс|минус|деленное на)[ .,…]*$',text):return False,'incomplete'
    supported,spoken,body=units(text,latex)
    if not supported:return False,'units'
    if numbers(spoken)!=[v.replace(',','.') for v in re.findall(r'\d+(?:[.,]\d+)?',body)]:return False,'number'
    actual=[]
    codes={'=':'eq','<':'lt','>':'gt','!=':'ne','<=':'le','>=':'ge','≠':'ne','≤':'le','≥':'ge',r'\ne':'ne',r'\neq':'ne',r'\le':'le',r'\leq':'le',r'\ge':'ge',r'\geq':'ge',r'\sim':'sim',r'\approx':'approx'}
    for m in re.finditer(r'\\(?:neq|ne|leq|le|geq|ge|approx|sim)\b|<=|>=|!=|[=<>≠≤≥]',body):actual.append(codes[m.group()])
    if [comparison_word(m.group()) for m in COMPARE.finditer(spoken)]!=actual:return False,'comparison'
    if len(re.findall(r'\bминус\b|\bотрицательн\w*',spoken))!=body.count('-'):return False,'minus'
    index_count=len(re.findall(r'(?<![A-Za-z])(?:[A-Za-z]|\\(?:alpha|beta|gamma))_',body))
    if len(re.findall(r'индекс\w*|подстрочн\w*',spoken))!=index_count:return False,'index'
    if len(re.findall(r'степен\w*|\bквадрат\w*|\bкуб\w*',spoken))!=body.count('^'):return False,'power'
    divisions=len(re.findall(r'делен\w*|делим|делить|раздел\w*|отношен\w*',spoken))
    if not divisions and 'дроб' in spoken:divisions=1
    if divisions!=len(re.findall(r'\\frac\b|/',body)):return False,'fraction'
    if len(re.findall(r'\bплюс\b',spoken))!=body.count('+'):return False,'syntax'
    commands=re.findall(r'\\([A-Za-z]+)',body)
    if any(c not in FUNCTIONS and c not in SAFE and c!='ne' for c in commands):return False,'syntax'
    if any(c in FUNCTIONS and not re.search(FUNCTIONS[c],spoken) for c in commands):return False,'syntax'
    stripped=re.sub(r'\\[A-Za-z]+','',body)
    if ordered(spoken,VARIABLES)!=re.findall(r'[A-Za-z]',stripped):return False,'variable'
    operands={('number',key):value for key,value in number_patterns(spoken).items()}
    operands.update({('variable',key):value for key,value in VARIABLES.items()})
    actual_operands=[('variable',token) if re.fullmatch(r'[A-Za-z]',token) else ('number',token.replace(',','.'))
                     for token in re.findall(r'[A-Za-z]|\d+(?:[.,]\d+)?',stripped)]
    if ordered(spoken,operands)!=actual_operands:return False,'fraction'
    return True,''


def review(item,code):
    result=copy.deepcopy(item)
    result['candidate_latex']=result.pop('latex','')
    result.update(verification_status='needs_review',review_reason=code,
                  review_note='Формулу нужно сверить: '+REASONS.get(code,REASONS['syntax'])+'.')
    return result


def finalize(report):
    from summary_sources import matches
    result=copy.deepcopy(report);accepted=[];pending=result.get('formula_review',[])
    for item in result.get('formulas',[]):
        spans=matches(item.get('quote',''),result.get('segments',[]))
        code='source'
        valid=False
        if len(spans)==1 and not any(r.get('needs_review') and not r.get('reviewed') for r in spans[0][1]):
            valid,code=check(item.get('latex',''),item['quote'])
        if valid:
            item['verification_status']='confirmed'
            explanation=str(item.get('explanation',''))
            if explanation.strip().lower() not in item['quote'].lower():item['explanation']=''
            accepted.append(item)
        else:pending.append(review(item,code))
    result['formulas']=accepted
    result['formula_review']=list({(v['quote'],v.get('candidate_latex'),v.get('review_reason')):v for v in pending}.values())
    if result['formula_review']:
        warnings=[v for v in result.get('warnings',[]) if not v.startswith('Формул для проверки:')]
        warnings.append(f"Формул для проверки: {len(result['formula_review'])}. Цитаты сохранены в конспекте.")
        result['warnings']=warnings
    return result
