import unittest

from objinfo.contribution import format_proposal


class ContributionStandard(unittest.TestCase):
    def test_standard_lists_the_actual_changes_and_base(self):
        before = {"version": 1, "objects": {"box": {"notes": "Before"}, "sun": {"notes": "Remove"}}}
        after = {"version": 1, "objects": {"coin": {"notes": "Added"}, "box": {"notes": "After"}}}
        proposal = format_proposal(before, after, "Tested on a custom track.", "abc123")
        self.assertEqual(proposal.title, "docs(objects): box, coin, sun")
        for text in ["### Changed (1)", "### Added (1)", "### Removed (1)", "`box`", "`coin`", "`sun`", "Tested on a custom track.", "`abc123`"]:
            self.assertIn(text, proposal.body)
        self.assertIn("- [x] The proposed JSON passes", proposal.body)
        self.assertIn("- [ ] The contributor verified", proposal.body)

    def test_verification_is_only_checked_when_the_person_says_so(self):
        before = {"version": 1, "objects": {"box": {"notes": "Before"}}}
        after = {"version": 1, "objects": {"box": {"notes": "After"}}}
        proposal = format_proposal(before, after, reviewed=True, game_tested=True)
        self.assertIn("- [x] The contributor reviewed", proposal.body)
        self.assertIn("- [x] The contributor verified", proposal.body)
        self.assertIn("No additional evidence supplied", proposal.body)

    def test_no_changes_and_invalid_documents_are_rejected(self):
        doc = {"version": 1, "objects": {"box": {"notes": "Same"}}}
        with self.assertRaises(ValueError):
            format_proposal(doc, doc)
        with self.assertRaises(ValueError):
            format_proposal(doc, {"version": 2, "objects": {}})

    def test_large_proposals_fit_github_title_and_body_limits(self):
        after = {"version": 1, "objects": {f"object_{i}": {"notes": "Added"} for i in range(1000)}}
        proposal = format_proposal({"version": 1, "objects": {}}, after, "A" * 70000)
        self.assertLess(len(proposal.title), 256)
        self.assertLess(len(proposal.body), 65536)
        self.assertIn("950 more", proposal.body)
