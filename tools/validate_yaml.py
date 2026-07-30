"""Validate the YAML files required by the Home Assistant app repository."""

from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).parents[1]
FILES = (
    ROOT / "repository.yaml",
    ROOT / "ha_ai_maintainer" / "config.yaml",
    ROOT / "ha_ai_maintainer" / "translations" / "en.yaml",
    ROOT / "ha_ai_maintainer" / "translations" / "hu.yaml",
)


def main() -> int:
    for path in FILES:
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
        if not isinstance(data, dict):
            raise ValueError(f"{path} must contain a YAML mapping")

    config = yaml.safe_load(FILES[1].read_text(encoding="utf-8"))
    required = {"name", "version", "slug", "description", "arch"}
    missing = required.difference(config)
    if missing:
        raise ValueError(f"config.yaml missing: {', '.join(sorted(missing))}")
    if config.get("homeassistant_api") is not True:
        raise ValueError("homeassistant_api must remain enabled")
    forbidden = {"docker_api", "full_access", "privileged"}
    enabled_forbidden = [key for key in forbidden if config.get(key)]
    if enabled_forbidden:
        raise ValueError(
            "unsafe permissions enabled: " + ", ".join(sorted(enabled_forbidden))
        )
    print("YAML validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
