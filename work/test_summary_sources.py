from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outputs/recorder'))
from summary_sources import reconcile


class SourceTests(unittest.TestCase):
    def report(self):
        quote='Икс не равен пяти.'
        return dict(summary=[quote],summary_evidence=[dict(quote=quote,segment_id=7,start=1,end=4)],
                    segments=[dict(id=7,start=1,end=4,text=quote)])

    def test_shifted_segments_rebind_to_current_audio(self):
        old=reconcile(self.report(),fresh=True)
        old['segments']=[dict(id=30,start=12,end=16,text=old['summary'][0])]
        new=reconcile(old);anchor=new['summary_evidence'][0]
        self.assertEqual((anchor['segment_id'],anchor['start'],anchor['end']),(30,12,16))
        self.assertEqual(anchor['original_source']['start'],1)
        self.assertEqual(anchor['source_status'],'confirmed')

    def test_split_sentence_keeps_whole_quote(self):
        old=self.report();old['segments']=[dict(id=30,start=10,end=12,text='Икс не'),dict(id=31,start=12,end=15,text='равен пяти.')]
        anchor=reconcile(old)['summary_evidence'][0]
        self.assertEqual((anchor['segment_id'],anchor['start'],anchor['end']),(30,10,15))

    def test_ambiguous_or_missing_source_cannot_open_old_timestamp(self):
        for text in ['Икс не равен пяти.','Игрек равен пяти.']:
            old=self.report();old['segments']=[dict(id=i,start=10+i*5,end=14+i*5,text=text) for i in range(2)]
            new=reconcile(old);anchor=new['summary_evidence'][0]
            self.assertNotIn('start',anchor)
            self.assertEqual(anchor['original_source']['start'],1)
            self.assertIn('Источник нужно сверить',new['summary'][0])
            self.assertEqual(reconcile(new),new)

    def test_verified_repeated_quote_keeps_its_identity(self):
        report=self.report();report['segments'].append(dict(id=8,start=5,end=8,text=report['summary'][0]))
        stamped=reconcile(report,fresh=True)
        self.assertEqual(reconcile(stamped)['summary_evidence'][0]['start'],1)

    def test_reviewed_source_and_restoration_clear_pending_status(self):
        report=self.report();report['segments'][0]['needs_review']=True
        pending=reconcile(report)
        self.assertNotIn('start',pending['summary_evidence'][0])
        pending['segments'][0]['reviewed']=True
        restored=reconcile(pending)
        self.assertEqual(restored['summary'],report['summary'])
        self.assertEqual(restored['warnings'],[])

    def test_mac_read_applies_review_decision_before_binding(self):
        from transcript_quality import annotate,report_for
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'analysis').mkdir();(root/'study').mkdir()
            report=self.report();report['segments'][0]['needs_review']=True
            key=annotate(report)['segments'][0]['review_key']
            (root/'analysis/lecture-1.json').write_text(json.dumps(report))
            (root/'study/lecture-1.notes.json').write_text(json.dumps(dict(transcript_review={key:dict(reviewed=True)})))
            read=report_for(root,'lecture-1.wav')
            self.assertEqual(read['summary'],report['summary'])
            self.assertEqual(read['summary_evidence'][0]['source_status'],'confirmed')


if __name__=='__main__':unittest.main()
