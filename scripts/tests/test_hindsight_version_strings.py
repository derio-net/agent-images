from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGE = REPO_ROOT / "hermes-agent-shell-hindsight"


def test_dockerfile_declares_api_version():
    assert "ARG HINDSIGHT_API_VERSION=" in (IMAGE / "Dockerfile").read_text()
