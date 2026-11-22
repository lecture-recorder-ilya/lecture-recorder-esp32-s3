"""Признаки выдачи ДЗ, а не вывод о личности говорящего по голосу."""
import re

AFTER=re.compile(r'домашн\w*\s+(?:задани|работ)|на дом\b|(?:на|к) следующ|после (?:пары|занятия|урока)')
ACTION=re.compile(r'\b(?:подготовьте|прочитайте|решите|выучите|изучите|сдайте|напишите|повторите|сделайте|выполните)\b|(?:нужно|надо|следует)\s+(?:будет\s+)?(?:решить|прочитать|подготовить|написать|сдать|выучить|сделать|выполнить)\b')
LABEL=re.compile(r'(?:^|[.!]\s+)(?:ваше\s+)?домашн\w*\s+(?:задани\w*|работ\w*)\s*[:—-]\s*(?:задач|пример|глав|параграф|упражнен)')
EXAMPLE=re.compile(r'например|допустим|в качестве примера|для примера|представьте|если бы|пример\s+(?:домашн|задани)')
CLARIFY=re.compile(r'я\s+(?:(?:правильно|верно)\s+)?понял|правильно\s+(?:я\s+)?понимаю|вы\s+(?:сказали|задали)|то есть\s+(?:нам|на дом)')
PERSONAL=re.compile(r'\b(?:мне|нам)\s+(?:надо|нужно)|\bя\s+(?:должен|должна)|в аудитории|(?:сосед|одногруппник|студент|кто-то|он|она)\b.{0,35}\b(?:сказал\w*|говорит|надо)')
LABELS={'question':'Это вопрос, выдача ДЗ не подтверждена.','example':'Это учебный пример, выдача ДЗ не подтверждена.',
        'clarification':'Это переспрос, выдачу ДЗ нужно сверить.','audience':'Это личная или чужая реплика, выдачу ДЗ нужно сверить.',
        'classwork':'Самостоятельная работа после занятия не подтверждена.','unsupported':'Формулировку ДЗ нужно сверить.'}


def classify(quote,roles=()):
    text=re.sub(r'\s+',' ',quote).strip().lower()
    if '?' in text:return 'question'
    if EXAMPLE.search(text):return 'example'
    if CLARIFY.search(text):return 'clarification'
    if PERSONAL.search(text) or any(role in ('student','audience') for role in roles):return 'audience'
    if not AFTER.search(text):return 'classwork'
    if not ACTION.search(text) and not LABEL.search(text):return 'unsupported'
    return 'assignment'
