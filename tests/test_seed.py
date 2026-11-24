import unittest
from datetime import date, timedelta
from scripts.generate_seed import build_dataset, sql_value


class SeedIntegrityTests(unittest.TestCase):
    def test_multiple_sizes_and_seeds_obey_business_constraints(self):
        for count, days, seed in [(50, 30, 0), (60, 30, 42), (120, 90, 99)]:
            with self.subTest(count=count, days=days, seed=seed):
                end = date(2026, 11, 24)
                start = end - timedelta(days=days - 1)
                data = build_dataset(count, days, end, seed)
                customers = {c['id']: c for c in data['customers']}
                self.assertEqual(len(customers), count)
                self.assertEqual(len({c['customer_code'] for c in customers.values()}), count)
                self.assertEqual({o['status'] for o in data['orders']}, {'PAID', 'PENDING', 'FAILED', 'REFUNDED'})
                self.assertEqual({r['type'] for r in data['ai_results']}, {'QUOTE', 'WEBSITE'})
                for row in data['orders'] + data['ai_results']:
                    self.assertGreaterEqual(row['created_at'], customers[row['customer_id']]['signed_up_at'])
                for order in data['orders']:
                    self.assertGreater(order['amount'], 0)
                    self.assertEqual(order['paid_at'] is not None, order['status'] in ('PAID', 'REFUNDED'))
                    self.assertEqual(order['refunded_at'] is not None, order['status'] == 'REFUNDED')
                    if order['paid_at']:
                        self.assertGreaterEqual(order['paid_at'], order['created_at'])
                    if order['refunded_at']:
                        self.assertGreaterEqual(order['refunded_at'], order['paid_at'])
                    if order['status'] == 'PAID':
                        self.assertNotEqual(order['paid_at'].date(), end)
                dates = {r['created_at'].date() for r in data['ai_results']}
                self.assertIn(start, dates)
                self.assertIn(end, dates)
                self.assertTrue(any(c['signed_up_at'].date() < start for c in customers.values()))
                self.assertTrue(any(c['signed_up_at'].date() >= start for c in customers.values()))

    def test_fixed_fixtures_cover_repeat_first_refund_and_nonpaying(self):
        data = build_dataset()
        paid = [o for o in data['orders'] if o['status'] == 'PAID']
        first_customer_orders = [o for o in paid if o['customer_id'] == 1]
        self.assertEqual(len(first_customer_orders), 3)
        self.assertLess(min(o['paid_at'].date() for o in first_customer_orders), date(2026, 10, 26))
        self.assertEqual(len([o for o in paid if o['customer_id'] == 2]), 1)
        self.assertFalse(any(o['customer_id'] == 3 for o in paid))
        self.assertFalse(any(o['customer_id'] == 6 for o in data['orders']))

    def test_reproducible_and_configurable(self):
        self.assertEqual(build_dataset(seed=42), build_dataset(seed=42))
        self.assertNotEqual(build_dataset(seed=42), build_dataset(seed=43))

    def test_rejects_insufficient_dataset(self):
        for kwargs in [{'customers': 49}, {'days': 29}]:
            with self.assertRaises(ValueError):
                build_dataset(**kwargs)

    def test_sql_string_escaping(self):
        self.assertEqual(sql_value("O'Brien"), "'O''Brien'")
        self.assertEqual(sql_value(None), 'NULL')


if __name__ == '__main__':
    unittest.main()
