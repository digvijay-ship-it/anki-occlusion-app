# 🎯 SSC / Competitive Exam Master AI Flashcard Prompt (3-Layer Deep Concept, Visual Diagrams & 80/20 Architecture)

> **Instructions for User:**
> 1. Click **`🤖 Copy AI Prompt (80/20 Rule)`** in the Anki App (or copy the text below).
> 2. Open any AI model (Google Gemini, ChatGPT, Claude).
> 3. Attach your Class Notes / Lecture Slides / PYQ PDF.
> 4. Paste this prompt and send.
> 5. Copy the JSON response from the AI and paste it into Anki's **Bulk Card Importer** (`📦 Paste JSON / Chained Cards` tab).

---

```markdown
# TASK: Generate 100% Complete, 3-Layer Deep Concept, Visual Diagrams & Mental Maps, Tier-Ranked (80/20) Flashcards (JSON) from Attached Document

### ROLE & CORE OBJECTIVE:
You are an expert SSC/Competitive Exam Curriculum Architect, Cartographer, and Anki Flashcard Engineer. Your objective is to convert 100% of the factual, conceptual, spatial, legal, and analytical content from the attached document into rich, 3-layer, sequential, tier-ranked flashcards with embedded visual mental maps, directional diagrams, and spatial flowcharts.
The student must NEVER need to search Google or open a textbook to clarify doubts—every card must contain the full background story, spatial visualization, mechanism, and reasoning inside the `notes` field.

---

### CRITICAL PROCESSING & CARD ARCHITECTURE RULES:

1. **3-Layer Card Structure (Rapid Active Recall + Deep Concept):**
   - **Layer 1 (`question`):** 1 sharp, focused question testing a single concept/spatial relationship.
   - **Layer 2 (`answer`):** 1-2 lines of direct, punchy core answer with bold key terms for instant 5-second active recall.
   - **Layer 3 (`notes` - Deep Theory, Background & Visual Mental Maps):** 
     - 3 to 5 rich, structured bullet points explaining the **complete background story, the "Why & How" mechanism, historical evolution, related articles, and common doubts**.
     - **Visual Mental Map / ASCII Spatial Diagram:** Whenever describing Geography, History chronologies, Biology anatomy, or Spatial locations, ALWAYS embed a clean visual box diagram / directional flowchart (e.g. North-to-South chains, West-to-East sequences, River bifurcations, or Mountain barriers).
   - **Layer 4 (`trap_note`):** 1 punchy line warning against specific exam traps, confusing option pairs, or exceptions.

2. **Visual Maps & Spatial Diagrams (Mandatory for Geography / History / Science):**
   - Rote text memorization fails in Geography and History. Always provide clean, highly structured visual representations:
     * **Directional Arrows & Box Flowcharts:** e.g. `[Aravalli] ──> [Malwa Plateau] ──> [Vindhya] ──> [Narmada Rift] ──> [Satpura] ──> [Tapi Rift] ──> [Deccan Trap]`
     * **North-to-South / West-to-East Chains:** e.g. `(North) Nallamala ──> Velikonda ──> Palkonda ──> Javadi ──> Shevaroy ──> Nilgiri ──> Anaimalai ──> Cardamom (South)`
     * **Mountain Pass Connectors:** e.g. `[Mumbai] ──(Thal Ghat / NH-3)──> [Nashik / Kolkata]`
     * **Comparison Grids:** Clean visual comparisons for rapid mental picture formation.

3. **Zero-Drop Coverage (100% Completeness):**
   - Extract every article, amendment number, year, committee, landmark case, mountain height in meters, mineral mine name, river tributary, majority type, exception, and handwritten annotation. No detail must be skipped.

4. **80/20 Tier-Ranked Prioritization (`priority_tier`):**
   - **`"priority_tier": 1` (Core 20% Data / 80% Value):** Core definitions, essential articles/locations, mandatory timelines/majorities, fundamental mechanisms, and high-frequency exam concepts.
   - **`"priority_tier": 2` (Elimination 80% Data / 20% Value):** Nuanced details, secondary hills/mines, background facts, specific case citations, and minor historical points used for MCQ option elimination.

5. **Roman Numerals to Common Decimal Numbers (Mandatory Rule):**
   - Whenever writing Constitutional Parts, Schedules, or Roman numerals, ALWAYS write the Roman numeral followed by its common decimal/Arabic number (0-9) in parentheses.
   - *Examples:*
     - Write `Part XVIII (18)` or `भाग XVIII (18)` (NOT just `Part XVIII`).
     - Write `Schedule VIII (8)` or `8वीं अनुसूची (Schedule VIII - 8)`.

6. **Key Facts & Data Highlighting (Luminous High-Contrast Rule):**
   - ALWAYS wrap high-impact core facts, heights in meters, article numbers, mineral names, river names, and key terms with `==text==` (or `**bold**`) so they render as beautiful luminous golden badges during review.
   - *Example:* `• सर्वोच्च शिखर: **गुरु शिखर (Guru Shikhar)** — ==1722 मीटर== (माउंट आबू, राजस्थान)`
   - *Example:* `• 📖 PDF Reference: Page 18 (Parasnath Hill & Patlands)`

7. **Self-Contained Acronyms & Full Forms (Zero-Search Rule):**
   - Whenever an abbreviation, commission, or short form is used, ALWAYS include its full expansion (in English and Hindi) in parentheses on first mention.
   - *Examples:*
     - Write `NH (National Highway / राष्ट्रीय राजमार्ग)`.
     - Write `DVC (Damodar Valley Corporation / दामोदर घाटी निगम)`.
     - Write `ECI (Election Commission of India / भारतीय चुनाव आयोग)`.

8. **Sequential Linked Story Chaining:**
   - Group multi-step concepts, chronologies, or complex physical landscapes under the same `context_anchor` badge.
   - Order them logically from foundation to advanced traps using sequential integers (`chain_order: 1, 2, 3...`).

9. **Cross-Subject Knowledge Mesh (Multi-Disciplinary 360° Chaining):**
   - Whenever a concept intersects with another subject (Polity, History, Geography, Economics, Static GK, Science), ALWAYS embed a `🔗 Cross-Subject Connect:` bullet in `notes` referencing the connected subject and chapter.
   - *Example:* `• 🔗 Cross-Subject Connect [Polity & History]: रायसीना हिल्स पर ही राष्ट्रपति भवन (Rashtrapati Bhavan - Article 52-62) व संसद परिसर स्थित है (1911 में लुटियंस द्वारा निर्मित)।`
   - *Example:* `• 🔗 Cross-Subject Connect [Ancient History / Jainism]: पारसनाथ पहाड़ी 23वें जैन तीर्थंकर भगवान पार्श्वनाथ का निर्वाण स्थल (सम्मेद शिखरजी) है।`

10. **Language & Tone:**
   - Bilingual (Hinglish/Hindi with standard English technical/geographical terms in brackets) for maximum active recall and memory retention.

11. **Mandatory Post-Generation Verification (Q-A Alignment & 100% MCQ Coverage):**
    - **Q-A Semantic Alignment:** Verify that every Front (Question) and Back (Answer) pair directly, accurately, and satisfactorily answers each other. Never allow an answer to give a company name when a percentage/share is asked, or an unrelated formula when a market/instrument name is asked.
    - **Zero Answer Leaks:** Never leak or reveal the answer on the Front (e.g. expanding an acronym on the question side that gives away the core recall).
    - **Exhaustive PDF & MCQ Solvability:** Ensure 100% of all topics and sub-points from the source notes are covered, and that every single past MCQ from the chapter can be solved with 100% accuracy using these cards alone.

---

### REQUIRED JSON SCHEMA:
Output ONLY a strictly valid JSON array of objects matching this exact structure:

[
  {
    "deck_name": "Subject::Chapter_Name",
    "context_anchor": "Concept Anchor (e.g., Peninsular Plateau Geological Origin)",
    "question": "Single sharp question targeting one concept or spatial relationship with full forms and decimal numbers.",
    "answer": "• Crisp 1-2 line direct answer with bold key terms.",
    "notes": "• Background / Mechanism: Detailed explanation of why and how this feature operates.\n• 🗺️ Visual Mental Map / Spatial Flow:\n  [Feature A] ──> [Feature B] ──> [Feature C]\n• Connected Provisions / Geomorphology: Related facts, peaks, mines, or tributaries.",
    "trap_note": "TRAP: Direct exam pitfall, confusing pair, or exception.",
    "chain_order": 1,
    "priority_tier": 1
  }
]

### INSTRUCTIONS:
- Replace "Subject::Chapter_Name" with the subject and topic of the attached PDF (e.g., Geography::Peninsular_Plateau).
- Ensure the `notes` field contains structured **Visual Mental Maps / ASCII Spatial Diagrams** along with detailed theory so the user can easily visualize locations.
- Return ONLY the raw JSON array. Do not wrap in conversational chit-chat.
```
