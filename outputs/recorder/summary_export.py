"""Общие цитаты и точные временные границы для текстового экспорта."""
import math


def timecode(value):
    if type(value) not in (int,float) or not math.isfinite(value) or value<0:return 'без таймкода'
    millis=math.floor(value*1000+.5);seconds=millis//1000
    return f'{seconds//60}:{seconds%60:02d}.{millis%1000:03d}'


def source_lines(item):
    quote=item.get('quote','');lines=[]
    if 'start' in item and 'end' in item and item.get('source_status')!='needs_review':
        lines.append(f"Источник [{timecode(item['start'])}–{timecode(item['end'])}]: «{quote}»")
    elif quote:lines.append('Неподтверждённая цитата: «'+quote+'». Источник нужно сверить.')
    original=item.get('original_source') or {}
    if 'start' in original and 'end' in original and (original.get('start'),original.get('end'))!=(item.get('start'),item.get('end')):
        lines.append(f"Исходная привязка [{timecode(original['start'])}–{timecode(original['end'])}]; до повторной сверки.")
    return lines
