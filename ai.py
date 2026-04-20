"""
AI metadata generation. Sends transcript (or hint), gets back {title, description, tags}.
Uses Anthropic by default (set ANTHROPIC_API_KEY). Falls back to OpenAI if
OPENAI_API_KEY is set instead.
"""
import json
import os
import re

SYSTEM_PROMPT = """You are a YouTube SEO expert. Given either a full video transcript
or a short topic hint, produce:
1. A click-worthy SEO title (max 90 chars, no clickbait lies)
2. A detailed description (2-3 paragraphs, written in first person like "In this video I...")
   - Start with a hook
   - Cover the main points
   - End with 3-5 relevant hashtags (#example)
3. A list of 15-25 YouTube tags (comma-separated strings, each tag 1-4 words)

CRITICAL: Respond with ONLY valid JSON, no markdown fences, no preamble. Schema:
{
  "title": "string",
  "description": "string",
  "tags": ["tag1", "tag2", ...]
}"""


def generate_metadata(transcript="", channel_hint="", video_hint=""):
    """
    Returns dict {title, description, tags}.

    - transcript: full transcript text (with_script mode). Primary source.
    - channel_hint: persistent channel context from config.yaml.
    - video_hint: one-off per-video hint from the editor (with_hint mode).

    At least one of transcript or video_hint should be non-empty for useful output.
    """
    transcript = (transcript or "")[:80000]  # stay under context limits
    parts = []
    if channel_hint:
        parts.append(f"Channel context: {channel_hint}")
    if video_hint:
        parts.append(f"Editor's note for this video: {video_hint}")
    if transcript:
        parts.append(f"Transcript:\n{transcript}")
    user_msg = "\n\n".join(parts) if parts else "Generate generic metadata for an untitled video."

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
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    data = json.loads(text)
    if not isinstance(data.get("tags"), list):
        data["tags"] = []
    data["title"] = str(data.get("title", "Untitled"))[:95]
    data["description"] = str(data.get("description", ""))
    return data
