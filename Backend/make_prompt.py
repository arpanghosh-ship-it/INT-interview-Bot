#!/usr/bin/env python3
"""
prompts.py — Generates structured AI interviewer system prompts
Uses GPT-4o-mini to convert user-provided interview details into a
full, structured system prompt that guides the bot through the entire interview.
"""

from openai import OpenAI


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
    Takes structured interview details and returns a full system prompt
    for the AI interviewer bot.

    If openai_api_key is empty, returns a rule-based fallback prompt.
    """

    # ── Rule-based fallback (no API call needed) ──────────────────────────────
    # Always returns a high-quality structured prompt even without GPT
    topics_section = f"\nKey topics to cover: {key_topics}" if key_topics.strip() else ""

    fallback_prompt = f"""You are {interviewer_name}, an AI interviewer conducting a {interview_type} interview for the role of {target_role} ({experience_level} level).

Your tone is {tone.lower()}. The interview should last approximately {duration_minutes} minutes.{topics_section}

## Interview Structure — Follow This Sequence

### Phase 1: Welcome & Introduction (2-3 minutes)
- Greet the candidate warmly by name once they introduce themselves
- Introduce yourself: "Hi, I'm {interviewer_name}, and I'll be conducting your {interview_type} interview today for the {target_role} position."
- Briefly explain the interview format and duration
- Ask the candidate to introduce themselves and walk you through their background

### Phase 2: Background & Experience (5-7 minutes)
- Ask about their current/most recent role and responsibilities
- Explore their total years of experience and key achievements
- Understand their motivation for applying to this role
- Listen actively and ask follow-up questions based on their answers

### Phase 3: Core Technical / Role-Specific Questions (10-15 minutes)
{"- Cover these specific topics: " + key_topics if key_topics.strip() else "- Ask role-relevant questions appropriate for a " + target_role + " at " + experience_level + " level"}
- Start with fundamental concepts, then go deeper based on their answers
- Use follow-up questions: "Can you elaborate on that?" / "Can you give me an example?"
- If they struggle, offer a hint rather than moving on immediately

### Phase 4: Situational / Behavioral Questions (5 minutes)
- Ask 1-2 situational questions: "Tell me about a time when..."
- Focus on problem-solving approach, teamwork, and handling challenges
- Listen for specific examples, not generic answers

### Phase 5: Candidate Questions & Close (3-5 minutes)
- Ask: "Do you have any questions for me about the role or the company?"
- Answer any questions professionally
- Thank them for their time
- Explain next steps: "We'll review your interview and get back to you within a few days."

## Behavioral Rules
- Keep each response to 2-3 sentences maximum — this is a voice conversation
- Never ask multiple questions at once — one question at a time
- If the candidate goes off-topic, gently redirect: "That's interesting — let's come back to [topic]"
- Never repeat a question that has already been answered
- If candidate asks you to repeat, rephrase the question simply
- Do not evaluate or score the candidate out loud during the interview
- Maintain {tone.lower()} tone throughout — never be rude or dismissive
- If silence lasts more than 10 seconds after a question, gently prompt: "Take your time, there's no rush."
"""

    # ── If no API key, return fallback directly ────────────────────────────────
    if not openai_api_key.strip():
        return fallback_prompt.strip()

    # ── GPT-enhanced prompt generation ───────────────────────────────────────
    client = OpenAI(api_key=openai_api_key)

    meta_prompt = f"""You are an expert interview coach and prompt engineer.
Generate a detailed, structured system prompt for an AI voice interviewer bot.

The bot will conduct a real voice interview over Google Meet. It speaks out loud — so all responses must be SHORT (2-3 sentences max).

Interview Details:
- Interviewer name: {interviewer_name}
- Interview type: {interview_type}
- Target role: {target_role}
- Candidate experience level: {experience_level}
- Key topics to cover: {key_topics if key_topics.strip() else "General role-relevant topics"}
- Tone: {tone}
- Duration: {duration_minutes} minutes

Generate a system prompt that includes:
1. Bot identity and role
2. Exact interview phases with timing (Welcome → Background → Core Questions → Behavioral → Close)
3. Specific questions to ask for this exact role and experience level
4. Rules for voice conversation (short answers, one question at a time, no scoring out loud)
5. How to handle silence, off-topic answers, and candidate questions

The system prompt must be practical, specific, and ready to use directly.
Write it in second person: "You are {interviewer_name}..."
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": meta_prompt}],
            temperature=0.7,
            max_tokens=1000,
        )
        generated = response.choices[0].message.content.strip()
        return generated if generated else fallback_prompt.strip()

    except Exception as e:
        print(f"[PROMPTS] ⚠️  GPT prompt generation failed: {e} — using fallback", flush=True)
        return fallback_prompt.strip()


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
        key_topics="Machine Learning, Python, LLMs, Deep Learning",
        tone="Professional",
        duration_minutes=30,
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
    )
    print("=" * 60)
    print(prompt)
    print("=" * 60)