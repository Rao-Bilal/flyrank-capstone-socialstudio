from app.services.caption_composer import generate_all_captions

def test_captions_differ_per_platform():
    captions = generate_all_captions(
        post_title="How We Scaled to 1M Requests",
        post_summary="A deep dive into our backend architecture."
    )
    assert "instagram" in captions
    assert "x" in captions
    assert captions["instagram"] != captions["x"]
    assert len(captions["x"]) <= 280