import sys
from pathlib import Path


PYTHON_DIR = Path(__file__).resolve().parents[2] / "Python"
sys.path.insert(0, str(PYTHON_DIR))

from export_slices import recommendation_objects
from type_signal_analyzer import ProjectTypeAnalyzer, visible_type_signals


def names(definitions):
    return {item["name"] for item in recommendation_objects(definitions)}


def test_visible_type_signals_cover_annotations_guards_casts_and_constructors():
    source = (
        "from typing import cast\n"
        "def target(value: <mask>, fallback: Response) -> Result:\n"
        "    if isinstance(value, User):\n"
        "        return cast(Product, DatabaseConnection())\n"
    )

    found = names(visible_type_signals(source))

    assert {"Response", "Result", "User", "Product", "DatabaseConnection"} <= found
    assert "TYPEPRO_MASK" not in found


def test_project_index_reads_pyi_and_resolves_relative_reexports(tmp_path):
    project = tmp_path / "project"
    package = project / "models"
    package.mkdir(parents=True)
    (package / "user.pyi").write_text("class User: ...\n", encoding="utf-8")
    (package / "__init__.py").write_text(
        "from .user import User\n", encoding="utf-8"
    )
    consumer = project / "service.py"
    consumer.write_text("from models import User\n", encoding="utf-8")

    analyzer = ProjectTypeAnalyzer(project)
    recommendations = analyzer.recommendations(str(consumer), "unrelated")

    assert "User" in names(recommendations)
    assert any("# source: project_stub" in value for value in analyzer.definitions["User"])


def test_project_index_resolves_star_imports_and_type_checking_blocks(tmp_path):
    project = tmp_path / "project"
    package = project / "models"
    package.mkdir(parents=True)
    (package / "types.py").write_text(
        "class PublicType: pass\nclass _PrivateType: pass\n", encoding="utf-8"
    )
    (package / "__init__.py").write_text(
        "from .types import *\n", encoding="utf-8"
    )
    consumer = project / "consumer.py"
    consumer.write_text(
        "from typing import TYPE_CHECKING\n"
        "from models import *\n"
        "if TYPE_CHECKING:\n"
        "    from models.types import PublicType as CheckedType\n",
        encoding="utf-8",
    )

    analyzer = ProjectTypeAnalyzer(project)
    found = names(analyzer.recommendations(str(consumer), "value"))

    assert {"PublicType", "CheckedType"} <= found
    assert "_PrivateType" not in found


def test_call_graph_propagates_returns_assignments_and_call_arguments(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    source = project / "app.py"
    source.write_text(
        "class User: pass\n"
        "def create_user():\n"
        "    return User()\n"
        "def load_user():\n"
        "    return create_user()\n"
        "def consume(value):\n"
        "    return value\n"
        "def identity(item):\n"
        "    return item\n"
        "current = load_user()\n"
        "consume(current)\n"
        "wrapped = identity(current)\n",
        encoding="utf-8",
    )

    analyzer = ProjectTypeAnalyzer(project)

    assert analyzer.function_returns["load_user"] == {"User"}
    assert "User" in analyzer.variable_types["current"]
    assert "User" in analyzer.parameter_types[("consume", "value")]
    assert "User" in analyzer.function_returns["identity"]
    assert "User" in analyzer.variable_types["wrapped"]
    assert "User" in names(
        analyzer.recommendations(str(source), "value", "consume")
    )


def test_pytest_fixture_and_factory_framework_rules(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    source = project / "test_app.py"
    source.write_text(
        "import pytest\n"
        "from unittest.mock import MagicMock\n"
        "class ApiClient: pass\n"
        "class User: pass\n"
        "class UserFactory:\n"
        "    @classmethod\n"
        "    def create(cls):\n"
        "        return User()\n"
        "@pytest.fixture\n"
        "def client():\n"
        "    return ApiClient()\n"
        "def test_api(client):\n"
        "    user = UserFactory.create()\n"
        "    mocked = MagicMock(spec=ApiClient)\n",
        encoding="utf-8",
    )

    analyzer = ProjectTypeAnalyzer(project)

    assert "ApiClient" in analyzer.parameter_types[("test_api", "client")]
    assert "User" in analyzer.variable_types["user"]
    assert {"MagicMock", "ApiClient"} <= analyzer.variable_types["mocked"]
