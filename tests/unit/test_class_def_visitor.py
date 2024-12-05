
from typing import Any

import libcst as cst
from libcst.codemod import CodemodContext, CodemodTest
from libcst.helpers import calculate_module_and_package
from libcst.metadata import FullRepoManager, MetadataWrapper
from libcst.testing.utils import UnitTest

from bump_pydantic.codemods.class_def_visitor import ClassDefVisitor


class TestClassDefVisitor(UnitTest):
    def gather_class_def(self, file_path_and_code: list[tuple[str, str]]) -> ClassDefVisitor:
        paths = [file_path for file_path, _ in file_path_and_code]
        metadata_manager = FullRepoManager("", paths, providers=ClassDefVisitor.METADATA_DEPENDENCIES)
        metadata_manager.resolve_cache()
        scratch: dict[str, Any] = {}
        for file_path, code in file_path_and_code:
            module_and_package = calculate_module_and_package("", file_path)
            context = CodemodContext(
                metadata_manager=metadata_manager,
                filename=file_path,
                full_module_name=module_and_package.name,
                full_package_name=module_and_package.package,
                scratch=scratch,
            )
            visitor = ClassDefVisitor(context=context)
            cache = metadata_manager.get_cache_for_path(file_path)
            module = cst.parse_module(CodemodTest.make_fixture_data(code))
            wrapper = MetadataWrapper(module, cache=cache)
            wrapper.visit(visitor)
        return visitor

    def test_no_annotations(self) -> None:
        visitor = self.gather_class_def([(
            "some/test/module.py",
            """
            def foo() -> None:
                pass
            """,
        )])
        results = visitor.context.scratch[ClassDefVisitor.BASE_MODEL_CONTEXT_KEY].known_members
        self.assertEqual(results, {"pydantic.BaseModel", "pydantic.main.BaseModel"})

    def test_without_bases(self) -> None:
        visitor = self.gather_class_def([(
            "some/test/module.py",
            """
            class Foo:
                pass
            """,
        )])
        results = visitor.context.scratch[ClassDefVisitor.BASE_MODEL_CONTEXT_KEY].known_members
        self.assertEqual(results, {"pydantic.BaseModel", "pydantic.main.BaseModel"})

    def test_with_class_defs(self) -> None:
        visitor = self.gather_class_def([(
            "some/test/module.py",
            """
            from pydantic import BaseModel

            class Foo(BaseModel):
                pass

            class Bar(Foo):
                pass
            """,
        )])
        results = visitor.context.scratch[ClassDefVisitor.BASE_MODEL_CONTEXT_KEY].known_members
        self.assertEqual(
            results, {"pydantic.BaseModel", "pydantic.main.BaseModel", "some.test.module.Foo", "some.test.module.Bar"}
        )

    def test_with_pydantic_base_model(self) -> None:
        visitor = self.gather_class_def([(
            "some/test/module.py",
            """
            import pydantic

            class Foo(pydantic.BaseModel):
                ...
            """,
        )])
        results = visitor.context.scratch[ClassDefVisitor.BASE_MODEL_CONTEXT_KEY].known_members
        self.assertEqual(results, {"pydantic.BaseModel", "pydantic.main.BaseModel", "some.test.module.Foo"})

    def test_with_cross_module(self) -> None:
        visitor = self.gather_class_def([(
            "some/test/module.py",
            """
            import some.test.other_module

            class Foo(some.test.other_module.Bar):
                ...
            """,
        ),(
            "some/test/other_module.py",
            """
            import some.test.third_module

            class Bar(some.test.third_module.Baz):
                ...
            """,
        ),(
            "some/test/third_module.py",
            """
            import pydantic

            class Baz(pydantic.BaseModel):
                ...
            """,
        )])
        results = visitor.context.scratch[ClassDefVisitor.BASE_MODEL_CONTEXT_KEY].known_members
        self.assertEqual(results, {"pydantic.BaseModel", "pydantic.main.BaseModel", "some.test.module.Foo", "some.test.other_module.Bar", "some.test.third_module.Baz"})
