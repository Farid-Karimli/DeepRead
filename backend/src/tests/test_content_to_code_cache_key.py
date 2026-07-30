from src.server import _content_to_code_cache_key


BASE = {
    "paper_id": "paper-1",
    "user_id": 7,
    "content": "The target encoder uses an exponential moving average.",
    "repo_url": "https://github.com/example/repo",
    "context": "Method section",
}


def test_content_to_code_cache_key_is_deterministic_and_user_paper_scoped():
    key = _content_to_code_cache_key(**BASE)

    assert key == "5371cf96ff830f984d537f3073848a02874aee02e37f59cb16e2760cab799427"
    assert key == _content_to_code_cache_key(**BASE)
    assert key != _content_to_code_cache_key(**{**BASE, "user_id": 8})
    assert key != _content_to_code_cache_key(**{**BASE, "paper_id": "paper-2"})
