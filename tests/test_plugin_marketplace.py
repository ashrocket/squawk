import json
from pathlib import Path


def test_marketplace_points_to_plugin_root():
    repo_root = Path(__file__).resolve().parents[1]
    marketplace_path = repo_root / ".claude-plugin" / "marketplace.json"
    marketplace = json.loads(marketplace_path.read_text())

    assert marketplace["name"] == "squawk"
    [plugin] = marketplace["plugins"]
    assert plugin["name"] == "squawk"
    assert plugin["source"] == "./claude-plugin"

    plugin_root = repo_root / plugin["source"]
    assert (plugin_root / ".claude-plugin" / "plugin.json").is_file()
