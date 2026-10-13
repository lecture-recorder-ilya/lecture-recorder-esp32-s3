"""Reviewed local examples, immutable audio extracts and recording-level splits."""
import contextlib
import fcntl
import hashlib
import io
import json
import math
import os
import threading
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path

LABELS = ('summary','homework','formula','subject','teacher')
LOCK = threading.RLock()

class Corpus:
    def __init__(self, recorder, root):
        self.recorder, self.root = Path(recorder), Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.index = self.root/'examples.json'
    @contextlib.contextmanager
    def transaction(self):
        with LOCK, (self.root/'corpus.lock').open('a') as file:
            fcntl.flock(file, fcntl.LOCK_EX)
            try:yield
            finally:fcntl.flock(file, fcntl.LOCK_UN)
    def rows(self):
        if not self.index.exists():return []
        return json.loads(self.index.read_text())
    def save(self, path, value):
        temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
        with temporary.open('x', encoding='utf-8') as out:
            os.chmod(temporary, 0o600)
            json.dump(value, out, ensure_ascii=False, indent=2)
            out.flush();os.fsync(out.fileno())
        os.replace(temporary, path)
    def source(self, name):
        if not isinstance(name,str) or Path(name).name!=name or any(c in name for c in '/\\\0') or not name.endswith('.wav'):
            raise ValueError('Некорректное имя записи')
        path = self.recorder/'recordings'/name
        if path.is_symlink() or not path.is_file():raise ValueError('Запись не найдена')
        return path
    def clip(self, name, start, end):
        if isinstance(start,bool) or isinstance(end,bool):raise ValueError('Некорректное время')
        start,end = float(start),float(end)
        if not all(math.isfinite(v) for v in (start,end)) or start<0:
            raise ValueError('Выбери фрагмент от 0,5 до 20 секунд')
        first,last=round(start*16000),round(end*16000)
        if not 8000<=last-first<=320000:raise ValueError('Выбери фрагмент от 0,5 до 20 секунд')
        with wave.open(str(self.source(name)),'rb') as source:
            if (source.getnchannels(),source.getsampwidth(),source.getframerate())!=(1,2,16000):
                raise ValueError('Нужна запись PCM16, моно, 16 кГц')
            if last>source.getnframes():raise ValueError('Фрагмент выходит за пределы записи')
            source.setpos(first);raw=source.readframes(last-first)
        if len(raw)!=(last-first)*2:raise ValueError('Запись изменилась во время чтения')
        output=io.BytesIO()
        with wave.open(output,'wb') as target:
            target.setparams((1,2,16000,0,'NONE','not compressed'));target.writeframes(raw)
        return output.getvalue()
    def groups(self):
        """Merged lectures and their original parts must stay in the same split."""
        parent = {}
        def find(name):
            parent.setdefault(name,name)
            if parent[name]!=name:parent[name]=find(parent[name])
            return parent[name]
        for path in (self.recorder/'study').glob('*.notes.json'):
            value=json.loads(path.read_text())
            name=path.name.removesuffix('.notes.json')+'.wav'
            for part in value.get('parts',[]):
                other=part.get('file')
                if isinstance(other,str):
                    a,b=find(name),find(other)
                    parent[max(a,b)]=min(a,b)
        for path in (self.recorder/'lessons').glob('*/занятие.json'):
            names=json.loads(path.read_text()).get('recordings',[])
            for name in names[1:]:
                a,b=find(names[0]),find(name)
                parent[max(a,b)]=min(a,b)
        return {name:find(name) for name in parent}
    def review(self, body):
        if body.get('reviewed') is not True:raise ValueError('Подтверди проверку по аудио')
        text=body.get('text')
        labels=body.get('labels')
        silence=body.get('silence')
        if not isinstance(text,str) or len(text)>2000 or len(text.encode())>4096:
            raise ValueError('Некорректный текст')
        if not isinstance(labels,list) or any(tag not in LABELS for tag in labels):raise ValueError('Некорректные отметки')
        if not isinstance(silence,bool) or (silence and (text.strip() or labels)) or (not silence and not text.strip()):
            raise ValueError('Для тишины оставь текст пустым; для речи введи правильный текст')
        name=body.get('file');start,end=body.get('start'),body.get('end')
        clip=self.clip(name,start,end)
        # Neither an automatic transcript nor model output is accepted as a reviewed label implicitly.
        key=hashlib.sha256(f'{name}:{round(float(start)*16000)}:{round(float(end)*16000)}'.encode()).hexdigest()
        path=self.root/(key+'.wav')
        with self.transaction():
            if not path.exists():
                with path.open('xb') as out:
                    os.chmod(path,0o600);out.write(clip);out.flush();os.fsync(out.fileno())
            elif path.read_bytes()!=clip:raise ValueError('Исходный звук изменился; пример не перезаписан')
            row=dict(id=key,file=name,start=float(start),end=float(end),text=text.strip(),labels=sorted(set(labels)),
                     silence=silence,reviewed=True,sha256=hashlib.sha256(clip).hexdigest(),
                     reviewed_at=datetime.now(timezone.utc).isoformat())
            rows=[r for r in self.rows() if r['id']!=key]+[row]
            self.save(self.index,rows)
        return row
    def verified(self):
        rows=self.rows()
        for row in rows:
            if row.get('reviewed') is not True:raise ValueError('Есть непроверенные примеры')
            path=self.root/(row['id']+'.wav')
            if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:
                raise ValueError('Контрольная сумма учебного аудио не совпала')
        return rows
    def split(self, rows):
        aliases=self.groups()
        group=lambda row:aliases.get(row['file'],row['file'])
        groups=sorted({group(row) for row in rows},key=lambda name:hashlib.sha256(name.encode()).hexdigest())
        if len(groups)<3:raise ValueError('Нужны проверенные примеры минимум из трёх разных занятий')
        holdout=set(groups[:max(1,len(groups)//5)])
        return [r for r in rows if group(r) not in holdout],[r for r in rows if group(r) in holdout]
    def status(self):
        rows=self.rows()
        aliases=self.groups()
        trained=[]
        for path in (self.root/'runs').glob('*/manifest.json'):
            value=json.loads(path.read_text())
            if value.get('completed'):trained.append(value['task'])
        return dict(examples=len(rows),speech=sum(not r['silence'] for r in rows),silence=sum(r['silence'] for r in rows),
                    seconds=round(sum(r['end']-r['start'] for r in rows),1),
                    records=len({r['file'] for r in rows}),groups=len({aliases.get(r['file'],r['file']) for r in rows}),
                    labels={tag:sum(tag in r['labels'] for r in rows) for tag in LABELS},
                    trained_models=sorted(set(trained)),trained=bool(trained),production_ready=False)
    def recordings(self):
        result=[]
        for path in sorted((self.recorder/'recordings').glob('*.wav'),reverse=True):
            try:
                with wave.open(str(path),'rb') as source:
                    result.append(dict(file=path.name,seconds=source.getnframes()/source.getframerate()))
            except (OSError,wave.Error):continue
        return result
