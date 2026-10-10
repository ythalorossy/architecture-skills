"""
Shared path helpers — moved out of dotnet_projects.py (CQ-06).

Helpers that were used by multiple modules but lived in dotnet_projects.py:
- normalize_include   (MSBuild backslash normalization)
- resolve_include    (resolve a include path relative to a base dir)
- local_tag         (strip XML namespace from element tag)
- project_group     (folder that holds the project folder)

SPEC-03 CQ-06 / CQ-07.
"""
from pathlib import Path, PurePosixPath


def normalize_include(include: str) -> str:
    """
    Normalize an MSBuild-style include path to POSIX forward-slash separators.

    MSBuild uses backslashes on Windows. This makes include paths usable
    on any OS by replacing ``\\`` with ``/``.
    """
    return include.strip().replace("\\", "/")


def resolve_include(base_dir: Path, include: str) -> Path:
    """
    Resolve an include path relative to ``base_dir``.

    Handles MSBuild backslash normalization via ``normalize_include``.
    Returns an absolute, resolved Path.
    """
    return (Path(base_dir) / normalize_include(include)).resolve()


def local_tag(element) -> str:
    """
    Return the local name of an XML element, stripping any namespace prefix.

    Handles both ``{ns}local`` (ElementTree) and ``prefix:local`` (lxml) forms.

    >>> import xml.etree.ElementTree as ET
    >>> el = ET.fromstring('<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003">')
    >>> local_tag(el)
    'Project'
    """
    tag = element.tag
    # ElementTree: "{http://ns}local"  → split at "}"
    if "}" in tag:
        return tag.split("}", 1)[-1]
    # lxml / generic: "prefix:local"  → split at ":"
    if ":" in tag:
        return tag.split(":", 1)[-1]
    return tag


def project_group(relative_path: str) -> str:
    """
    Return the folder that holds the project folder.

    For a project file at ``src/Domain/X/X.csproj``, returns ``src/Domain``.
    For a project at ``root.csproj`` (fewer than 2 path segments), returns ``""``.

    Examples
    --------
    >>> project_group("src/Domain/X/X.csproj")
    'src/Domain'
    >>> project_group("src/X.csproj")
    ''
    >>> project_group("X.csproj")
    ''
    """
    parts = PurePosixPath(relative_path).parts
    return "/".join(parts[:-2]) if len(parts) > 2 else ""
