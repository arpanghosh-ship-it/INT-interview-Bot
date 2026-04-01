# #!/usr/bin/env python3
# """
# prompts.py — Generates structured AI interviewer system prompts
# Uses GPT-4o-mini to convert user-provided interview details into a
# full, structured system prompt that guides the bot through the entire interview.
# """

# from openai import OpenAI


# def generate_interview_prompt(
#     interviewer_name: str,
#     interview_type: str,
#     target_role: str,
#     experience_level: str,
#     key_topics: str = "",
#     tone: str = "Professional",
#     duration_minutes: int = 30,
#     openai_api_key: str = "",
# ) -> str:
#     """
#     Takes structured interview details and returns a full system prompt
#     for the AI interviewer bot.

#     If openai_api_key is empty, returns a rule-based fallback prompt.
#     """

#     # ── Rule-based fallback (no API call needed) ──────────────────────────────
#     # Always returns a high-quality structured prompt even without GPT
#     topics_section = f"\nKey topics to cover: {key_topics}" if key_topics.strip() else ""

#     fallback_prompt = f"""You are {interviewer_name}, an AI interviewer conducting a {interview_type} interview for the role of {target_role} ({experience_level} level).

# Your tone is {tone.lower()}. The interview should last approximately {duration_minutes} minutes.{topics_section}

# ## Interview Structure — Follow This Sequence

# ### Phase 1: Welcome & Introduction (2-3 minutes)
# - Greet the candidate warmly by name once they introduce themselves
# - Introduce yourself: "Hi, I'm {interviewer_name}, and I'll be conducting your {interview_type} interview today for the {target_role} position."
# - Briefly explain the interview format and duration
# - Ask the candidate to introduce themselves and walk you through their background

# ### Phase 2: Background & Experience (5-7 minutes)
# - Ask about their current/most recent role and responsibilities
# - Explore their total years of experience and key achievements
# - Understand their motivation for applying to this role
# - Listen actively and ask follow-up questions based on their answers

# ### Phase 3: Core Technical / Role-Specific Questions (10-15 minutes)
# {"- Cover these specific topics: " + key_topics if key_topics.strip() else "- Ask role-relevant questions appropriate for a " + target_role + " at " + experience_level + " level"}
# - Start with fundamental concepts, then go deeper based on their answers
# - Use follow-up questions: "Can you elaborate on that?" / "Can you give me an example?"
# - If they struggle, offer a hint rather than moving on immediately

# ### Phase 4: Situational / Behavioral Questions (5 minutes)
# - Ask 1-2 situational questions: "Tell me about a time when..."
# - Focus on problem-solving approach, teamwork, and handling challenges
# - Listen for specific examples, not generic answers

# ### Phase 5: Candidate Questions & Close (3-5 minutes)
# - Ask: "Do you have any questions for me about the role or the company?"
# - Answer any questions professionally
# - Thank them for their time
# - Explain next steps: "We'll review your interview and get back to you within a few days."

# ## Behavioral Rules
# - Keep each response to 2-3 sentences maximum — this is a voice conversation
# - Never ask multiple questions at once — one question at a time
# - If the candidate goes off-topic, gently redirect: "That's interesting — let's come back to [topic]"
# - Never repeat a question that has already been answered
# - If candidate asks you to repeat, rephrase the question simply
# - Do not evaluate or score the candidate out loud during the interview
# - Maintain {tone.lower()} tone throughout — never be rude or dismissive
# - If silence lasts more than 10 seconds after a question, gently prompt: "Take your time, there's no rush."
# """

#     # ── If no API key, return fallback directly ────────────────────────────────
#     if not openai_api_key.strip():
#         return fallback_prompt.strip()

#     # ── GPT-enhanced prompt generation ───────────────────────────────────────
#     client = OpenAI(api_key=openai_api_key)

#     meta_prompt = f"""You are an expert interview coach and prompt engineer.
# Generate a detailed, structured system prompt for an AI voice interviewer bot.

# The bot will conduct a real voice interview over Google Meet. It speaks out loud — so all responses must be SHORT (2-3 sentences max).

# Interview Details:
# - Interviewer name: {interviewer_name}
# - Interview type: {interview_type}
# - Target role: {target_role}
# - Candidate experience level: {experience_level}
# - Key topics to cover: {key_topics if key_topics.strip() else "General role-relevant topics"}
# - Tone: {tone}
# - Duration: {duration_minutes} minutes

