import hashlib
import json
import os
import re


def write_bytes(path,payload):
    if path.exists():
        previous=path.read_bytes()
        if previous!=payload:
            folder=path.parent/'history'/path.stem;folder.mkdir(parents=True,exist_ok=True)
            archived=folder/(hashlib.sha256(previous).hexdigest()+'.json')
            if archived.exists() and archived.read_bytes()!=previous:raise OSError('Архив конспекта повреждён')
            if not archived.exists():
                temporary=archived.with_suffix('.json.tmp');temporary.write_bytes(previous);temporary.replace(archived)
    temporary=path.with_suffix(path.suffix+'.tmp')
    with temporary.open('wb') as stream:
        stream.write(payload);stream.flush();os.fsync(stream.fileno())
    temporary.replace(path)


def save(path,value):write_bytes(path,json.dumps(value,ensure_ascii=False,indent=2).encode('utf-8'))


def versions(path):return sorted(p.stem for p in (path.parent/'history'/path.stem).glob('*.json') if re.fullmatch('[0-9a-f]{64}',p.stem))


def restore(path,revision):
    if not re.fullmatch('[0-9a-f]{64}',revision):raise ValueError('Некорректная версия конспекта')
    archived=path.parent/'history'/path.stem/(revision+'.json');payload=archived.read_bytes()
    if hashlib.sha256(payload).hexdigest()!=revision:raise ValueError('Архив конспекта повреждён')
    value=json.loads(payload)
    if not isinstance(value,dict):raise ValueError('Некорректный архив конспекта')
    from transcript_quality import markdown
    export=path.with_suffix('.md');temporary=export.with_suffix('.md.tmp')
    try:
        temporary.write_text(markdown(value)+'\n',encoding='utf-8')
        write_bytes(path,payload)
        temporary.replace(export)
    finally:
        if temporary.is_file():temporary.unlink()
    return value
