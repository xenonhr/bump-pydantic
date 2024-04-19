from typing import Any

from libcst import MetadataWrapper, parse_module
from libcst.codemod import CodemodContext, CodemodTest
from libcst.metadata import FullRepoManager

from bump_pydantic.codemods.class_def_visitor import ClassDefVisitor
from bump_pydantic.codemods.warn_replaced_overrides import WarnReplacedOverridesCommand

DEFAULT_PATH = "foo.py"

class TestAddMissingAnnotation(CodemodTest):
    TRANSFORM = WarnReplacedOverridesCommand

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

            def foo(self) -> None:
                pass
        """
        self.assertCodemod(code, code)

    def test_warn_old_method(self) -> None:
        before = """
        from pydantic import BaseModel

        class Potato(BaseModel):
            price: int

            def dict(self, **kwargs: Any) -> dict[str, Any]:
                return kwargs
        """
        after = """
        from pydantic import BaseModel

        class Potato(BaseModel):
            price: int

            # TODO[pydantic]: overriding a deprecated model method: `dict` is replaced by `model_dump`.
            # You may need to refactor this and add tests to ensure the intended behavior is preserved.
            # Check https://docs.pydantic.dev/dev-v2/migration/#changes-to-pydanticbasemodel for more information.
            def dict(self, **kwargs: Any) -> dict[str, Any]:
                return kwargs
        """
        self.assertCodemod(before, after)
