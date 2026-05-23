from pathlib import Path

from scripts.validate_supabase_resume_readiness import DEFAULT_CONTROL_PLANE_URL


def test_default_control_plane_url_uses_https_for_lab_host() -> None:
    assert DEFAULT_CONTROL_PLANE_URL == "https://192.168.1.166:8787"


def test_main_control_url_default_has_no_cleartext_http_fallback() -> None:
    source = Path("scripts/validate_supabase_resume_readiness.py").read_text(
        encoding="utf-8"
    )
    main_block = source.split("def main()", 1)[1]
    assert '"http://' not in main_block
