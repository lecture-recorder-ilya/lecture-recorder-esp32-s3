from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outputs/recorder'))
from formula_evidence import check


class FormulaEvidenceTests(unittest.TestCase):
    def test_supported_features(self):
        for quote,latex in [
            ('Икс равен минус пяти.','x=-5'),
            ('Икс с индексом два равен пяти.',r'x_{2}=5'),
            ('Икс в квадрате равен четырём.',r'x^2=4'),
            ('Икс меньше или равен пяти.',r'x\leq 5'),
            ('Икс не больше пяти.',r'x\leq 5'),
            ('Икс не равен пяти.',r'x\ne 5'),
            ('Икс делён на два равен трём.',r'\frac{x}{2}=3'),
            ('Скорость равна пяти метрам в секунду.',r'v=5\,\mathrm{m/s}'),
            ('Длина равна пяти сантиметрам.',r'l=5\,\mathrm{cm}'),
            ('Площадь равна пяти квадратным метрам.',r'S=5\,\mathrm{m^2}'),
            ('Сила равна массе, умноженной на ускорение.','F=ma'),
        ]:
            with self.subTest(quote=quote,latex=latex):self.assertTrue(check(latex,quote)[0],check(latex,quote))

    def test_lost_or_changed_features_are_not_confirmed(self):
        for quote,latex in [
            ('Икс равен минус пяти.','x=5'),
            ('Икс с индексом два равен пяти.','x=5'),
            ('Икс в квадрате равен четырём.','x=4'),
            ('Икс меньше или равен пяти.','x<5'),
            ('Икс делён на два равен трём.','x=3'),
            ('Икс делён на два равен трём.',r'\frac{2}{x}=3'),
            ('Икс минус игрек равен двум.','y-x=2'),
            ('Скорость равна пяти метрам в секунду.',r'v=5\,\mathrm{m}'),
            ('Длина равна пяти сантиметрам.',r'l=5\,\mathrm{m}'),
            ('Площадь равна пяти квадратным метрам.',r'S=5\,\mathrm{m}'),
        ]:
            with self.subTest(quote=quote,latex=latex):self.assertFalse(check(latex,quote)[0])

    def test_comparison_and_unit_notation(self):
        for quote,latex in [('Икс не больше пяти.',r'x\leq 5'),('Икс больше или равен пяти.',r'x\geq 5'),
                            ('Сопротивление равно пяти омам.',r'R=5\Omega'),
                            ('Скорость равна пяти метрам в секунду.','v=5 м/с')]:
            with self.subTest(quote=quote):self.assertTrue(check(latex,quote)[0],check(latex,quote))

    def test_pending_formula_preserves_quote_and_timestamps(self):
        from ai_worker import validate_part
        from formula_evidence import finalize
        quote='Икс не равен пяти.';rows=[dict(id=7,start=10,end=14,text=quote)]
        result=validate_part(dict(formulas=[dict(quote=quote,segment_id=7,latex='x=5')]),rows)
        self.assertEqual(result['formulas'],[])
        pending=result['formula_review'][0]
        self.assertEqual((pending['quote'],pending['start'],pending['end']),(quote,10,14))
        self.assertNotIn('latex',pending)
        context=dict(segments=rows,formulas=[dict(quote=quote,segment_id=7,start=10,end=14,latex='x=5')])
        self.assertEqual(finalize(context)['formulas'],[])
        self.assertEqual(finalize(context)['formula_review'][0]['review_reason'],'comparison')


if __name__=='__main__':unittest.main()
