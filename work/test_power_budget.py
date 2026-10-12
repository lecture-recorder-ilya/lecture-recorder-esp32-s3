import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outputs/recorder'))
from power_budget import Budget

class PowerTests(unittest.TestCase):
    def test_budget_waits_after_synchronizing_and_preserves_duty(self):
        now=[0.0];events=[]
        def sleep(seconds):
            events.append(('sleep',seconds));now[0]+=seconds
        def sync():events.append(('sync',));now[0]+=.1
        budget=Budget(sync,lambda:now[0],sleep,lambda:True)
        now[0]=.9;budget.checkpoint();self.assertFalse(events)
        now[0]=1.1;budget.checkpoint()
        self.assertEqual(events[0],('sync',))
        self.assertAlmostEqual(budget.active_seconds,1.2)
        self.assertAlmostEqual(budget.idle_seconds,4.8)
        self.assertLessEqual(max(v[1] for v in events if v[0]=='sleep'),.5)
        self.assertAlmostEqual(budget.started,now[0])
    def test_disabled_budget_does_not_sleep_or_sync(self):
        budget=Budget(lambda:self.fail('sync'),lambda:10,
                      lambda _:self.fail('sleep'),lambda:False)
        budget.checkpoint(force=True)
    def test_setting_change_ends_rest(self):
        now=[0.0];enabled=[True]
        def sleep(seconds):now[0]+=seconds;enabled[0]=False
        budget=Budget(clock=lambda:now[0],sleep=sleep,enabled=lambda:enabled[0])
        now[0]=1;budget.checkpoint();self.assertEqual(budget.idle_seconds,.5)

if __name__=='__main__':unittest.main()
