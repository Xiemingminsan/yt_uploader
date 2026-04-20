"""
AI metadata generation. Sends transcript, gets back {title, description, tags}.
Uses Anthropic by default (set ANTHROPIC_API_KEY). Falls back to OpenAI if
OPENAI_API_KEY is set instead.
"""
import json
import os
import re

SYSTEM_PROMPT = """You are a YouTube SEO expert. Given a video transcript, produce:
1. A click-worthy SEO title (max 90 chars, no clickbait lies)
2. A detailed description (2-3 paragraphs, written in first person like "In this video I...")
   - Start with a hook
   - Cover the main points from the transcript
   - End with 3-5 relevant hashtags (#example)
3. A list of 15-25 YouTube tags (comma-separated strings, each tag 1-4 words)

CRITICAL: Respond with ONLY valid JSON, no markdown fences, no preamble. Schema:
{
  "title": "string",
  "description": "string",
  "tags": ["tag1", "tag2", ...]
}"""


def generate_metadata(transcript, channel_hint=""):
    """Returns dict {title, description, tags}. channel_hint adds context."""
    # Truncate transcript to stay under context limits (~80k chars is safe)
    transcript = transcript[:80000]
    user_msg = (
        f"Channel context: {channel_hint}\n\n" if channel_hint else ""
    ) + f"Transcript:\n{transcript}"

    if os.getenv("ANTHROPIC_API_KEY"):
        return _call_anthropic(user_msg)
    elif os.getenv("OPENAI_API_KEY"):
        return _call_openai(user_msg)
    else:
        raise RuntimeError("Set ANTHROPIC_API_KEY or OPENAI_API_KEY in .env")


def _call_anthropic(user_msg):
    import anthropic
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5"),
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    text = resp.content[0].text
    return _parse_json(text)


def _call_openai(user_msg):
    from openai import OpenAI
    client = OpenAI()
    resp = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        response_format={"type": "json_object"},
    )
    return _parse_json(resp.choices[0].message.content)


def _parse_json(text):
    # Strip markdown fences if model ignored instructions
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    data = json.loads(text)
    # Sanitize
    if not isinstance(data.get("tags"), list):
        data["tags"] = []
    data["title"] = str(data.get("title", "Untitled"))[:95]
    data["description"] = str(data.get("description", ""))
    return data
