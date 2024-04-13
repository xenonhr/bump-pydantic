from typing import Any

import pytest
from libcst import MetadataWrapper, parse_module
from libcst.codemod import CodemodContext, CodemodTest
from libcst.metadata import FullRepoManager

from bump_pydantic.codemods.class_def_visitor import ClassDefVisitor
from bump_pydantic.codemods.replace_imports import ReplaceImportsCodemod

DEFAULT_PATH = "foo.py"

class TestReplaceImportsCommand(CodemodTest):
    TRANSFORM = ReplaceImportsCodemod

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

    def test_base_settings(self) -> None:
        before = """
        from pydantic import BaseSettings
        """
        after = """
        from pydantic_settings import BaseSettings
        """
        self.assertCodemod(before, after)

    def test_noop_base_settings(self) -> None:
        code = """
        from potato import BaseSettings
        """
        self.assertCodemod(code, code)

    @pytest.mark.xfail(reason="To be implemented.")
    def test_base_settings_as(self) -> None:
        before = """
        from pydantic import BaseSettings as Potato
        """
        after = """
        from pydantic_settings import BaseSettings as Potato
        """
        self.assertCodemod(before, after)

    def test_color(self) -> None:
        before = """
        from pydantic import Color
        """
        after = """
        from pydantic_extra_types.color import Color
        """
        self.assertCodemod(before, after)

    def test_color_full(self) -> None:
        before = """
        from pydantic.color import Color
        """
        after = """
        from pydantic_extra_types.color import Color
        """
        self.assertCodemod(before, after)

    def test_noop_color(self) -> None:
        code = """
        from potato import Color
        """
        self.assertCodemod(code, code)

    def test_payment_card_number(self) -> None:
        before = """
        from pydantic import PaymentCardNumber
        """
        after = """
        from pydantic_extra_types.payment import PaymentCardNumber
        """
        self.assertCodemod(before, after)

    def test_payment_card_brand(self) -> None:
        before = """
        from pydantic.payment import PaymentCardBrand
        """
        after = """
        from pydantic_extra_types.payment import PaymentCardBrand
        """
        self.assertCodemod(before, after)

    def test_noop_payment_card_number(self) -> None:
        code = """
        from potato import PaymentCardNumber
        """
        self.assertCodemod(code, code)

    def test_noop_payment_card_brand(self) -> None:
        code = """
        from potato import PaymentCardBrand
        """
        self.assertCodemod(code, code)

    def test_both_payment(self) -> None:
        before = """
        from pydantic.payment import PaymentCardNumber, PaymentCardBrand
        """
        after = """
        from pydantic_extra_types.payment import PaymentCardBrand, PaymentCardNumber
        """
        self.assertCodemod(before, after)

    def test_typed_dict_with_model(self) -> None:
        before = """
        from typing import TypedDict
        from pydantic import BaseModel

        class PotatoDict(TypedDict):
            a: int
            b: str

        class Potato(BaseModel):
            data: PotatoDict
        """
        after = """
        from pydantic import BaseModel
        from typing_extensions import TypedDict

        class PotatoDict(TypedDict):
            a: int
            b: str

        class Potato(BaseModel):
            data: PotatoDict
        """
        self.assertCodemod(before, after)

    def test_typed_dict_nop_without_model(self) -> None:
        code = """
        from typing import TypedDict

        pass
        """
        self.assertCodemod(code, code)