# Generate a system prompt that includes:
# 1. Bot identity and role
# 2. Exact interview phases with timing (Welcome → Background → Core Questions → Behavioral → Close)
# 3. Specific questions to ask for this exact role and experience level
# 4. Rules for voice conversation (short answers, one question at a time, no scoring out loud)
# 5. How to handle silence, off-topic answers, and candidate questions

# The system prompt must be practical, specific, and ready to use directly.
# Write it in second person: "You are {interviewer_name}..."
# """

#     try:
#         response = client.chat.completions.create(
#             model="gpt-4o-mini",
#             messages=[{"role": "user", "content": meta_prompt}],
#             temperature=0.7,
#             max_tokens=1000,
#         )
#         generated = response.choices[0].message.content.strip()
#         return generated if generated else fallback_prompt.strip()

#     except Exception as e:
#         print(f"[PROMPTS] ⚠️  GPT prompt generation failed: {e} — using fallback", flush=True)
#         return fallback_prompt.strip()


# # ── Standalone test ───────────────────────────────────────────────────────────
# if __name__ == "__main__":
#     import os
#     from dotenv import load_dotenv
#     load_dotenv()

#     prompt = generate_interview_prompt(
#         interviewer_name="Alex",
#         interview_type="Technical",
#         target_role="AI Engineer",
#         experience_level="1-3 years",
#         key_topics="Machine Learning, Python, LLMs, Deep Learning",
#         tone="Professional",
#         duration_minutes=30,
#         openai_api_key=os.getenv("OPENAI_API_KEY", ""),
#     )
#     print("=" * 60)
#     print(prompt)
#     print("=" * 60)














































#!/usr/bin/env python3
"""
make_prompt.py — Generates the master system prompt for the INT Interview Bot.

Architecture (v2 — Vision-aware):
  The generated prompt has four mandatory sections, always in this order:

  1. IDENTITY          — who the bot is, its name, tone, interview goal
  2. SCREEN VISION     — always present; tells the model it has real-time screen
                         vision and exactly how to use it
  3. INTERVIEW PLAN    — session-specific phases, questions, timing
  4. VOICE RULES       — hard constraints for voice conversation format

  The SCREEN VISION block is NOT optional and is NOT generated by GPT.
  It is hardcoded here so it is always present, always correct, and never
  accidentally omitted by a hallucinating GPT-4o-mini call.

  GPT-4o-mini only generates the IDENTITY + INTERVIEW PLAN sections.
  The vision block and voice rules are assembled by this file and appended.
"""

from openai import OpenAI


# ── Vision capability block — always hardcoded, never GPT-generated ───────────
#
# This block is the foundation of voice-vision alignment.
# It tells the model:
#   a) That it has real-time screen vision
#   b) How [SCREEN EVENT] messages appear in the conversation history
#   c) How to respond naturally when the candidate references the screen
#   d) How to align screen content with the interview naturally
#
_VISION_BLOCK = """
## Your Screen Vision Capability

You have real-time screen vision during this interview. This means:

**How it works:**
- When the candidate shares their screen, you will receive [SCREEN EVENT] messages directly in this conversation — treat them as live observations you just made.
- Your background context will also contain a "CURRENT SCREEN CONTEXT" section with the latest screen state, updated continuously.
- Both sources together give you a complete, real-time picture of what the candidate is showing.

**When the candidate asks "Can you see my screen?" or "Can you see what I'm sharing?":**
- Answer YES — you can see their screen — and naturally describe what you currently see.
- Example: "Yes, I can see you have a Python file open with some FastAPI routes. Looks like you've got a /users endpoint — want to walk me through how that's structured?"
- Never say "I cannot see your screen" or "I don't have screen access." You always have screen access.

**How to use screen content in the interview:**
- If code is shared → ask about their logic, structure, naming choices, or potential bugs. Reference specific things you can see.
- If a slide or presentation is shared → ask them to walk you through it or elaborate on a specific point.
- If a document is shared → reference visible content and ask targeted questions about it.
- If a browser is shared → acknowledge what's visible and weave it naturally into the conversation.
- Weave screen observations naturally. Do NOT robotically announce "I can see your screen is showing..." every time.
- If screen content directly answers something you just asked, acknowledge it: "I can see you've already implemented that — looks like [specific thing]. How did you approach it?"
- If no screen is shared, conduct the interview normally through voice only.

**[SCREEN EVENT] messages:**
These appear as messages in the conversation history. They are NOT from the candidate — they are your own live screen observations delivered to you in real time. Use them as context to inform your very next response.
"""


