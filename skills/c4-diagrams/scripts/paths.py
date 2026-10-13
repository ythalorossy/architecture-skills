"""
Path and name helpers shared by the ecosystem modules:

- normalize_include  MSBuild backslash paths -> forward slashes
- resolve_include    an include path, relative to a base folder
- local_tag          an XML element's tag without its namespace
- project_group      the folder that holds a project's folder
- TEST_DIRS          folder names whose code is test code
- in_test_dir        True when any of these path parts is a test folder
- GO_EXPANDED_DIRS   Go folders whose second segment names the package group
- GO_MODULE_LINE     the `module x` line of a go.mod
- REQUIREMENTS_FILE  a Python requirements file name
- TOOLING_DIRS       folder names that hold tooling rather than the system
- GENERIC_URL_KEYS   setting names that say "a URL" and nothing else
"""
import re
from pathlib import Path, PurePosixPath

# Code below a folder with one of these names is test code: it is left out
# of components, facts and evidence.
TEST_DIRS = frozenset({"test", "tests", "__tests__", "spec", "specs", "e2e", "testdata"})

# Go repositories put several packages under one of these, so the group a
# package belongs to is its first two segments: services/billing, not
# services. Shared by the component view and the code-structure view.
GO_EXPANDED_DIRS = ("cmd", "internal", "pkg", "api", "app", "services")

# `module example.com/shop` at the top of a go.mod.
GO_MODULE_LINE = re.compile(r"^module\s+(\S+)", re.MULTILINE)

# requirements.txt, requirements-dev.txt, requirements_prod.txt.
REQUIREMENTS_FILE = re.compile(r"requirements.*\.txt$")

# Folders that hold the tooling around a repository rather than the system it
# ships: a release script, a generator, a sample. Used by the guard on inferred
# Python source roots, so a Go repository with a `hack/gen.py` is not reported
# as having a Python project.
TOOLING_DIRS = frozenset({
    "scripts", "script", "tools", "tooling", "build", "ci", "hack", "bin",
    "examples", "example", "samples", "sample", "docs", "doc",
})

# Setting names that only say "this is a URL". When one is the last part of
# a configuration key, the key above it is what names the thing.
GENERIC_URL_KEYS = frozenset({
    "url", "uri", "urls", "baseurl", "base-url", "base_url",
    "apiurl", "api-url", "api_url", "endpoint", "host", "address",
})


def in_test_dir(parts) -> bool:
    """True when any of ``parts`` is a test folder, whatever case it is written in."""
    return any(str(part).lower() in TEST_DIRS for part in parts)


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
