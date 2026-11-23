import atexit
import json
import queue
import selectors
import subprocess
import sys
import threading
import time
from pathlib import Path
from context_review import request, apply, VERSION

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent.parent


class Reviewer:
    def __init__(self, publish):
        self.publish = publish; self.pending = queue.Queue(maxsize=1)
        self.thread = None; self.process = None; self.log = None
        self.signature = None
        self.status = {'version': VERSION, 'memory_rows': 4, 'state': 'waiting',
                       'checked_windows': 0, 'changed_rows': 0,'formulas':0}
        atexit.register(self.close)

    def submit(self, name, rows, subject=None):
        if len(rows) < 2:
            return
        value = request(rows, subject)
        signature = (name, tuple((r['start'], r['end']) for r in value['rows']))
        if signature == self.signature or (not value['slots'] and not value['collect_math']):
            return
        self.signature = signature
        try:
            self.pending.get_nowait()
        except queue.Empty:
            pass
        self.pending.put_nowait((name, value))
        if self.thread is None:
            self.thread = threading.Thread(target=self.loop, daemon=True)
            self.thread.start()

    def close(self):
        process, self.process = self.process, None
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=3)
            process.stdin.close(); process.stdout.close()
        if self.log is not None:
            self.log.close(); self.log = None

    def infer(self, value):
        if self.process is None or self.process.poll() is not None:
            self.close()
            self.log = (PROJECT/'work/context-review.log').open('a')
            self.process = subprocess.Popen([sys.executable, '-u', str(ROOT/'context_review.py')],
                                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=self.log, text=True, bufsize=1)
        process = self.process
        process.stdin.write(json.dumps(value, ensure_ascii=False)+'\n'); process.stdin.flush()
        deadline = time.monotonic()+240
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while time.monotonic() < deadline:
                if selector.select(timeout=1):
                    line = process.stdout.readline()
                    if not line:
                        raise RuntimeError('Самопроверка завершилась; исходный текст сохранён')
                    result = json.loads(line)
                    if result.get('error'):
                        raise RuntimeError(result['error'])
                    return result['answer']
                if process.poll() is not None:
                    break
        raise TimeoutError('Самопроверка занята; исходный текст сохранён')

    def loop(self):
        while True:
            try:
                name, value = self.pending.get(timeout=120)
            except queue.Empty:
                self.close(); self.status.update(state='waiting')
                continue
            try:
                self.status.update(state='checking', file=name, context_end=value['rows'][-1]['end'])
                answer = self.infer(value)
                updates = apply(value, answer)
                from math_formulas import collect
                formulas=collect(value,answer)
                changed = self.publish(name, updates, formulas)
                self.status.update(state='ready', checked_windows=self.status['checked_windows']+1,
                                   changed_rows=self.status['changed_rows']+changed,
                                   formulas=self.status['formulas']+len(formulas),error='')
            except Exception as error:
                self.close()
                self.status.update(state='unavailable', error=str(error)[:200])
