from libcst.codemod import CodemodTest

from bump_pydantic.codemods.root_model import RootModelCommand


class TestReplaceConfigCommand(CodemodTest):
    TRANSFORM = RootModelCommand

    def test_root_model(self) -> None:
        before = """
        from pydantic import BaseModel

        class Potato(BaseModel):
            __root__ = int
        """
        after = """
        from pydantic import RootModel

        class Potato(RootModel[int]):
            pass
        """
        self.assertCodemod(before, after)

    def test_noop(self) -> None:
        code = """
        from pydantic import BaseModel

        class Potato(BaseModel):
            pass
        """
        self.assertCodemod(code, code)

    def test_multiple_root_models(self) -> None:
        before = """
        from pydantic import BaseModel

        class Potato(BaseModel):
            __root__ = int

        class Carrot(BaseModel):
            __root__ = str
        """
        after = """
        from pydantic import RootModel

        class Potato(RootModel[int]):
            pass

        class Carrot(RootModel[str]):
            pass
        """
        self.assertCodemod(before, after)

    def test_root_model_annotated(self) -> None:
        before = """
        from pydantic import BaseModel, Field

        class Potato(BaseModel):
            __root__: Annotated[str, Field(pattern="((^[+-]?[0-9]*\\.?[0-9]+$)|(<\\+.+>.*))")]
        """
        after = """
        from pydantic import RootModel, Field

        class Potato(RootModel[Annotated[str, Field(pattern="((^[+-]?[0-9]*\\.?[0-9]+$)|(<\\+.+>.*))")]]):
            pass
        """
        self.assertCodemod(before, after)

    def test_root_model_annotated_value(self) -> None:
        before = """
        from pydantic import BaseModel, Field

        class Potato(BaseModel):
            __root__: Any = None
        """
        after = """
        from pydantic import RootModel, Field

        class Potato(RootModel[Any]):
            root: Any = None
        """
        self.assertCodemod(before, after)

    def test_root_member(self) -> None:
        before = """
        from pydantic import BaseModel, Field

        class Potato(BaseModel):
            __root__: str

        potato = Potato(__root__="hi")
        r = potato.__root__
        """
        after = """
        from pydantic import RootModel, Field

        class Potato(RootModel[str]):
            pass

        potato = Potato(root="hi")
        r = potato.root
        """
        self.assertCodemod(before, after)
