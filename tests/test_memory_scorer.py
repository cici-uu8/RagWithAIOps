import json
import unittest
from pathlib import Path

from app.models.memory import MemoryRecord
from app.services.memory_scorer import LexicalMemoryScorer


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "memory_synthetic" / "p1_memory_records.json"


class MemoryScorerTests(unittest.TestCase):
    def _record_at(self, index: int) -> MemoryRecord:
        payloads = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        return MemoryRecord.model_validate(payloads[index])

    def test_lexical_scorer_matches_synonym_terms(self):
        record = self._record_at(0)
        scorer = LexicalMemoryScorer()

        score, matched_terms = scorer.score(record, "OOM 之后怎么排查")

        self.assertGreater(score, 0)
        self.assertIn("oom", matched_terms)

    def test_lexical_scorer_includes_payload_and_tags(self):
        record = self._record_at(0)
        scorer = LexicalMemoryScorer()

        score, matched_terms = scorer.score(record, "oom_kill gc")

        self.assertGreater(score, 0)
        self.assertTrue(matched_terms)


if __name__ == "__main__":
    unittest.main()
