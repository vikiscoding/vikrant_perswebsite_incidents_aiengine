# Phase 1 Evaluation Rubric

**Purpose**: Provide a consistent, transparent way to score Phase 1 capabilities on both historical incidents and synthetic scenarios. This is the primary mechanism for measuring **cognitive** progress and deciding when Phase 1 is complete.

**Scope**: Applies only to Phase 1 (State Machine + Triage + Communication + Living Detection Gaps + Verifiability + logging completeness).

**Philosophy**: We score **outcomes and reasoning quality**, not just whether the AI "did something". Every score must be justifiable with evidence from the incident record and traces. The model never grades its own homework (zero trust on self-evaluation).

**Interlocks**: Operational metrics (latency, override rate) live in structured logs per `FIRST_PRINCIPLES.md` — they complement this rubric; they do not replace it.

## Scoring Scale (1–5)

| Score | Meaning | When to Use |
|-------|---------|-------------|
| 5     | Excellent / Production-ready | Clearly better than a strong human performer. Actionable, accurate, and well-reasoned. |
| 4     | Strong / Clearly useful | Good enough to deliver real value today. Minor issues only. |
| 3     | Acceptable baseline | Works but requires human correction or has noticeable gaps. |
| 2     | Weak / Needs improvement | Has fundamental issues that would cause problems in real use. |
| 1     | Poor / Harmful | Would actively mislead or create more work than it saves. |

**Rule**: If you are unsure between two scores, choose the lower one and write the justification.

---

## Rubric Dimensions

### 1. Triage Quality (Weight: High)

**What we measure**: Accuracy and usefulness of priority, impact assessment, categorization, routing, and duplicate detection.

**Scoring Guidance**:
- **5**: Priority and impact_score are correct or better than the original human triage. Affected user estimate is realistic. Routing is clearly correct. Duplicate detection works when obvious. Reasoning is excellent.
- **4**: Mostly correct. One dimension slightly off but overall decision would not cause harm.
- **3**: Directionally correct but would require meaningful human adjustment (e.g., priority off by one level, impact underestimated).
- **2**: Multiple material errors (wrong priority + bad impact + poor routing).
- **1**: Actively harmful (e.g., Critical incident triaged as Low, or major duplicate missed).

**Evidence Required**: Compare against ground truth (historical record or synthetic design) + rubric scorer notes.

### 2. Impact Assessment Quality

**Focus**: How well the system understands business/user impact beyond raw symptoms.

- **5**: Impact_score (1-100) + affected_users_estimate + narrative show genuine understanding of downstream business effect.
- **4**: Good but misses one secondary impact.
- **3**: Basic understanding present but shallow.
- **2–1**: Treats all incidents the same or fundamentally misjudges blast radius.

### 3. Communication Quality & Timeliness

**Dimensions**: Clarity, accuracy, appropriate tone for audience, realistic expectations, professionalism.

**Scoring Guidance**:
- **5**: Drafts are clear, factual, set proper expectations, and would reduce user anxiety. Tone is excellent for the audience.
- **4**: Minor polish needed but would be acceptable to send with small edits.
- **3**: Usable but requires significant rewriting (vague, wrong tone, or missing key context).
- **2–1**: Could cause confusion, set bad expectations, or damage trust.

### 4. Detection Gap Identification (Signature Phase 1 Metric)

**What we measure**: Ability to surface systemic issues that traditional processes miss.

**Scoring Guidance**:
- **5**: Surfaces 2+ high/medium severity gaps with excellent evidence and actionable recommendations (monitoring, runbook, dependency, etc.). Gaps were not obvious from raw data.
- **4**: Surfaces at least one strong, actionable gap with good reasoning.
- **3**: Surfaces at least one gap, but it is either low severity or obvious to a human who read the full timeline.
- **2**: Only superficial or generic observations ("more monitoring would help").
- **1**: No meaningful gaps identified or hallucinates non-existent problems.

**Note**: This dimension is deliberately ambitious. Early scores of 2–3 are expected and valuable for learning.

### 5. Context Preservation & Single Source of Truth Quality

**Focus**: How complete, accurate, and useful the overall incident record is for anyone (including future humans or AI) who was not present.

- **5**: A stranger can fully understand the incident, decisions made, and why without needing Slack/email/history. All key context is captured in the record.
- **4**: Very good, only minor missing pieces.
- **3**: Functional but important context is scattered or missing.
- **2–1**: Record would still require heavy human explanation.

### 6. Reasoning Transparency & Verifiability

**Focus**: Quality of the audit trail for AI decisions.

- **5**: Every significant AI output has clear, specific reasoning that directly references context and data. Full traces stored and replayable (prompt, response, latency).
- **4**: Reasoning is good but occasionally generic ("based on symptoms...").
- **3**: Reasoning exists but is shallow or hard to verify.
- **2–1**: Black box behavior or reasoning that doesn't match the output.

### 6b. Logging Completeness (Gate-style, scored pass/fail + notes)

**Focus**: Whether the run produced enough structured data for later improvement and dashboards.

- **Pass**: Every Grok call has an `ai_traces/` file; every state change has an event with actor; at least time_to_triage (or equivalent timestamps) and override/approval events are reconstructable.
- **Fail**: Missing traces, anonymous actors, or critical path only visible in free-text console output.

A **Fail** on logging completeness blocks Phase 1 exit even if cognitive scores are high.

### 7. Overall Incident Record Utility (Holistic)

**The "Would I want this on a real incident?" score**

This is the single most important number. It combines all dimensions above with real-world usefulness.

- **5**: I would be genuinely happy (or relieved) to have this record on a real production incident.
- **4**: Clearly adds value and I would use it.
- **3**: Better than nothing but I would still do a lot of work myself.
- **2**: Would create more work than it saves.
- **1**: Actively dangerous or misleading.

---

## How to Run an Evaluation

1. Select 8–12 incidents (mix of historical + carefully constructed synthetic).
2. For each incident, run the system from raw input through closure (or as far as Phase 1 supports).
3. Score dimensions 1–7 using the guidance above; record 6b logging completeness pass/fail.
4. Record:
   - Scores + evidence/justification
   - Notable AI traces or failures
   - Operational excerpts from logs (time_to_triage, overrides) when available
   - Suggested improvements
5. Compute average per dimension + overall average.
6. Store the full scored bundle under `evaluations/{date}/` (include paths to traces used).

**Minimum for Phase 1 Exit**:
- Average Overall Record Utility ≥ 3.8
- No cognitive dimension (1–6, 7) below 3.0 average across the set
- Logging completeness **Pass** on all evaluation incidents used for exit

---

## Future Evolution of This Rubric

- Phase 2 will add dimensions for Hypothesis Quality, Evidence Verification, and Mitigation Suggestion quality.
- We will also add "human time saved" estimation (even if approximate).
- Over time we will calibrate the rubric against multiple scorers for inter-rater reliability.
- Dashboard views (when built) will chart **logged** metrics alongside these rubric trends — not invent new unlogged KPIs.

---

**This rubric is the heartbeat of cognitive quality.** Structured logs are the heartbeat of operational improvement. If we cannot honestly score ourselves on both, we are not making real progress.