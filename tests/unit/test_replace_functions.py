from typing import Any

from libcst import MetadataWrapper, parse_module
from libcst.codemod import CodemodContext, CodemodTest
from libcst.metadata import FullRepoManager

from bump_pydantic.codemods.class_def_visitor import ClassDefVisitor
from bump_pydantic.codemods.replace_functions import ReplaceFunctionsCodemod

DEFAULT_PATH = "foo.py"

class TestReplaceFunctions(CodemodTest):
    TRANSFORM = ReplaceFunctionsCodemod

    def test_replace_parse_obj_as(self) -> None:
        before = """
        from typing import List

        from pydantic import BaseModel, parse_obj_as

        class User(BaseModel):
            name: str

        class Users(BaseModel):
            users: List[User]

        users = parse_obj_as(Users, {'users': [{'name': 'John'}]})
        """
        after = """
        from typing import List

        from pydantic import TypeAdapter, BaseModel

        class User(BaseModel):
            name: str

        class Users(BaseModel):
            users: List[User]

        users = TypeAdapter(Users).validate_python({'users': [{'name': 'John'}]})
        """
        self.assertCodemod(before, after)

    def test_replace_parse_raw_as(self) -> None:
        before = """
        from typing import List

        from pydantic import BaseModel, parse_raw_as

        class User(BaseModel):
            name: str

        class Users(BaseModel):
            users: List[User]

        users = parse_raw_as(Users, some_json_string)
        """
        after = """
        from typing import List

        from pydantic import TypeAdapter, BaseModel

        class User(BaseModel):
            name: str

        class Users(BaseModel):
            users: List[User]

        users = TypeAdapter(Users).validate_json(some_json_string)
        """
        self.assertCodemod(before, after)

    def test_replace_json_loads_dump(self) -> None:
        before = """
        from typing import List

        from pydantic import BaseModel

        class User(BaseModel):
            name: str

        jsonable_user = json.loads(User(name="Bob").model_dump_json())
        """
        after = """
        from typing import List

        from pydantic import BaseModel

        class User(BaseModel):
            name: str

        jsonable_user = User(name="Bob").model_dump(mode="json")
        """
        self.assertCodemod(before, after)

    def test_replace_moved(self) -> None:
        before = """
        from typing import List

        from pydantic import validate_arguments

        @validate_arguments
        def foo(x: int) -> int:
            return x

        pydantic.utils.deep_update({'a': 1}, {'b': 2})
        """
        after = """
        from typing import List

        from pydantic import validate_arguments
        import pydantic.v1.utils
        from pydantic.deprecated.decorator import validate_arguments

        @validate_arguments
        def foo(x: int) -> int:
            return x

        pydantic.v1.utils.deep_update({'a': 1}, {'b': 2})
        """
        self.assertCodemod(before, after)

    def test_replace_extra_1(self) -> None:
        before = """
        import pydantic

        class Extra:
            allow = "allow"

        extra = pydantic.Extra.allow
        non_extra = Extra.allow
        """
        after = """
        import pydantic

        class Extra:
            allow = "allow"

        extra = "allow"
        non_extra = Extra.allow
        """
        self.assertCodemod(before, after)

    def test_replace_extra_2(self) -> None:
        before = """
        from pydantic import Extra

        extra = Extra.allow
        """
        after = """
        extra = "allow"
        """
        self.assertCodemod(before, after)
