"""
Caption generation service.
Uses build_caption_prompt() to compose the prompt, then either:
 - calls a free LLM (if configured), or
 - falls back to a deterministic template (always works, $0, no key needed)
"""

from app.config.social_prompts import build_caption_prompt, PLATFORM_FRAGMENTS


def _template_fallback(platform: str, post_title: str, post_summary: str) -> str:
    """Deterministic, no-AI fallback so the pipeline always works at $0."""
    if platform == "instagram":
        return (
            f"{post_title}\n\n{post_summary}\n\n"
            f"Read the full story - link in bio!\n"
            f"#tech #flyrank #buildinpublic"
        )
    elif platform == "x":
        summary_short = post_summary[:180]
        return f"{post_title}: {summary_short}"
    else:
        raise ValueError(f"Unknown platform: {platform}")


def generate_caption(platform: str, post_title: str, post_summary: str, use_ai: bool = False) -> str:
    """
    Generate a caption for the given platform.
    If use_ai=False (default), uses the free deterministic template.
    If use_ai=True, builds the composed prompt and would call an LLM
    (wire this to Gemini free tier / Ollama when ready).
    """
    prompt = build_caption_prompt(platform, post_title, post_summary)  # always composed, even for fallback path

    if not use_ai:
        return _template_fallback(platform, post_title, post_summary)

    raise NotImplementedError("AI caption path not wired yet - use_ai=False for now")


def generate_all_captions(post_title: str, post_summary: str, use_ai: bool = False) -> dict[str, str]:
    return {
        platform: generate_caption(platform, post_title, post_summary, use_ai)
        for platform in PLATFORM_FRAGMENTS
    }