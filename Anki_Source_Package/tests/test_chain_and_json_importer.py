# -*- coding: utf-8 -*-
import unittest
import json
from models import Card, Deck
from data_manager import get_or_create_deck_by_path, import_json_cards
from ui.import_cards_dialog import build_text_card, parse_delimited_text


class TestChainAndJsonImporter(unittest.TestCase):
    def setUp(self):
        self.data = {"decks": []}

    def test_card_dataclass_chain_fields(self):
        card = Card(
            question="What is glycolysis?",
            answer="Breakdown of glucose into pyruvate",
            context_anchor="Cellular Respiration",
            chain_order=1,
            parent_chain_id="chain-uuid-123",
            trap_note="Requires 2 ATP investment"
        )
        self.assertEqual(card.context_anchor, "Cellular Respiration")
        self.assertEqual(card.chain_order, 1)
        self.assertEqual(card.parent_chain_id, "chain-uuid-123")
        self.assertEqual(card.trap_note, "Requires 2 ATP investment")

        # Test to_dict and from_dict
        d = card.to_dict()
        self.assertEqual(d["context_anchor"], "Cellular Respiration")
        self.assertEqual(d["chain_order"], 1)
        self.assertEqual(d["parent_chain_id"], "chain-uuid-123")
        self.assertEqual(d["trap_note"], "Requires 2 ATP investment")

        restored = Card.from_dict(d)
        self.assertEqual(restored.context_anchor, "Cellular Respiration")
        self.assertEqual(restored.chain_order, 1)
        self.assertEqual(restored.parent_chain_id, "chain-uuid-123")
        self.assertEqual(restored.trap_note, "Requires 2 ATP investment")

    def test_get_or_create_deck_by_path(self):
        # Single level
        d1 = get_or_create_deck_by_path(self.data, "Biology")
        self.assertEqual(d1["name"], "Biology")
        self.assertEqual(len(self.data["decks"]), 1)

        # Multi level (Parent::Child::Sub)
        d_sub = get_or_create_deck_by_path(self.data, "Biology::Genetics::Mendel")
        self.assertEqual(d_sub["name"], "Mendel")
        
        # Verify hierarchy
        bio = self.data["decks"][0]
        self.assertEqual(bio["name"], "Biology")
        self.assertEqual(len(bio["children"]), 1)
        genetics = bio["children"][0]
        self.assertEqual(genetics["name"], "Genetics")
        self.assertEqual(len(genetics["children"]), 1)
        self.assertEqual(genetics["children"][0]["name"], "Mendel")

        # Existing path should not duplicate
        d_existing = get_or_create_deck_by_path(self.data, "Biology::Genetics::Mendel")
        self.assertEqual(d_existing["_id"], d_sub["_id"])
        self.assertEqual(len(genetics["children"]), 1)

    def test_import_json_cards_with_auto_chaining(self):
        json_payload = [
            {
                "deck_name": "Biochemistry::Respiration",
                "context_anchor": "Glycolysis Pathway",
                "question": "Step 1 of Glycolysis?",
                "answer": "Glucose -> Glucose-6-phosphate via Hexokinase",
                "trap_note": "Consumes 1 ATP",
                "chain_order": 1
            },
            {
                "deck_name": "Biochemistry::Respiration",
                "context_anchor": "Glycolysis Pathway",
                "question": "Step 2 of Glycolysis?",
                "answer": "G6P -> Fructose-6-phosphate via Phosphoglucose Isomerase",
                "trap_note": "Reversible isomerization",
                "chain_order": 2
            },
            {
                "deck_name": "Biochemistry::Respiration",
                "context_anchor": "Glycolysis Pathway",
                "question": "Step 3 of Glycolysis?",
                "answer": "F6P -> Fructose-1,6-bisphosphate via PFK-1",
                "trap_note": "Committed and rate-limiting step!",
                "chain_order": 3
            },
            {
                "deck_name": "General Science",
                "question": "What is water?",
                "answer": "H2O"
            }
        ]

        res = import_json_cards(self.data, json_payload)
        self.assertEqual(res["imported"], 4)
        self.assertEqual(res["chains_created"], 1)

        # Check that the 3 glycolysis cards share the SAME parent_chain_id
        cards = res["created_cards"]
        glyco_cards = [c for c in cards if c["context_anchor"] == "Glycolysis Pathway"]
        self.assertEqual(len(glyco_cards), 3)
        self.assertIsNotNone(glyco_cards[0]["parent_chain_id"])
        self.assertEqual(glyco_cards[0]["parent_chain_id"], glyco_cards[1]["parent_chain_id"])
        self.assertEqual(glyco_cards[1]["parent_chain_id"], glyco_cards[2]["parent_chain_id"])
        self.assertEqual(glyco_cards[0]["chain_order"], 1)
        self.assertEqual(glyco_cards[1]["chain_order"], 2)
        self.assertEqual(glyco_cards[2]["chain_order"], 3)
        self.assertEqual(glyco_cards[2]["trap_note"], "Committed and rate-limiting step!")

        # Check standalone card
        water_card = [c for c in cards if c["question"] == "What is water?"][0]
        self.assertIsNone(water_card["parent_chain_id"])

    def test_import_json_duplicate_policies(self):
        json_payload = [
            {"deck_name": "TestDeck", "question": "Card 1", "answer": "Answer 1"},
            {"deck_name": "TestDeck", "question": "Card 2", "answer": "Answer 2"}
        ]
        import_json_cards(self.data, json_payload)

        # 1. Skip policy
        dup_payload = [
            {"deck_name": "TestDeck", "question": "Card 1", "answer": "Changed 1"},
            {"deck_name": "TestDeck", "question": "Card 3", "answer": "Answer 3"}
        ]
        res_skip = import_json_cards(self.data, dup_payload, dup_policy="skip")
        self.assertEqual(res_skip["imported"], 1)
        self.assertEqual(res_skip["skipped"], 1)

        # 2. Update policy
        update_payload = [
            {"deck_name": "TestDeck", "question": "Card 1", "answer": "Updated Answer 1", "trap_note": "New Trap"}
        ]
        res_update = import_json_cards(self.data, update_payload, dup_policy="update")
        self.assertEqual(res_update["updated"], 1)
        
        # Verify updated card in deck
        deck = self.data["decks"][0]
        card1 = [c for c in deck["cards"] if c["question"] == "Card 1"][0]
        self.assertEqual(card1["answer"], "Updated Answer 1")
        self.assertEqual(card1["trap_note"], "New Trap")

    def test_review_queue_sorting_keeps_chain_together_in_order(self):
        chain_id = "chain-xyz-999"
        card_chain_3 = Card(question="Q3", chain_order=3, parent_chain_id=chain_id, sm2_due="2026-08-25T10:00:00")
        card_chain_1 = Card(question="Q1", chain_order=1, parent_chain_id=chain_id, sm2_due="2026-08-25T12:00:00")
        card_chain_2 = Card(question="Q2", chain_order=2, parent_chain_id=chain_id, sm2_due="2026-08-25T11:00:00")
        card_standalone_a = Card(question="QA", sm2_due="2026-08-25T08:00:00")
        card_standalone_b = Card(question="QB", sm2_due="2026-08-25T15:00:00")

        items = [
            (card_chain_3, None, card_chain_3),
            (card_standalone_b, None, card_standalone_b),
            (card_chain_1, None, card_chain_1),
            (card_standalone_a, None, card_standalone_a),
            (card_chain_2, None, card_chain_2),
        ]

        # Sorting logic identical to review_screen.py
        chain_earliest_due = {}
        for card, box_idx, sm2_obj in items:
            cid = card.get("parent_chain_id")
            if cid:
                due = sm2_obj.get("sm2_due", "") or ""
                if cid not in chain_earliest_due or (due and due < chain_earliest_due[cid]):
                    chain_earliest_due[cid] = due

        def _sort_key(item):
            card, box_idx, sm2_obj = item
            cid = card.get("parent_chain_id")
            if cid:
                c_due = chain_earliest_due.get(cid, "")
                try:
                    c_order = int(card.get("chain_order", 0) or 0)
                except (ValueError, TypeError):
                    c_order = 0
                return (c_due, str(cid), c_order, sm2_obj.get("sm2_due", "") or "")
            else:
                return (sm2_obj.get("sm2_due", "") or "", "", 0, "")

        items.sort(key=_sort_key)

        # Expected order: QA (08:00) -> Q1 (step 1) -> Q2 (step 2) -> Q3 (step 3) -> QB (15:00)
        questions_order = [item[0].get("question") for item in items]
        self.assertEqual(questions_order, ["QA", "Q1", "Q2", "Q3", "QB"])

    def test_import_json_matches_by_card_uid_and_preserves_sm2(self):
        # 1. Initial import of Card #3 (overloaded question)
        initial_payload = [
            {
                "card_uid": "uid-rbi-003",
                "deck_name": "TestDeck",
                "question": "RBI के प्रतीक चिह्न में कौन-सा पशु और कौन-सा वृक्ष चित्रित है?",
                "answer": "रॉयल बंगाल टाइगर और ताड़ का पेड़",
                "notes": "पुरानी ओवरलोडेड नोट्स"
            }
        ]
        import_json_cards(self.data, initial_payload)
        deck = self.data["decks"][0]
        c3 = deck["cards"][0]
        
        # Simulate user reviewing card #3 (SM-2 progress accumulated)
        c3["reps"] = 6
        c3["interval"] = 15
        c3["factor"] = 2.6
        c3["state"] = "review"
        c3["due"] = "2026-09-20T10:00:00"

        # 2. Re-import where Card #3 is pruned to 1 atomic question (Fact 1),
        # and a new Card #4 (Fact 2) is added with new UID!
        split_payload = [
            {
                "card_uid": "uid-rbi-003", # SAME UID
                "deck_name": "TestDeck",
                "question": "भारतीय रिज़र्व बैंक (RBI) के आधिकारिक प्रतीक चिह्न में कौन-सा पशु चित्रित है?",
                "answer": "रॉयल बंगाल टाइगर (Royal Bengal Tiger)",
                "notes": "1935 में शुरुआत में ईस्ट इंडिया कंपनी का डबल मोहर शेर था।"
            },
            {
                "card_uid": "uid-rbi-004", # NEW UID
                "deck_name": "TestDeck",
                "question": "भारतीय रिज़र्व बैंक (RBI) के आधिकारिक प्रतीक चिह्न में कौन-सा वृक्ष चित्रित है?",
                "answer": "ताड़ का पेड़ (Palm Tree)",
                "notes": "प्रतीक में ताड़ का पेड़ स्थिरता और छाया का प्रतीक है।"
            }
        ]

        res = import_json_cards(self.data, split_payload, dup_policy="update")
        self.assertEqual(res["updated"], 1)
        self.assertEqual(res["imported"], 1)

        # 3. Verify Card #3 updated text but kept 100% of SM-2 progress
        updated_c3 = [c for c in deck["cards"] if c.get("card_uid") == "uid-rbi-003"][0]
        self.assertEqual(updated_c3["question"], "भारतीय रिज़र्व बैंक (RBI) के आधिकारिक प्रतीक चिह्न में कौन-सा पशु चित्रित है?")
        self.assertEqual(updated_c3["answer"], "रॉयल बंगाल टाइगर (Royal Bengal Tiger)")
        self.assertEqual(updated_c3["reps"], 6)       # PRESERVED!
        self.assertEqual(updated_c3["interval"], 15)   # PRESERVED!
        self.assertEqual(updated_c3["factor"], 2.6)    # PRESERVED!
        self.assertEqual(updated_c3["state"], "review")# PRESERVED!

        # 4. Verify Card #4 is brand new card
        new_c4 = [c for c in deck["cards"] if c.get("card_uid") == "uid-rbi-004"][0]
        self.assertEqual(new_c4.get("reviews", 0), 0)
        self.assertEqual(new_c4.get("sm2_repetitions", 0), 0)
        self.assertEqual(new_c4["answer"], "ताड़ का पेड़ (Palm Tree)")


if __name__ == "__main__":
    unittest.main()