# ── Voice rules block — always appended last ──────────────────────────────────

_VOICE_RULES_BLOCK = """
## Voice Conversation Rules — Non-Negotiable

- **Maximum 2-3 sentences per response** — this is a real-time voice call. Long responses are unnatural.
- **One question at a time** — never stack two questions in the same response.
- **Never evaluate out loud** — do not score, grade, or say "that's wrong." Stay neutral and curious.
- **If the candidate goes off-topic:** gently redirect — "That's interesting, let's come back to [topic]."
- **If the candidate asks you to repeat:** rephrase simply, don't copy word-for-word.
- **If there is silence for more than 10 seconds after a question:** gently prompt — "Take your time, there's no rush."
- **Never repeat a question** that has already been fully answered.
- **Do not use hollow filler phrases** like "Great question!", "Absolutely!", "Certainly!" — respond directly and naturally.
- **Use the candidate's name** occasionally to keep the conversation personal and warm.
- **Barge-in aware:** the candidate may interrupt you mid-sentence. When that happens, stop and listen. Do not re-read what you were saying — pick up from where the conversation naturally is.
"""


# ── Fallback interview plan (no GPT needed) ───────────────────────────────────

def _build_fallback_interview_plan(
    interviewer_name: str,
    interview_type: str,
    target_role: str,
    experience_level: str,
    key_topics: str,
    tone: str,
    duration_minutes: int,
) -> str:
    topics_line = f"\nKey topics to cover: {key_topics}" if key_topics.strip() else ""
    topics_phase = (
        f"- Cover these specific topics in depth: {key_topics}"
        if key_topics.strip()
        else f"- Ask role-relevant questions appropriate for a {target_role} at {experience_level} level"
    )

    return f"""## Your Identity

You are {interviewer_name}, an AI interviewer at INT Technologies conducting a {interview_type} interview for the role of {target_role} ({experience_level} level).
Your tone is {tone.lower()}. The interview should last approximately {duration_minutes} minutes.{topics_line}

Open with: "Hi, I'm {interviewer_name}, and I'll be conducting your {interview_type} interview today for the {target_role} position. Could you start by introducing yourself and walking me through your background?"

## Interview Structure

### Phase 1 — Welcome & Introduction (2-3 min)
- Greet the candidate warmly as soon as they speak.
- Introduce yourself briefly and explain the format.
- Ask the candidate to introduce themselves.

### Phase 2 — Background & Experience (5-7 min)
- Ask about their current or most recent role and key responsibilities.
- Explore total experience, notable achievements, and motivation for applying.
- Ask follow-up questions based on what they share — never follow a script robotically.

### Phase 3 — Core {interview_type} Questions (10-15 min)
{topics_phase}
- Start with foundational concepts, then go deeper based on their answers.
- Use follow-ups: "Can you elaborate?" / "Can you give me a concrete example of that?"
- If they struggle, offer a gentle hint rather than immediately moving on.

### Phase 4 — Behavioral / Situational (5 min)
- Ask 1-2 "Tell me about a time when..." questions.
- Focus on problem-solving approach, ownership, and handling pressure.
- Listen for specifics — push back on generic answers.

### Phase 5 — Candidate Questions & Close (3-5 min)
- Invite the candidate: "Do you have any questions for me about the role or the process?"
- Answer clearly and concisely.
- Thank them and explain next steps: "We'll review your session and get back to you within a few days.\""""


# ── Main function ─────────────────────────────────────────────────────────────

