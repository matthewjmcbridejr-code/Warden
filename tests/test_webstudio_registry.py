from pathlib import Path

import pytest

from warden.webstudio.registry import RegistryError, get_site, load_registry


def test_valid_registry_loads(tmp_path: Path) -> None:
    registry_path = tmp_path / "sites.yaml"
    registry_path.write_text(
        """
sites:
  - name: demo-site
    domain: demo.example.com
    repo_path: /tmp/demo-site
    package_manager: pnpm
""".strip(),
        encoding="utf-8",
    )
    sites = load_registry(registry_path)
    assert len(sites) == 1
    assert sites[0].name == "demo-site"
    assert sites[0].package_manager == "pnpm"
    assert sites[0].production_branch == "main"


def test_get_site_returns_named_entry(tmp_path: Path) -> None:
    registry_path = tmp_path / "sites.yaml"
    registry_path.write_text(
        """
sites:
  - name: site-a
    domain: a.example.com
    repo_path: /tmp/a
  - name: site-b
    domain: b.example.com
    repo_path: /tmp/b
""".strip(),
        encoding="utf-8",
    )
    site = get_site("site-b", registry_path)
    assert site.domain == "b.example.com"


def test_missing_registry_file_fails_cleanly(tmp_path: Path) -> None:
    with pytest.raises(RegistryError):
        load_registry(tmp_path / "does-not-exist.yaml")


def test_invalid_yaml_fails_cleanly(tmp_path: Path) -> None:
    registry_path = tmp_path / "sites.yaml"
    registry_path.write_text("sites: [this is not: valid: yaml", encoding="utf-8")
    with pytest.raises(RegistryError):
        load_registry(registry_path)


def test_missing_sites_key_fails_cleanly(tmp_path: Path) -> None:
    registry_path = tmp_path / "sites.yaml"
    registry_path.write_text("not_sites: []", encoding="utf-8")
    with pytest.raises(RegistryError):
        load_registry(registry_path)


def test_invalid_site_entry_fails_cleanly(tmp_path: Path) -> None:
    registry_path = tmp_path / "sites.yaml"
    registry_path.write_text(
        """
sites:
  - name: bad site!
    domain: bad.example.com
    repo_path: /tmp/bad
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(RegistryError):
        load_registry(registry_path)


def test_duplicate_site_names_fail_cleanly(tmp_path: Path) -> None:
    registry_path = tmp_path / "sites.yaml"
    registry_path.write_text(
        """
sites:
  - name: dup
    domain: a.example.com
    repo_path: /tmp/a
  - name: dup
    domain: b.example.com
    repo_path: /tmp/b
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(RegistryError):
        load_registry(registry_path)


def test_unknown_package_manager_fails_cleanly(tmp_path: Path) -> None:
    registry_path = tmp_path / "sites.yaml"
    registry_path.write_text(
        """
sites:
  - name: site
    domain: a.example.com
    repo_path: /tmp/a
    package_manager: cargo
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(RegistryError):
        load_registry(registry_path)
