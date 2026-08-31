import os
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt5.QtWidgets import QApplication, QLabel

_APP = QApplication.instance() or QApplication([])

from ui.recovery_dialog import RecoveryDialog, _draft_label


class RecoveryDialogCopyTests(unittest.TestCase):
    def test_latest_draft_is_labeled_recommended(self):
        label = _draft_label(
            {
                "updated_at": "2026-05-15T08:54:16",
                "card": {
                    "title": "Recovered PDF",
                    "pdf_path": r"C:\notes\sample.pdf",
                    "boxes": [{"box_id": "b1"}],
                },
                "deck": {},
            },
            0,
        )

        self.assertIn("Recommended - newest draft", label)
        self.assertIn("Recovered PDF from sample.pdf", label)
        self.assertIn("1 mask", label)
        self.assertIn("No deck selected yet", label)

    def test_dialog_selects_newest_draft_and_uses_plain_button_labels(self):
        dialog = RecoveryDialog(
            {
                "drafts": [
                    {
                        "draft_id": "new",
                        "updated_at": "2026-05-15T08:54:16",
                        "card": {"title": "Newer", "boxes": []},
                        "deck": {},
                    },
                    {
                        "draft_id": "old",
                        "updated_at": "2026-05-15T08:53:57",
                        "card": {"title": "Older", "boxes": []},
                        "deck": {},
                    },
                ],
                "review_events": [],
            }
        )
        self.addCleanup(dialog.close)

        self.assertEqual(dialog.draft_list.currentRow(), 0)
        self.assertIn("Recommended - newest draft", dialog.draft_list.item(0).text())
        self.assertIn("Older draft", dialog.draft_list.item(1).text())
        self.assertEqual(dialog.btn_open_draft.text(), "Restore Selected Draft")
        self.assertEqual(dialog.btn_delete_draft.text(), "Delete Selected Draft")
        self.assertEqual(dialog.btn_restore_latest.text(), "Restore Latest Draft")
        self.assertEqual(dialog.btn_delete_all.text(), "Delete All Drafts")
        self.assertEqual(dialog.btn_close.text(), "Close (Keep Drafts)")
        self.assertEqual(
            dialog.btn_recover_reviews.text(), "No Review Progress To Restore"
        )
        self.assertEqual(dialog.btn_restore_latest.objectName(), "primaryRecoveryButton")
        self.assertEqual(dialog.btn_open_draft.objectName(), "primaryRecoveryButton")
        self.assertEqual(dialog.btn_delete_all.objectName(), "dangerRecoveryButton")
        self.assertEqual(dialog.btn_delete_draft.objectName(), "dangerRecoveryButton")
        self.assertIn("QPushButton:hover", dialog.styleSheet())
        self.assertIn("QPushButton:focus", dialog.styleSheet())
        self.assertFalse(dialog.btn_recover_reviews.isEnabled())

    def test_restore_latest_button_uses_newest_draft_without_manual_selection(self):
        dialog = RecoveryDialog(
            {
                "drafts": [
                    {"draft_id": "new", "card": {"title": "Newer"}, "deck": {}},
                    {"draft_id": "old", "card": {"title": "Older"}, "deck": {}},
                ],
                "review_events": [],
            }
        )
        self.addCleanup(dialog.close)
        dialog.draft_list.clearSelection()
        dialog.draft_list.setCurrentItem(None)

        dialog._open_latest_draft()

        self.assertEqual(dialog.action, "open_draft")
        self.assertEqual(dialog.selected_draft["draft_id"], "new")

    def test_delete_all_button_collects_every_draft(self):
        dialog = RecoveryDialog(
            {
                "drafts": [
                    {"draft_id": "new", "card": {"title": "Newer"}, "deck": {}},
                    {"draft_id": "old", "card": {"title": "Older"}, "deck": {}},
                ],
                "review_events": [],
            }
        )
        self.addCleanup(dialog.close)

        dialog._delete_all_drafts()

        self.assertEqual(dialog.action, "delete_all_drafts")
        self.assertEqual(
            [draft["draft_id"] for draft in dialog.selected_drafts],
            ["new", "old"],
        )

    def test_review_progress_only_dialog_explains_empty_draft_list(self):
        dialog = RecoveryDialog(
            {
                "drafts": [],
                "review_events": [
                    {"event_id": "r1", "status": "recoverable"},
                    {"event_id": "r2", "status": "recoverable"},
                ],
            }
        )
        self.addCleanup(dialog.close)

        labels = "\n".join(label.text() for label in dialog.findChildren(QLabel))
        self.assertIn("We found unsaved review progress", labels)
        self.assertIn("No card drafts are waiting", labels)
        self.assertIn("Review progress ready to restore: 2", labels)
        self.assertEqual(dialog.draft_list.count(), 1)
        self.assertIn("Review progress checkpoint", dialog.draft_list.item(0).text())
        self.assertTrue(dialog.btn_recover_reviews.isEnabled())
        self.assertEqual(dialog.btn_recover_reviews.objectName(), "primaryRecoveryButton")
        self.assertEqual(dialog.btn_close.text(), "Close (Keep Progress)")
        self.assertFalse(dialog.btn_restore_latest.isEnabled())
        self.assertFalse(dialog.btn_open_draft.isEnabled())


if __name__ == "__main__":
    unittest.main()
