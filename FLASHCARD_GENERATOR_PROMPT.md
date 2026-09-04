# 🎯 SSC / Competitive Exam Master AI Flashcard Prompt (3-Layer Deep Concept & 80/20 Architecture)

> **Instructions for User:**
> 1. Click **`🤖 Copy AI Prompt (80/20 Rule)`** in the Anki App (or copy the text below).
> 2. Open any AI model (Google Gemini, ChatGPT, Claude).
> 3. Attach your Class Notes / Lecture Slides / PYQ PDF.
> 4. Paste this prompt and send.
> 5. Copy the JSON response from the AI and paste it into Anki's **Bulk Card Importer** (`📦 Paste JSON / Chained Cards` tab).

---

```markdown
# TASK: Generate 100% Complete, 3-Layer Deep Concept, Tier-Ranked (80/20) Flashcards (JSON) from Attached Document

### ROLE & CORE OBJECTIVE:
You are an expert SSC/Competitive Exam Curriculum Architect and Anki Flashcard Engineer. Your objective is to convert 100% of the factual, conceptual, legal, and analytical content from the attached document into rich, 3-layer, sequential, tier-ranked flashcards.
The student must NEVER need to search Google or open a textbook to clarify doubts—every card must contain the full background story, mechanism, and reasoning inside the `notes` field.

---

### CRITICAL PROCESSING & CARD ARCHITECTURE RULES:

1. **3-Layer Card Structure (Rapid Active Recall + Deep Concept):**
   - **Layer 1 (`question`):** 1 sharp, focused question testing a single concept.
   - **Layer 2 (`answer`):** 1-2 lines of direct, punchy core answer with bold key terms for instant 5-second active recall.
   - **Layer 3 (`notes` - Deep Theory & Background Explanation):** 
     - 3 to 5 rich, structured bullet points explaining the **complete background story, the "Why & How" mechanism, historical evolution, related articles, and common doubts**.
     - Must be 100% self-contained so no external Googling is ever needed.
   - **Layer 4 (`trap_note`):** 1 punchy line warning against specific exam traps, confusing option pairs, or exceptions.

2. **Zero-Drop Coverage (100% Completeness):**
   - Extract every article, amendment number, year, committee, landmark case, numerical timeline, majority type, exception, and handwritten annotation. No detail must be skipped.

3. **80/20 Tier-Ranked Prioritization (`priority_tier`):**
   - **`"priority_tier": 1` (Core 20% Data / 80% Value):** Core definitions, essential articles, mandatory timelines/majorities, fundamental mechanisms, and high-frequency exam concepts.
   - **`"priority_tier": 2` (Elimination 80% Data / 20% Value):** Nuanced details, secondary committees, background facts, specific case citations, and minor historical points used for MCQ option elimination.

4. **Roman Numerals to Common Decimal Numbers (Mandatory Rule):**
   - Whenever writing Constitutional Parts, Schedules, or Roman numerals, ALWAYS write the Roman numeral followed by its common decimal/Arabic number (0-9) in parentheses.
   - *Examples:*
     - Write `Part XVIII (18)` or `भाग XVIII (18)` (NOT just `Part XVIII`).
     - Write `Part XV (15)` or `भाग XV (15)` (NOT just `Part XV`).
     - Write `Part XX (20)` or `भाग XX (20)` (NOT just `Part XX`).
     - Write `8वीं अनुसूची (Schedule VIII - 8)`.

5. **Self-Contained Acronyms & Full Forms (Zero-Search Rule):**
   - Whenever an abbreviation, commission, or short form is used, ALWAYS include its full expansion (in English and Hindi) in parentheses on first mention.
   - *Examples:*
     - Write `ECI (Election Commission of India / भारतीय चुनाव आयोग)`.
     - Write `UPSC (Union Public Service Commission / संघ लोक सेवा आयोग)`.
     - Write `CAA (Constitutional Amendment Act / संविधान संशोधन अधिनियम)`.
     - Write `EWS (Economically Weaker Sections / आर्थिक रूप से कमजोर वर्ग)`.
     - Write `NCBC (National Commission for Backward Classes / राष्ट्रीय पिछड़ा वर्ग आयोग)`.

6. **Sequential Linked Story Chaining:**
   - Group multi-step concepts, chronologies, or complex physical landscapes under the same `context_anchor` badge.
   - Order them logically from foundation to advanced traps using sequential integers (`chain_order: 1, 2, 3...`).

7. **Cross-Subject Knowledge Mesh (Multi-Disciplinary 360° Chaining):**
   - Whenever a concept intersects with another subject (Polity, History, Geography, Economics, Static GK, Science), ALWAYS embed a `🔗 Cross-Subject Connect:` bullet in `notes` referencing the connected subject and chapter.
   - *Example:* `• 🔗 Cross-Subject Connect [Polity & History]: रायसीना हिल्स पर ही राष्ट्रपति भवन (Rashtrapati Bhavan - Article 52-62) व संसद परिसर स्थित है (1911 में लुटियंस द्वारा निर्मित)।`
   - *Example:* `• 🔗 Cross-Subject Connect [Ancient History / Jainism]: पारसनाथ पहाड़ी 23वें जैन तीर्थंकर भगवान पार्श्वनाथ का निर्वाण स्थल (सम्मेद शिखरजी) है।`

8. **Language & Tone:**
   - Bilingual (Hinglish/Hindi with standard English technical/geographical terms in brackets) for maximum active recall and memory retention.

9. **Mandatory Post-Generation Verification (Q-A Alignment & 100% MCQ Coverage):**
   - **Q-A Semantic Alignment:** Verify that every Front (Question) and Back (Answer) pair directly, accurately, and satisfactorily answers each other. Never allow an answer to give a company name when a percentage/share is asked, or an unrelated formula when a market/instrument name is asked.
   - **Zero Answer Leaks:** Never leak or reveal the answer on the Front (e.g. expanding an acronym on the question side that gives away the core recall).
   - **Exhaustive PDF & MCQ Solvability:** Ensure 100% of all topics and sub-points from the source notes are covered, and that every single past MCQ from the chapter can be solved with 100% accuracy using these cards alone.

---

### REQUIRED JSON SCHEMA:
Output ONLY a strictly valid JSON array of objects matching this exact structure:

[
  {
    "deck_name": "Subject::Chapter_Name",
    "context_anchor": "Concept Anchor (e.g., National Emergency Article 352)",
    "question": "Single sharp question targeting one concept with full forms and decimal numbers.",
    "answer": "• Crisp 1-2 line direct answer with bold key terms.",
    "notes": "• Background / Mechanism: Detailed explanation of why and how this provision operates.\n• Historical / Legal Context: Relevant constitutional history, previous position, or related amendment.\n• Connected Provisions: Related articles/clauses that clarify potential doubts completely.",
    "trap_note": "TRAP: Direct exam pitfall, confusing pair, or exception.",
    "chain_order": 1,
    "priority_tier": 1
  }
]

### INSTRUCTIONS:
- Replace "Subject::Chapter_Name" with the subject and topic of the attached PDF (e.g., Polity::Emergency_and_Amendments).
- Ensure the `notes` field is rich, detailed, and completely explains the context so the user never has to search Google.
- Return ONLY the raw JSON array. Do not wrap in conversational chit-chat.
```
