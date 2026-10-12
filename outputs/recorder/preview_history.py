"""Five minutes of draft text in RAM, independent of the saved audio."""
import re

class PreviewHistory:
    def __init__(self):
        self.file=None;self.rows=[];self.serial=0
    @staticmethod
    def words(text):return set(re.findall(r'\w+',text.casefold()))
    def update(self,name,seconds,segments):
        if name!=self.file:self.file=name;self.rows=[];self.serial=0
        cutoff=seconds-300
        self.rows=[row for row in self.rows if row['end']>cutoff]
        for segment in segments:
            text=segment.get('text','').strip();start=float(segment['start']);end=float(segment['end'])
            if not text or end<=cutoff:continue
            words=self.words(text);match=None
            # Adjacent identical short decoder outputs form one display interval.
            # Keep later genuine repetitions and never discard source audio.
            if self.rows:
                previous=self.rows[-1]
                normalized=lambda value:re.findall(r'\w+',value.casefold())
                if (1<=len(normalized(text))<=4 and normalized(text)==normalized(previous['text'])
                    and 0<=start-previous['end']<=2 and end>=previous['end']):
                    previous['end']=end
                    previous['needs_review']=bool(previous.get('needs_review') or segment.get('needs_review'))
                    continue
            for row in reversed(self.rows[-12:]):
                overlap=min(end,row['end'])-max(start,row['start'])
                previous=self.words(row['text']);similarity=len(words&previous)/max(1,min(len(words),len(previous)))
                if overlap>0 and abs(start-row['start'])<3 and similarity>=.65:
                    match=row;break
            if match:
                if end>=match['end']-.2 and len(text)>=len(match['text'])*.65:
                    match.update(text=text,end=max(end,match['end']))
                    match.update({key:segment[key] for key in ('needs_review','recognition') if key in segment})
                continue
            if self.rows and end<=max(row['end'] for row in self.rows)+.15:continue
            self.serial+=1;self.rows.append(dict(segment,id=self.serial,text=text))
        return [dict(row) for row in self.rows]
