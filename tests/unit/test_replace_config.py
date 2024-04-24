from typing import Any

import pytest
from libcst import MetadataWrapper, parse_module
from libcst.codemod import CodemodContext, CodemodTest
from libcst.metadata import FullRepoManager

from bump_pydantic.codemods.class_def_visitor import ClassDefVisitor
from bump_pydantic.codemods.replace_config import ReplaceConfigCodemod

DEFAULT_PATH = "foo.py"

class TestReplaceConfigCommand(CodemodTest):
    TRANSFORM = ReplaceConfigCodemod

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


    def test_config(self) -> None:
        before = """
        from pydantic import BaseModel

        class Potato(BaseModel):
            class Config:
                allow_arbitrary_types = True
        """
        after = """
        from pydantic import ConfigDict, BaseModel

        class Potato(BaseModel):
            model_config = ConfigDict(allow_arbitrary_types=True)
        """
        self.assertCodemod(before, after)

    def test_noop_config(self) -> None:
        code = """
        from pydantic import BaseModel

        class Potato:
            class Config:
                allow_mutation = True
        """
        self.assertCodemod(code, code)

    def test_noop_config_with_bases(self) -> None:
        code = """
        from potato import RandomBase

        class Potato(RandomBase):
            class Config:
                allow_mutation = True
        """
        self.assertCodemod(code, code)

    def test_global_config_class(self) -> None:
        code = """
        from pydantic import BaseModel as Potato

        class Config:
            allow_arbitrary_types = True
        """
        self.assertCodemod(code, code)

    def test_reset_config_args(self) -> None:
        before = """
        from pydantic import BaseModel

        class Potato(BaseModel):
            class Config:
                allow_arbitrary_types = True

        potato = Potato()

        class Potato2(BaseModel):
            class Config:
                strict = True
        """
        after = """
        from pydantic import ConfigDict, BaseModel

        class Potato(BaseModel):
            model_config = ConfigDict(allow_arbitrary_types=True)

        potato = Potato()

        class Potato2(BaseModel):
            model_config = ConfigDict(strict=True)
        """
        self.assertCodemod(before, after)

    def test_config_with_non_assign(self) -> None:
        before = """
        from pydantic import BaseModel

        class Potato(BaseModel):
            class Config:
                allow_arbitrary_types = True

                def __init__(self):
                    self.allow_mutation = True
        """
        after = """
        from pydantic import BaseModel

        class Potato(BaseModel):
            # TODO[pydantic]: We couldn't refactor this class, please create the `model_config` manually.
            # Check https://docs.pydantic.dev/dev-v2/migration/#changes-to-config for more information.
            class Config:
                allow_arbitrary_types = True

                def __init__(self):
                    self.allow_mutation = True
        """
        self.assertCodemod(before, after)

    def test_inherited_config(self) -> None:
        before = """
        from pydantic import BaseModel

        from potato import SuperConfig

        class Potato(BaseModel):
            class Config(SuperConfig):
                allow_arbitrary_types = True
        """
        after = """
        from pydantic import BaseModel

        from potato import SuperConfig

        class Potato(BaseModel):
            # TODO[pydantic]: The `Config` class inherits from another class, please create the `model_config` manually.
            # Check https://docs.pydantic.dev/dev-v2/migration/#changes-to-config for more information.
            class Config(SuperConfig):
                allow_arbitrary_types = True
        """
        self.assertCodemod(before, after)

    @pytest.mark.xfail(reason="Comments inside Config are swallowed.")
    def test_inner_comments(self) -> None:
        before = """
        from pydantic import BaseModel

        class Potato(BaseModel):
            class Config:
                # This is a comment
                allow_arbitrary_types = True
        """
        after = """
        from pydantic import BaseModel

        class Potato(BaseModel):
            model_config = ConfigDict(
                # This is a comment
                allow_arbitrary_types=True
            )
        """
        self.assertCodemod(before, after)

    def test_already_commented(self) -> None:
        before = """
        from pydantic import BaseModel

        from potato import SuperConfig

        class Potato(BaseModel):
            # TODO[pydantic]: The `Config` class inherits from another class, please create the `model_config` manually.
            # Check https://docs.pydantic.dev/dev-v2/migration/#changes-to-config for more information.
            class Config(SuperConfig):
                allow_arbitrary_types = True
        """
        after = """
        from pydantic import BaseModel

        from potato import SuperConfig

        class Potato(BaseModel):
            # TODO[pydantic]: The `Config` class inherits from another class, please create the `model_config` manually.
            # Check https://docs.pydantic.dev/dev-v2/migration/#changes-to-config for more information.
            class Config(SuperConfig):
                allow_arbitrary_types = True
        """
        self.assertCodemod(before, after)

    def test_extra_enum(self) -> None:
        before = """
        from pydantic import BaseModel, Extra

        class Potato(BaseModel):
            class Config:
                extra = Extra.allow
        """
        after = """
        from pydantic import ConfigDict, BaseModel

        class Potato(BaseModel):
            model_config = ConfigDict(extra="allow")
        """
        self.assertCodemod(before, after)

    def test_allow_mutation(self) -> None:
        before = """
        from pydantic import BaseModel

        class Potato(BaseModel):
            class Config:
                allow_mutation = False
        """
        after = """
        from pydantic import ConfigDict, BaseModel

        class Potato(BaseModel):
            model_config = ConfigDict(frozen=True)
        """
        self.assertCodemod(before, after)

    def test_allow_mutation_redundant(self) -> None:
        before = """
        from pydantic import BaseModel

        class Potato(BaseModel):
            class Config:
                allow_mutation = False
                frozen = True
        """
        after = """
        from pydantic import ConfigDict, BaseModel

        class Potato(BaseModel):
            model_config = ConfigDict(frozen=True)
        """
        self.assertCodemod(before, after)

    def test_removed_keys(self) -> None:
        before = """
        from pydantic import BaseModel

        class Potato(BaseModel):
            class Config:
                underscore_attrs_are_private = True
        """
        after = """
        from pydantic import ConfigDict, BaseModel

        class Potato(BaseModel):
            model_config = ConfigDict()
        """
        self.assertCodemod(before, after)

    def test_multiple_removed_keys(self) -> None:
        before = """
        from pydantic import BaseModel

        class Potato(BaseModel):
            class Config:
                underscore_attrs_are_private = True
                smart_union = True
        """
        after = """
        from pydantic import ConfigDict, BaseModel

        class Potato(BaseModel):
            model_config = ConfigDict()
        """
        self.assertCodemod(before, after)

    def test_renamed_keys(self) -> None:
        before = """
        from pydantic import BaseModel

        class Potato(BaseModel):
            class Config:
                orm_mode = True
        """
        after = """
        from pydantic import ConfigDict, BaseModel

        class Potato(BaseModel):
            model_config = ConfigDict(from_attributes=True)
        """
        self.assertCodemod(before, after)

    def test_rename_extra_enum_by_string(self) -> None:
        before = """
        from pydantic import BaseModel, Extra

        class Potato(BaseModel):
            class Config:
                extra = Extra.allow
        """
        after = """
        from pydantic import ConfigDict, BaseModel

        class Potato(BaseModel):
            model_config = ConfigDict(extra="allow")
        """
        self.assertCodemod(before, after)

    def test_noop_extra(self) -> None:
        before = """
        from pydantic import BaseModel
        from potato import Extra

        class Potato(BaseModel):
            class Config:
                extra = Extra.potato
        """
        after = """
        from pydantic import ConfigDict, BaseModel
        from potato import Extra

        class Potato(BaseModel):
            model_config = ConfigDict(extra=Extra.potato)
        """
        self.assertCodemod(before, after)

    def test_extra_inside(self) -> None:
        before = """
        from typing import Type

        from pydantic import BaseModel, Extra

        class Model(BaseModel):
            class Config:
                extra = Extra.allow

            def __init_subclass__(cls: "Type[Model]", **kwargs: Any) -> None:
                class Config:
                    extra = Extra.forbid

                cls.Config = Config  # type: ignore
                super().__init_subclass__(**kwargs)
        """
        after = """
        from typing import Type

        from pydantic import ConfigDict, BaseModel, Extra

        class Model(BaseModel):
            model_config = ConfigDict(extra="allow")

            def __init_subclass__(cls: "Type[Model]", **kwargs: Any) -> None:
                class Config:
                    extra = Extra.forbid

                cls.Config = Config  # type: ignore
                super().__init_subclass__(**kwargs)
        """
        self.assertCodemod(before, after)

    def test_model_field(self) -> None:
        before = """
        from pydantic import BaseModel

        class Potato(BaseModel):
            model_name: str = "potato"
            class Config:
                allow_arbitrary_types = True
        """
        after = """
        from pydantic import ConfigDict, BaseModel

        class Potato(BaseModel):
            model_name: str = "potato"
            model_config = ConfigDict(allow_arbitrary_types=True, protected_namespaces=())
        """
        self.assertCodemod(before, after)

    def test_model_config_field(self) -> None:
        before = """
        from pydantic import BaseModel

        class Potato(BaseModel):
            model_config: str = "potato"

        class Potato2:
            model_config: str = "potato"
        """
        after = """
        from pydantic import BaseModel

        class Potato(BaseModel):
            # TODO[pydantic]: Pydantic 2 reserves the name `model_config`; please rename this field.
            # Check https://docs.pydantic.dev/dev-v2/migration/#changes-to-config for more information.
            model_config: str = "potato"

        class Potato2:
            model_config: str = "potato"
        """
        self.assertCodemod(before, after)
