from tools.osv_tools import (
    parse_package_json,
    parse_package_lock_json,
    parse_poetry_lock,
    parse_pyproject_toml,
    parse_python_requirements,
)


def test_parse_requirements_basic():
    content = """
    requests==2.31.0
    fastapi>=0.115
    # comment
    """
    deps = parse_python_requirements(content)
    assert any(d["name"] == "requests" and d["version"] == "2.31.0" for d in deps)
    assert any(d["name"] == "fastapi" for d in deps)


def test_parse_pyproject_toml():
    content = """
[project]
dependencies = [
  "httpx==0.27.0",
  "pydantic>=2.0"
]

[tool.poetry.dependencies]
python = "^3.11"
uvicorn = "0.30.0"
"""
    deps = parse_pyproject_toml(content)
    names = {d["name"] for d in deps}
    assert "httpx" in names
    assert "pydantic" in names
    assert "uvicorn" in names


def test_parse_poetry_lock():
    content = """
[[package]]
name = "requests"
version = "2.32.3"

[[package]]
name = "urllib3"
version = "2.2.2"
"""
    deps = parse_poetry_lock(content)
    assert any(d["name"] == "requests" and d["version"] == "2.32.3" for d in deps)


def test_parse_package_files():
    pkg = '{"dependencies":{"react":"^18.2.0"},"devDependencies":{"vite":"5.0.1"}}'
    lock = '{"dependencies":{"react":{"version":"18.2.0"}},"packages":{"node_modules/vite":{"version":"5.0.1"}}}'

    deps_pkg = parse_package_json(pkg)
    deps_lock = parse_package_lock_json(lock)

    assert any(d["name"] == "react" for d in deps_pkg)
    assert any(d["name"] == "vite" for d in deps_pkg)
    assert any(d["name"] == "react" and d["version"] == "18.2.0" for d in deps_lock)
