import json
from anthropic import Anthropic

from app.config import settings


def analyze_transcript(transcript: str, video_duration: float, context: str = None, minimal_cuts: bool = False) -> dict:
    """
    Use Claude to analyze transcript and generate:
    - Cut plan (which segments to keep)
    - Title suggestions
    - Description
    - Hashtags
    - Hook/opening line
    """
    client = Anthropic(api_key=settings.anthropic_api_key)

    if context:
        context_section = f"""
CRITICAL INSTRUCTION - READ CAREFULLY:
The creator has described what this video is about:
"{context}"

YOU MUST USE ONLY THIS DESCRIPTION for generating titles, descriptions, hooks, and hashtags.

The transcript below contains SPEECH RECOGNITION ERRORS - especially the word "perhoja/perhonen" (butterflies)
which is a MISHEARD WORD and has NOTHING to do with the actual video content.

DO NOT mention butterflies, fishing lures, or any other topic not explicitly in the creator's description above.
ONLY use the transcript for identifying timestamps and cut points, NOT for understanding content.
"""
    else:
        context_section = ""

    prompt = f"""Analyze this video transcript and help create a short-form video (reel/short) for social media.
{context_section}
TRANSCRIPT (auto-generated, may have errors):
{transcript}

VIDEO DURATION: {video_duration:.1f} seconds

Please analyze the content and provide:

1. CUT_PLAN: Identify segments to KEEP for the final video.
   {"MINIMAL CUTS MODE: Keep EVERYTHING except completely dead silence (5+ seconds of nothing happening). Mark nearly all segments as keep:true." if minimal_cuts else "Be VERY CONSERVATIVE. Only cut long dead silences (3+ seconds of nothing) or walking/moving with no talking."}

   KEEP all of these (they make content feel genuine):
   - Fumbles, stutters, self-corrections - these are AUTHENTIC
   - Brief pauses - natural speech has pauses
   - "Um", "uh", thinking moments - real people do this
   - Mistakes followed by corrections - shows genuine unscripted content

   ONLY cut:
   - Long silence with nothing happening (3-5+ seconds)
   - Walking/transition shots with no audio

   If video is under 90 seconds, probably keep ALL of it.
   When in doubt, KEEP IT.

2. TITLE: A catchy title for the short (max 100 chars)

3. DESCRIPTION: A brief description for social media (2-3 sentences max)

4. HASHTAGS: 5-10 relevant hashtags

5. HOOK: The opening hook/first line that grabs attention

Respond in this exact JSON format with BOTH Finnish and English versions:
{{
    "cut_plan": {{
        "segments": [
            {{"start": 0.0, "end": 10.5, "keep": true, "reason": "Strong opening"}},
            {{"start": 10.5, "end": 15.0, "keep": false, "reason": "Filler/pause"}},
            ...
        ],
        "estimated_final_duration": 45.0
    }},
    "title_fi": "Otsikko suomeksi",
    "title_en": "Title in English",
    "description_fi": "Kuvaus suomeksi",
    "description_en": "Description in English",
    "hashtags": ["hashtag1", "hashtag2", ...],
    "hook_fi": "Koukku suomeksi",
    "hook_en": "Hook in English"
}}

Only respond with valid JSON, no other text."""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    # Parse JSON from response
    response_text = response.content[0].text.strip()

    # Try to extract JSON if wrapped in markdown code blocks
    if "```json" in response_text:
        response_text = response_text.split("```json")[1].split("```")[0].strip()
    elif "```" in response_text:
        response_text = response_text.split("```")[1].split("```")[0].strip()

    try:
        result = json.loads(response_text)
    except json.JSONDecodeError:
        # Return a basic structure if parsing fails
        result = {
            "cut_plan": {"segments": [], "estimated_final_duration": video_duration},
            "title": "Untitled",
            "description": transcript[:200] if transcript else "",
            "hashtags": [],
            "hook": "",
            "parse_error": response_text
        }

    return result


def generate_thumbnail_text(title_fi: str, title_en: str, context: str = None) -> dict:
    """Generate text overlay for thumbnail in both Finnish and English."""
    client = Anthropic(api_key=settings.anthropic_api_key)

    context_hint = f"\nVideo context: {context}" if context else ""

    prompt = f"""Create short, punchy text overlays for a video thumbnail in BOTH Finnish and English.

Finnish title: {title_fi}
English title: {title_en}{context_hint}

Requirements:
- Maximum 2-4 words per language
- Should grab attention instantly
- Use action words or create curiosity
- ALL CAPS
- Must be relevant to the actual content

Respond in this exact JSON format:
{{"text_fi": "TEKSTI SUOMEKSI", "text_en": "TEXT IN ENGLISH"}}

Only respond with JSON, nothing else."""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=100,
        messages=[{"role": "user", "content": prompt}]
    )

    response_text = response.content[0].text.strip()

    try:
        import json
        result = json.loads(response_text)
        return result
    except:
        return {"text_fi": "KATSO TÄMÄ", "text_en": "WATCH THIS"}
