from typing import Any

from libcst import MetadataWrapper, parse_module
from libcst.codemod import CodemodContext, CodemodTest
from libcst.metadata import FullRepoManager

from bump_pydantic.codemods.add_missing_annotation import AddMissingAnnotationCommand
from bump_pydantic.codemods.class_def_visitor import ClassDefVisitor

DEFAULT_PATH = "foo.py"

class TestAddMissingAnnotation(CodemodTest):
    TRANSFORM = AddMissingAnnotationCommand

    maxDiff = None

    def setUp(self) -> None:
        scratch = {}
        providers = [*self.TRANSFORM.METADATA_DEPENDENCIES, *ClassDefVisitor.METADATA_DEPENDENCIES]
        metadata_manager = FullRepoManager(".", [DEFAULT_PATH], providers=providers)  # type: ignore[arg-type]
        metadata_manager.resolve_cache()
        context = CodemodContext(
            metadata_manager=metadata_manager,
            filename=DEFAULT_PATH,
            # full_module_name=module_and_package.name,
            # full_package_name=module_and_package.package,
            scratch=scratch,
        )

        self.context = context
        return super().setUp()

    def assertCodemod(
        self,
        before: str,
        after: str,
        *args: Any,
        **kwargs: Any) -> None:
        mod = MetadataWrapper(
            parse_module(CodemodTest.make_fixture_data(before)), True,
            cache=self.context.metadata_manager.get_cache_for_path(DEFAULT_PATH),
        )
        instance = ClassDefVisitor(context=self.context)
        mod.visit(instance)
        super().assertCodemod(before, after, *args, context_override=self.context, **kwargs)

    def test_no_change(self) -> None:
        code = """
        from pydantic import BaseModel

        class Potato(BaseModel):
            price: int
        """
        self.assertCodemod(code, code)

    def test_add_annotation(self) -> None:
        before = """
        from pydantic import BaseModel

        class Potato(BaseModel):
            price = 5
            name = "Russet"
        """
        after = """
        from pydantic import BaseModel

        class Potato(BaseModel):
            price: int = 5
            name: str = "Russet"
        """
        self.assertCodemod(before, after)

    def test_cannot_add_annotation(self) -> None:
        before = """
        from pydantic import BaseModel

        class Potato(BaseModel):
            prices = [5, 6, 7]
        """
        after = """
        from pydantic import BaseModel

        class Potato(BaseModel):
            # TODO[pydantic]: all model fields must have a type annotation.
            prices = [5, 6, 7]
        """
        self.assertCodemod(before, after)
