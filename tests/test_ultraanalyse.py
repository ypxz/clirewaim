"""The Transaction inversion behind the ultraanalyse dashboard."""

import json
import tempfile
import unittest
from pathlib import Path

from ultraanalyse import inversion, logs, topics


def row(issuer, reviewer, accepted, amount, index=1):
    return {
        "issuer": issuer,
        "reviewer": reviewer,
        "line_item_index": index,
        "accepted": accepted,
        "amount": amount,
    }


class InvertItemTests(unittest.TestCase):
    def setUp(self):
        # Fair Value 100. A charges 80 (fair), B charges 120 (Overcharge), C is silent (0 / 0).
        # Limits: A 90, B 150, C 0.
        self.rows = [
            row("A", "B", True, 80.0),
            row("A", "C", False, 120.0),  # wrongful rejection pays 1.5 x 80
            row("B", "A", False, 0.0),  # rightful rejection
            row("B", "C", False, 0.0),
            row("C", "A", True, 0.0),
            row("C", "B", True, 0.0),
        ]

    def test_wrongful_rejection_reveals_a_fair_charge(self):
        item = inversion.invert_item(self.rows)
        self.assertEqual(item["teams"]["A"]["a"], 80.0)
        self.assertTrue(item["teams"]["A"]["fair"])
        self.assertEqual(item["t_lo"], 80.0)

    def test_unaccepted_overcharge_is_unseen_but_known_unfair(self):
        item = inversion.invert_item(self.rows)
        self.assertIsNone(item["teams"]["B"]["a"])
        self.assertFalse(item["teams"]["B"]["fair"])
        self.assertIsNone(item["t_hi"])

    def test_logged_values_close_the_bracket(self):
        item = inversion.invert_item(self.rows, {"B": (120.0, 150.0)})
        self.assertEqual(item["t_hi"], 120.0)
        self.assertEqual(item["teams"]["B"]["b"], 150.0)
        self.assertEqual(item["t_quality"], "bounded")

    def test_limit_is_an_interval(self):
        item = inversion.invert_item(self.rows, {"B": (120.0, 150.0)})
        self.assertEqual(item["teams"]["A"]["b_lo"], 0.0)
        self.assertEqual(item["teams"]["A"]["b_hi"], 120.0)
        self.assertEqual(item["teams"]["C"]["b_hi"], 80.0)

    def test_money_adds_up(self):
        item = inversion.invert_item(self.rows)
        self.assertEqual(item["teams"]["A"]["income"], 200.0)
        self.assertEqual(item["teams"]["C"]["cost"], 120.0)
        self.assertEqual(item["teams"]["C"]["penalty"], 40.0)
        self.assertAlmostEqual(sum(t["net"] for t in item["teams"].values()), 0.0)

    def test_accepted_overcharge_bounds_the_fair_value(self):
        rows = self.rows + [
            row("D", "A", False, 0.0),
            row("D", "B", True, 110.0),
            row("D", "C", False, 0.0),
        ]
        item = inversion.invert_item(rows)
        self.assertEqual(item["t_hi"], 110.0)
        self.assertEqual(item["teams"]["B"]["overpaid_cost"], 110.0)
        self.assertEqual(inversion.fair_value_point(80.0, 110.0), 80.0)
        self.assertEqual(inversion.fair_value_point(100.0, 110.0), 104.88)

    def test_shared_payout_is_read_as_the_cap(self):
        rows = [row(team, "X", True, 2000.0) for team in "ABC"] + [
            row(team, "Y", False, 0.0) for team in "ABC"
        ]
        item = inversion.invert_item(rows)
        self.assertEqual(item["cap"], 2000.0)
        self.assertEqual(item["teams"]["A"]["a_kind"], "at-least")
        self.assertEqual(item["t_hi"], 500.0)

    def test_two_equal_overcharges_are_not_a_cap(self):
        rows = [row(team, "X", True, 300.0) for team in "AB"] + [
            row(team, "Y", False, 0.0) for team in "AB"
        ]
        item = inversion.invert_item(rows)
        self.assertIsNone(item["cap"])
        self.assertEqual(item["t_hi"], 300.0)
        self.assertEqual(item["teams"]["A"]["a_kind"], "exact")

    def test_a_larger_payout_rules_out_the_cap(self):
        rows = [row(team, "X", True, 300.0) for team in "ABC"] + [
            row(team, "Y", False, 0.0) for team in "ABC"
        ]
        rows += [row("D", "X", True, 450.0), row("D", "Y", False, 0.0)]
        self.assertIsNone(inversion.invert_item(rows)["cap"])

    def test_hindsight(self):
        item = inversion.invert_item(self.rows)
        result = inversion.hindsight(item, "C")
        self.assertEqual(result["reviewer_regret"], 40.0)
        # Charging 80: B accepts (its Limit is at least 80), A's Limit is unknown, so 1x each.
        self.assertEqual(result["issuer_benchmark"], 160.0)
        self.assertEqual(result["issuer_gap"], 160.0)


class ModelReplyTests(unittest.TestCase):
    def _replies(self, *raw_replies):
        with tempfile.TemporaryDirectory() as folder:
            log_dir = Path(folder) / "ai_log"
            log_dir.mkdir()
            for number, raw in enumerate(raw_replies):
                (log_dir / f"game_007_{number}.json").write_text(
                    json.dumps({"draw": str(number), "reply": raw})
                )
            return logs.read_model_replies(Path(folder), 7)

    def test_malformed_replies_do_not_stop_the_build(self):
        replies = self._replies(
            '{"items": null}', "not json", '{"items": ["x", {"line_item": "a"}]}', "[1]"
        )
        self.assertEqual(replies["items"], {})
        self.assertEqual(len(replies["draws"]), 4)

    def test_fenced_reply_is_read(self):
        fenced = '```json\n{"items": [{"line_item": 2, "coverage_probability": 0.9, "clause": " c "}]}\n```'
        replies = self._replies(fenced)
        self.assertEqual(replies["items"][2][0]["coverage"], 0.9)
        self.assertEqual(replies["items"][2][0]["clause"], "c")


class TopicTests(unittest.TestCase):
    def test_opening_decides_the_peril(self):
        text = "Accidental damage claim on the portable electronics cover. The laptop was thrown when the driver swerved to avoid a tree in a storm."
        self.assertEqual(topics.case_topic(text), "Accidental damage: electronics")
        self.assertEqual(
            topics.case_topic("A bicycle was stolen from outside the building."),
            "Bicycle theft",
        )

    def test_item_category(self):
        self.assertEqual(
            topics.item_category("Vehicle costs (1 pcs)"), "Travel / vehicle"
        )
        self.assertEqual(topics.item_category("Skilled worker hours (1 hrs)"), "Labour")


if __name__ == "__main__":
    unittest.main()
