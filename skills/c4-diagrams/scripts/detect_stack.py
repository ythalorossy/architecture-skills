"""
The technology stack line: the languages and frameworks a repository uses.

Read from manifests rather than from file extensions, so a repository is
called Python because it has Python source and a Python manifest, not because
something pinned a Sphinx build in a docs/requirements.txt. The result is the
one-line summary at the top of the report and in summary.json.
"""
from pathlib import Path

try:
    from scripts.repo_index import RepoIndex
except ImportError:
    from repo_index import RepoIndex


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
        "Python": ("pyproject.toml", "setup.py"),
        "Java": ("pom.xml", "build.gradle", "build.gradle.kts"),
        "Go": ("go.mod",)
    }

    index = RepoIndex.ensure(index, repo)
    files = index.files()

    def has(*suffixes):
        return any(f.name.endswith(suffixes) for f in files)

    found = []
    for stack, suffixes in indicators.items():
        if has(*suffixes):
            found.append(stack)
        elif stack == "Python" and has("requirements.txt") and has(".py"):
            # A requirements.txt is only evidence of Python with Python source
            # beside it: a lone docs/requirements.txt pins a Sphinx build, and
            # a repository with no .py file is not a Python project.
            found.append(stack)
    for rel in index.by_suffix(".json"):
        if rel.name == "package.json":
            data = index.read_json(rel)
            if data and _uses_react(data):
                found.append("React")
                break

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
