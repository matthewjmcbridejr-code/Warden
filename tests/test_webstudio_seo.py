from pathlib import Path

from warden.webstudio.seo import check_html, check_site_files


GOOD_HTML = """
<html>
<head>
  <title>Marius WebStudio — Local AI Webmaster</title>
  <meta name="description" content="Marius WebStudio helps SMBs manage websites with a local-first AI agent.">
  <link rel="canonical" href="https://usemarius.com/">
  <meta property="og:title" content="Marius WebStudio">
  <meta property="og:description" content="Local-first AI webmaster for SMB sites.">
  <meta property="og:image" content="https://usemarius.com/og.png">
  <script type="application/ld+json">
  {"@context": "https://schema.org", "@type": "LocalBusiness", "name": "Marius WebStudio"}
  </script>
</head>
<body></body>
</html>
"""

BARE_HTML = "<html><head></head><body>No metadata here.</body></html>"


def test_check_html_detects_all_fields() -> None:
    result = check_html(GOOD_HTML)
    assert result.title == "Marius WebStudio — Local AI Webmaster"
    assert result.meta_description is not None
    assert result.canonical == "https://usemarius.com/"
    assert result.og_title == "Marius WebStudio"
    assert result.has_json_ld is True
    assert result.has_local_business_schema is True
    assert result.issues == []


def test_check_html_flags_missing_fields() -> None:
    result = check_html(BARE_HTML)
    assert result.title is None
    assert "missing <title>" in result.issues
    assert "missing meta description" in result.issues
    assert "missing canonical link" in result.issues
    assert "missing JSON-LD structured data" in result.issues


def test_check_site_files_detects_present_files(tmp_path: Path) -> None:
    (tmp_path / "public").mkdir()
    (tmp_path / "public" / "robots.txt").write_text("User-agent: *", encoding="utf-8")
    result = check_site_files(tmp_path)
    assert result["robots_txt"] == "public/robots.txt"
    assert result["sitemap_xml"] is None
    assert "missing sitemap.xml" in result["issues"]
