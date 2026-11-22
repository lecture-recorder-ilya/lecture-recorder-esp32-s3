"""Сохранить живые ответы локальной модели для явно указанных расшифровок."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'outputs/recorder'))
import ai_worker


def fixtures():
    return [
        dict(name='homework_deadline', rows=[
            dict(id=0,start=0,end=3,text='Так, слышно? Микрофон проверяем.'),
            dict(id=1,start=4,end=9,text='На дом решите задачу 15. Сдайте примерно до пятницы.'),
            dict(id=2,start=10,end=14,text='Не к среде, к среде сдавать не надо.'),
        ]),
        dict(name='missing_condition_and_numbers', rows=[
            dict(id=0,start=0,end=3,text='то система не имеет единственного решения.'),
            dict(id=1,start=7,end=10,text='Если функция гладкая,',needs_review=True),
            dict(id=2,start=10,end=13,text='то существует производная.'),
            dict(id=3,start=14,end=18,text='Сопротивление равно не 15, а 150 ом.'),
            dict(id=4,start=19,end=23,text='Икс равен пяти или пятидесяти, не расслышал.',needs_review=True),
        ]),
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline', default='v0.5.9')
    parser.add_argument('--fixtures', type=Path, help='JSON с явно указанными источниками и строками после ASR')
    parser.add_argument('--without-throttle', action='store_true', help='Убрать паузы только в этом контрольном прогоне')
    args = parser.parse_args()
    from mlx_lm import load
    from mlx_lm.sample_utils import make_sampler
    import mlx.core as mx

    from compare_summary_filters import mac
    config = args.model / 'config.json'
    report = dict(kind='local_model_on_saved_transcript', model=str(args.model.resolve()),
                  config_sha256=hashlib.sha256(config.read_bytes()).hexdigest(),
                  validator_sha256=hashlib.sha256(Path(ai_worker.__file__).read_bytes()).hexdigest(),
                  baseline=args.baseline, temperature=0, max_tokens=2800, cases=[])
    report['test_without_throttle']=args.without_throttle
    report['system_sha256']=hashlib.sha256(ai_worker.SYSTEM.encode('utf-8')).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    print('Загружаю локальную модель конспекта',flush=True)
    model, tokenizer = load(str(args.model))
    mx.random.seed(0)
    inputs = json.loads(args.fixtures.read_text(encoding='utf-8')) if args.fixtures else fixtures()
    report['fixtures'] = str(args.fixtures.resolve()) if args.fixtures else 'встроенные искусственные фрагменты'
    for fixture in inputs:
        print(f"{fixture['name']}: генерирую",flush=True)
        started = time.monotonic()
        rows = [dict(needs_review=False, **row) if 'needs_review' not in row else row for row in fixture['rows']]
        messages = [dict(role='system',content=ai_worker.SYSTEM),
                    dict(role='user',content='Предмет по расписанию (контекст, не доказательство): None\nРасшифровка:\n'
                         + json.dumps(rows,ensure_ascii=False))]
        trace = dict(name=fixture['name'], rows=rows, origin=fixture.get('origin','искусственная расшифровка'), attempts=[])
        for attempt in range(2):
            prompt = tokenizer.apply_chat_template(messages,tokenize=False,add_generation_prompt=True)
            budget=ai_worker.Budget(enabled=lambda:False) if args.without_throttle else None
            raw = ai_worker.streamed_text(model,tokenizer,prompt,2800,make_sampler(temp=0),budget=budget)
            trace['attempts'].append(raw)
            try:
                proposal = ai_worker.parse_json(raw)
                trace.update(proposal=proposal, before=mac(args.baseline,[dict(proposal=proposal,rows=rows)])[0],
                             after=ai_worker.validate_part(proposal,rows))
                break
            except (ValueError,json.JSONDecodeError) as error:
                trace['parse_error'] = str(error)
                messages += [dict(role='assistant',content=raw),dict(role='user',content='Верни результат ещё раз только как валидный JSON указанной схемы.')]
        trace['seconds'] = round(time.monotonic()-started,1)
        report['cases'].append(trace)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(f"{fixture['name']}: {trace['seconds']}s, parsed={'proposal' in trace}",flush=True)
    print(args.output.resolve(),flush=True)


if __name__ == '__main__':
    main()
