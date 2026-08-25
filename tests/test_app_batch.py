import json
import unittest

from app import _generate_batch_results


VALID_ISBNS = [
    "9787521779158",
    "9787020002207",
    "9787506365437",
    "9787530210291",
    "9787544258609",
]


class FakeClient:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []
        self.last_network_request = False
        self.closed = False

    def query(self, isbn):
        self.calls.append(isbn)
        self.last_network_request = True
        if self.fail:
            raise ConnectionError("模拟上游失败")
        return {
            "title": f"测试书 {isbn}",
            "authors": "张三",
            "publisher": "测试出版社",
            "pubdate": "2024",
            "clc_code": "TP311",
            "subject": "",
            "summary": "",
        }

    def close(self):
        self.closed = True


def collect_events(isbns, client):
    lines = _generate_batch_results(
        isbns,
        client=client,
        sleep_fn=lambda _delay: None,
        delay_fn=lambda: 0,
    )
    return [json.loads(line) for line in lines]


class BatchQueryTest(unittest.TestCase):
    def test_duplicate_isbns_are_queried_once_but_both_are_returned(self):
        client = FakeClient()

        events = collect_events(
            [VALID_ISBNS[0], "978-7-5217-7915-8"],
            client,
        )
        done = events[-1]

        self.assertEqual(client.calls, [VALID_ISBNS[0]])
        self.assertEqual(done["total"], 2)
        self.assertEqual(done["success_count"], 2)
        self.assertEqual(len(done["results"]), 2)
        self.assertEqual(done["results"][1]["isbn_input"], "978-7-5217-7915-8")

    def test_circuit_breaker_stops_network_after_three_failures(self):
        client = FakeClient(fail=True)

        events = collect_events(VALID_ISBNS, client)
        done = events[-1]

        self.assertEqual(len(client.calls), 3)
        self.assertEqual(done["fail_count"], 5)
        self.assertEqual(done["results"][3]["error_type"], "circuit_open")
        self.assertEqual(done["results"][4]["error_type"], "circuit_open")


if __name__ == "__main__":
    unittest.main()
