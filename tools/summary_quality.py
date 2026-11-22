"""Короткий отчёт поддержанности на сохранённых ответах. Модель здесь не запускается."""
import argparse
import hashlib
import json
from pathlib import Path

FIELDS=('summary','homework','formulas')
REVIEWS=('homework_review','formula_review')


def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def count(value,fields):return sum(len(value.get(field,[])) for field in fields if isinstance(value.get(field),list))


def build(raw,comparison,kind):
    if hashlib.sha256(raw).hexdigest()!=comparison['input_sha256']:raise ValueError('Сравниваются разные файлы ответов')
    data=json.loads(raw);cases=data['cases'] if isinstance(data,dict) else data
    if kind=='live' and (not isinstance(data,dict) or any(not c.get('attempts') for c in cases)):
        raise ValueError('Нет сохранённых генераций: фиксированный ответ нельзя объявить живым прогоном')
    if [c['name'] for c in cases]!=[c['name'] for c in comparison['cases']]:raise ValueError('Списки примеров различаются')
    report=dict(kind=kind,cases=len(cases),input_sha256=comparison['input_sha256'],
        definition='Подтверждено новым фильтром означает поддержку расшифровкой и его проверками; истинность слов лектора не установлена.',
        fixed_is_not_model='Фиксированные ловушки и искусственный выбор строк не являются ответами модели.',
        empty_model=0,empty_model_on_weak_input=0,excluded_aside_proposals=0,versions={},details=[],
        filter_files_sha256=comparison.get('filter_files_sha256',{}),revisions=comparison.get('revisions',{}))
    for case,compared in zip(cases,comparison['cases']):
        if digest(case['proposal'])!=compared['proposal_sha256']:raise ValueError('Ответ модели изменён после сравнения')
        proposal=case['proposal'];proposed=count(proposal,FIELDS)
        origin=case.get('origin') or {};origin=origin if isinstance(origin,dict) else {}
        no_speech=origin.get('subset')=='no_speech'
        weak=bool(origin.get('synthetic') or any(r.get('needs_review') for r in case.get('rows',[]))) and not no_speech
        report['empty_model']+=int(proposed==0)
        report['empty_model_on_weak_input']+=int(proposed==0 and weak)
        report['excluded_aside_proposals']+=len(proposal.get('excluded_asides',[]))
        detail=dict(name=case['name'],proposals=proposed,weak_input=weak,no_speech=no_speech,versions={})
        for version,results in compared['versions'].items():
            result=results['mac'];published=count(result,FIELDS);review=count(result,REVIEWS)
            discarded=proposed-published-review
            if discarded<0:raise ValueError('Число решений превышает число предложений')
            values=dict(published=published,review=review,discarded=discarded,
                        empty_after_filter=int(published==0),empty_on_weak_input=int(weak and published==0),
                        empty_no_speech=int(no_speech and published==0),applied_asides=len(result.get('excluded_asides',[])))
            detail['versions'][version]=values
            total=report['versions'].setdefault(version,{k:0 for k in values})
            for key,value in values.items():total[key]+=value
        report['details'].append(detail)
    current=report['versions'].get('рабочая_копия',{})
    report['current']=dict(confirmed=current.get('published',0),disputed=current.get('review',0),discarded=current.get('discarded',0))
    return report


def text(report):
    current=report['current'];label='живые ответы локальной модели' if report['kind']=='live' else 'фиксированные данные, без запуска модели'
    lines=[f"Вход: {label}. Примеров: {report['cases']}.",report['definition'],
        f"Новый фильтр: подтверждено {current['confirmed']}, спорно {current['disputed']}, отброшено {current['discarded']}.",
        f"Пустых ответов до фильтра: {report['empty_model']}; из них на отмеченном слабом/зашумлённом входе: {report['empty_model_on_weak_input']}."]
    for version,result in report['versions'].items():
        lines.append(f"{version}: выпущено {result['published']}, на сверку {result['review']}, отброшено {result['discarded']}; пусто после фильтра {result['empty_after_filter']}, на слабом входе {result['empty_on_weak_input']}.")
    lines.append(f"Попыток модели исключить фрагменты как посторонние: {report['excluded_aside_proposals']}; новым фильтром применено {report['versions'].get('рабочая_копия',{}).get('applied_asides',0)}. Правильность определения чужих реплик этим не доказана.")
    lines.append('Выпущенные старым фильтром элементы не названы подтверждёнными: среди них возможны прежние ошибки. Слабый/сомнительный вход — needs_review или зафиксированное добавление шума; в ловушках метка поставлена в тесте. Физическая громкость не измерялась.')
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path);parser.add_argument('comparison',type=Path)
    parser.add_argument('--kind',choices=['live','fixed'],required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=build(args.input.read_bytes(),json.loads(args.comparison.read_text()),args.kind)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    args.output.with_suffix('.txt').write_text(text(report),encoding='utf-8')
    print(text(report),end='')


if __name__=='__main__':main()
