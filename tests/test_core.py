import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from patient_caller.config import ALLOWED_DESTINATION, DestinationError, assert_destination, normalize_e164
from patient_caller.call_io import CallRecord
from patient_caller.leads import find_leads
from patient_caller.scenarios import SCENARIOS, instructions_for


class PhoneTests(unittest.TestCase):
    def test_accepts_the_assessment_line_in_common_formats(self):
        self.assertEqual(assert_destination("+1-805-439-8008"), ALLOWED_DESTINATION)
        self.assertEqual(assert_destination("(805) 439-8008"), ALLOWED_DESTINATION)
        self.assertEqual(normalize_e164("18054398008"), ALLOWED_DESTINATION)

    def test_refuses_any_other_number(self):
        with self.assertRaises(DestinationError):
            assert_destination("+16156451400")
        with self.assertRaises(DestinationError):
            assert_destination("+18054398009")


class ScenarioTests(unittest.TestCase):
    def test_ids_are_unique_and_cover_a_submission(self):
        ids = [scenario.id for scenario in SCENARIOS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(ids), 10)

    def test_instructions_name_the_patient_and_today(self):
        text = instructions_for(SCENARIOS[0], datetime(2026, 10, 15))
        self.assertIn("Maya Chen", text)
        self.assertIn("Thursday, October 15, 2026", text)
        self.assertIn("finish_call", text)


class TranscriptTests(unittest.TestCase):
    def test_render_labels_both_sides_and_the_channels(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = CallRecord(
                directory=Path(tmp),
                scenario=SCENARIOS[4],
                caller_number="+15555550100",
                destination=ALLOWED_DESTINATION,
                room_name="call-test",
            )
            record.mark_answered()
            record.add_turn("CLINIC", "How can I help?")
            record.add_turn("PATIENT", "Can I come in Sunday at 10?")
            text = record.render()
        self.assertIn("left channel = clinic", text)
        self.assertIn("CLINIC: How can I help?", text)
        self.assertIn("PATIENT: Can I come in Sunday at 10?", text)
        self.assertIn(ALLOWED_DESTINATION, text)


class LeadTests(unittest.TestCase):
    def test_sunday_confirmation_is_a_lead(self):
        transcript = (
            "[00:04.0] PATIENT: Can I come Sunday at 10?\n"
            "[00:09.0] CLINIC: I've scheduled you for Sunday at 10 am.\n"
        )
        leads = find_leads("05-sunday", transcript)
        self.assertTrue(any(lead.severity == "high" for lead in leads))

    def test_sunday_refusal_is_not_a_lead(self):
        transcript = (
            "[00:04.0] PATIENT: Can I come Sunday at 10?\n"
            "[00:09.0] CLINIC: We are closed Sunday. I can schedule you Monday at 10.\n"
        )
        self.assertEqual(find_leads("05-sunday", transcript), [])

    def test_urgent_call_without_er_direction_is_a_lead(self):
        transcript = (
            "[00:08.0] CLINIC: I booked you a routine visit next Tuesday.\n"
        )
        leads = find_leads("08-urgent-symptoms", transcript)
        self.assertTrue(leads)

    def test_er_direction_is_not_a_lead(self):
        transcript = (
            "[00:08.0] CLINIC: Please go to the ER or call 911 now.\n"
        )
        self.assertEqual(find_leads("08-urgent-symptoms", transcript), [])


if __name__ == "__main__":
    unittest.main()
