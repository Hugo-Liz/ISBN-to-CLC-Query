import os
import tempfile
import unittest

from query_cache import QueryCache


class QueryCacheTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.now = [1000.0]
        self.cache = QueryCache(
            path=os.path.join(self.temp_dir.name, "cache.sqlite3"),
            positive_ttl=100,
            negative_ttl=10,
            clock=lambda: self.now[0],
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_success_result_round_trip(self):
        expected = {"title": "测试书", "clc_code": "TP311"}
        self.cache.set_success("9787020002207", expected)

        hit, result = self.cache.get("9787020002207")

        self.assertTrue(hit)
        self.assertEqual(result, expected)

    def test_not_found_round_trip(self):
        self.cache.set_not_found("9787506365437")

        hit, result = self.cache.get("9787506365437")

        self.assertTrue(hit)
        self.assertIsNone(result)

    def test_expired_entry_is_removed(self):
        self.cache.set_success("9787530210291", {"title": "过期书"})
        self.now[0] += 101

        hit, result = self.cache.get("9787530210291")

        self.assertFalse(hit)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
