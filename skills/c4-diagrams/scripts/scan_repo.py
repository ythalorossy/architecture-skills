from pathlib import Path
import json

try:
    from scripts.repo_index import is_ignored_dir
    from scripts.projects import discover_all
except ImportError:
    from repo_index import is_ignored_dir
    from projects import discover_all


def scan_repo(repo_path, index=None, discovery=None):
    repo = Path(repo_path).resolve()

    if discovery is None:
        discovery = discover_all(repo, index)

    projects = [
        {
            "name": project["id"],
            "path": project["relative_path"],
            "group": project["group"],
            "ecosystem": project["ecosystem"],
            "in_solution": project["in_solution"],
            "duplicate_name": project["duplicate_name"]
        }
        for project in discovery["projects"]
    ]

    folders = sorted(
        folder.name
        for folder in repo.iterdir()
        if folder.is_dir() and not is_ignored_dir(folder.name)
    )

    scan_results = {
        "solutions": discovery["solutions"],
        "projects": projects,
        "orphan_projects": [
            project["path"]
            for project in projects
            if project["in_solution"] is False
        ],
        "duplicate_project_names": sorted({
            project["name"]
            for project in discovery["projects"]
            if project["duplicate_name"]
        }),
        "folders": folders
    }
    return scan_results, discovery


if __name__ == "__main__":
    import sys

    result = scan_repo(sys.argv[1])

    print(json.dumps(result, indent=2))
