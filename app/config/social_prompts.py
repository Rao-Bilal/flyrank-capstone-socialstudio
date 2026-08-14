"""
Composable caption prompt fragments.
Shared brand voice + platform rules + content summary = final prompt per platform.
No near-duplicated prompts per platform - only the platform fragment differs.
"""

BRAND_VOICE = (
    "You are writing social captions for FlyRank, a fast-moving tech brand. "
    "Voice: confident, clear, a little playful. Never use corporate jargon. "
    "Always tie the caption back to the value for the reader."
)

PLATFORM_FRAGMENTS = {
    "instagram": (
        "Platform: Instagram. Style: casual, warm, can use 1-3 relevant emojis. "
        "Max length: 2200 characters. Include a soft call-to-action. "
        "End with 3-5 relevant hashtags on a new line."
    ),
    "x": (
        "Platform: X (Twitter). Style: punchy, concise, no fluff. "
        "Max length: 280 characters INCLUDING any hashtags. "
        "At most 1-2 hashtags. Lead with the hook, not the setup."
    ),
}


def build_caption_prompt(platform: str, post_title: str, post_summary: str) -> str:
    """
    Compose the final prompt for a given platform from shared + platform
    fragments. This is what gets sent to the caption-generation model
    (or used as a template for a hand-written fallback).
    """
    if platform not in PLATFORM_FRAGMENTS:
        raise ValueError(f"Unknown platform: {platform}")

    return (
        f"{BRAND_VOICE}\n\n"
        f"{PLATFORM_FRAGMENTS[platform]}\n\n"
        f"Blog post title: {post_title}\n"
        f"Blog post summary: {post_summary}\n\n"
        f"Write ONE caption only. Do not include quotation marks around it."
    )