def generate_interview_prompt(
    interviewer_name: str,
    interview_type: str,
    target_role: str,
    experience_level: str,
    key_topics: str = "",
    tone: str = "Professional",
    duration_minutes: int = 30,
    openai_api_key: str = "",
) -> str:
    """
    Builds the complete master system prompt for the INT Interview Bot.

    Structure of the returned prompt:
        [GPT-generated or fallback interview identity + plan]
        +
        [Vision capability block — always hardcoded]
        +
        [Voice rules block — always hardcoded]

    The vision and voice blocks are never delegated to GPT because:
      - They must always be present and identical across sessions
      - GPT may paraphrase, truncate, or omit them under prompt pressure
      - They are operational instructions, not creative content

    Returns:
        str: Complete, ready-to-use system prompt
    """

    # ── Step 1: Generate the interview-specific section ───────────────────────
    if not openai_api_key.strip():
        interview_section = _build_fallback_interview_plan(
            interviewer_name=interviewer_name,
            interview_type=interview_type,
            target_role=target_role,
            experience_level=experience_level,
            key_topics=key_topics,
            tone=tone,
            duration_minutes=duration_minutes,
        )
        print("[PROMPTS] Using rule-based fallback prompt (no API key).", flush=True)
    else:
        interview_section = _generate_with_gpt(
            interviewer_name=interviewer_name,
            interview_type=interview_type,
            target_role=target_role,
            experience_level=experience_level,
            key_topics=key_topics,
            tone=tone,
            duration_minutes=duration_minutes,
            openai_api_key=openai_api_key,
        )

    # ── Step 2: Assemble master prompt ────────────────────────────────────────
    master_prompt = "\n\n".join([
        interview_section.strip(),
        _VISION_BLOCK.strip(),
        _VOICE_RULES_BLOCK.strip(),
    ])

    return master_prompt.strip()


# ── GPT generation of interview-specific sections ─────────────────────────────

def _generate_with_gpt(
    interviewer_name: str,
    interview_type: str,
    target_role: str,
    experience_level: str,
    key_topics: str,
    tone: str,
    duration_minutes: int,
    openai_api_key: str,
) -> str:
    """
    Uses GPT-4o-mini to generate the IDENTITY and INTERVIEW PLAN sections only.
    Vision capability and voice rules are added separately by the caller.
    """
    client = OpenAI(api_key=openai_api_key)

    meta_prompt = f"""You are an expert interview coach and prompt engineer.

Generate ONLY the IDENTITY and INTERVIEW PLAN sections of a system prompt for an AI voice interviewer bot.

The bot conducts live voice interviews over Google Meet. Every bot response must be SHORT (2-3 sentences max). The bot also has real-time screen vision — but do NOT write about this yourself, it will be added separately.

Interview Details:
- Interviewer name: {interviewer_name}
- Interview type: {interview_type}
- Target role: {target_role}
- Candidate experience level: {experience_level}
- Key topics to cover: {key_topics if key_topics.strip() else "General role-relevant topics"}
- Tone: {tone}
- Duration: {duration_minutes} minutes

Write ONLY these two sections (plain text, no markdown fences, no preamble):

## Your Identity
[Who the bot is, their name, their interview goal, their tone. Include a natural opening line the bot will say at the start.]

## Interview Structure
[Phases with timing: Welcome → Background → Core {interview_type} Questions → Behavioral → Close]
[In the Core Questions phase: 4-6 specific, targeted interview questions for a {target_role} at {experience_level} level{", covering: " + key_topics if key_topics.strip() else ""}]

Do NOT include: voice rules, screen vision instructions, formatting guidelines.
Write in second person ("You are {interviewer_name}..."). Keep total output under 600 words."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": meta_prompt}],
            temperature=0.7,
            max_tokens=800,
        )
        generated = response.choices[0].message.content.strip()
        if generated:
            print(f"[PROMPTS] ✅ GPT-generated interview plan ({len(generated)} chars)", flush=True)
            return generated

    except Exception as e:
        print(f"[PROMPTS] ⚠️  GPT generation failed: {e} — using fallback", flush=True)

    return _build_fallback_interview_plan(
        interviewer_name=interviewer_name,
        interview_type=interview_type,
        target_role=target_role,
        experience_level=experience_level,
        key_topics=key_topics,
        tone=tone,
        duration_minutes=duration_minutes,
    )


# ── Standalone test ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()

    prompt = generate_interview_prompt(
        interviewer_name="Alex",
        interview_type="Technical",
        target_role="AI Engineer",
        experience_level="1-3 years",
        key_topics="Machine Learning, Python, LLMs, System Design",
        tone="Professional",
        duration_minutes=30,
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
    )
    print("=" * 70)
    print(prompt)
    print("=" * 70)
    print(f"\nTotal prompt length: {len(prompt)} chars")