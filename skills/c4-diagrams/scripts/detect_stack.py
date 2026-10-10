from pathlib import Path
import json

try:
    from scripts.repo_index import walk_files
except ImportError:
    from repo_index import walk_files


def _uses_react(package_json_data):
    return "react" in {
        **package_json_data.get("dependencies", {}),
        **package_json_data.get("devDependencies", {}),
        **package_json_data.get("peerDependencies", {})
    }


def detect_stack(repo_path, index=None):
    repo = Path(repo_path)

    indicators = {
        ".NET": (".sln", ".slnx", ".csproj", ".fsproj", ".vbproj"),
        "Node.js": ("package.json",),
        "Python": ("requirements.txt", "pyproject.toml", "setup.py"),
        "Java": ("pom.xml", "build.gradle", "build.gradle.kts"),
        "Go": ("go.mod",)
    }

    if index is not None:
        # Use index views for I/O efficiency
        files = index.files("all")
        suffix_indicators = {k: tuple(v) for k, v in indicators.items()}
        found = [
            stack
            for stack, suffixes in suffix_indicators.items()
            if any(f.suffix == s or f.name.endswith(suffixes) for f in files for s in suffixes)
        ]
        # React check
        for rel in index.by_suffix(".json"):
            if rel.name == "package.json":
                data = index.read_json(rel)
                if data and _uses_react(data):
                    found.append("React")
                    break
    else:
        # Fallback: use walk_files (legacy standalone mode)
        files = list(walk_files(
            repo,
            lambda name: name.endswith(sum(indicators.values(), ()))
        ))
        found = [
            stack
            for stack, suffixes in indicators.items()
            if any(file.name.endswith(suffixes) for file in files)
        ]
        if any(file.name == "package.json" for file in files):
            for file in files:
                if file.name == "package.json":
                    try:
                        data = json.loads(file.read_text(encoding="utf-8"))
                        if _uses_react(data):
                            found.append("React")
                            break
                    except (OSError, ValueError):
                        pass

    return found


if __name__ == "__main__":
    import sys

    repo_path = sys.argv[1]

    stacks = detect_stack(repo_path)

    if stacks:
        print("Detected:")
        for stack in stacks:
            print(f" - {stack}")
    else:
        print("Unknown stack")
