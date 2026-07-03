from pathlib import Path

from warden.webstudio.proof import ProofPack


def test_proof_pack_markdown_contains_key_sections() -> None:
    pack = ProofPack(
        site_name="usemarius",
        domain="usemarius.com",
        repo_path="/tmp/usemarius",
        branch="webstudio/usemarius/update-cta",
        task="Update homepage CTA copy",
        commands_run=[{"args": ["npm", "run", "build"], "ok": True, "duration_seconds": 12.3}],
        build_status="passed",
        test_status="skipped (no tests configured)",
        changed_files=["src/app/page.tsx"],
        screenshots=["desktop.png", "mobile.png"],
        seo_checks={"issues": ["missing og:image"]},
        vercel_preview_url="https://usemarius-preview.vercel.app",
        recommended_next_action="Ship it.",
        client_summary="Homepage CTA updated and verified.",
    )
    markdown = pack.to_markdown()
    assert "# WebStudio Proof Pack — usemarius" in markdown
    assert "usemarius.com" in markdown
    assert "npm run build" in markdown
    assert "src/app/page.tsx" in markdown
    assert "desktop.png" in markdown
    assert "missing og:image" in markdown
    assert "https://usemarius-preview.vercel.app" in markdown
    assert "Ship it." in markdown


def test_proof_pack_write_creates_file(tmp_path: Path) -> None:
    pack = ProofPack(site_name="demo", domain="demo.example.com", repo_path="/tmp/demo")
    path = pack.write(tmp_path)
    assert path.exists()
    assert path.read_text(encoding="utf-8").startswith("# WebStudio Proof Pack — demo")
