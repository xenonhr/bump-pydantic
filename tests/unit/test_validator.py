import pytest
from libcst.codemod import CodemodTest

from bump_pydantic.codemods.validator import ValidatorCodemod


class TestValidatorCommand(CodemodTest):
    TRANSFORM = ValidatorCodemod

    maxDiff = None

    def test_rename_validator_to_field_validator(self) -> None:
        before = """
        import typing as t

        from pydantic import BaseModel, validator


        class Potato(BaseModel):
            name: str
            dialect: str

            @validator("name", "dialect", pre=True)
            def _string_validator(cls, v: t.Any) -> t.Optional[str]:
                if isinstance(v, exp.Expression):
                    return v.name.lower()
                return str(v).lower() if v is not None else None
        """
        after = """
        import typing as t

        from pydantic import field_validator, BaseModel


        class Potato(BaseModel):
            name: str
            dialect: str

            @field_validator("name", "dialect", mode="before")
            @classmethod
            def _string_validator(cls, v: t.Any) -> t.Optional[str]:
                if isinstance(v, exp.Expression):
                    return v.name.lower()
                return str(v).lower() if v is not None else None
        """
        self.assertCodemod(before, after)

    def test_use_model_validator(self) -> None:
        before = """
        import typing as t

        from pydantic import BaseModel, root_validator


        class Potato(BaseModel):
            name: str
            dialect: str

            @root_validator(pre=True)
            def _normalize_fields(cls, values: t.Dict[str, t.Any]) -> t.Dict[str, t.Any]:
                if "gateways" not in values and "gateway" in values:
                    values["gateways"] = values.pop("gateway")
        """
        after = """
        import typing as t

        from pydantic import model_validator, BaseModel


        class Potato(BaseModel):
            name: str
            dialect: str

            @model_validator(mode="before")
            @classmethod
            def _normalize_fields(cls, values: t.Dict[str, t.Any]) -> t.Dict[str, t.Any]:
                if "gateways" not in values and "gateway" in values:
                    values["gateways"] = values.pop("gateway")
        """
        self.assertCodemod(before, after)

    def test_remove_allow_reuse_from_model_validator(self) -> None:
        before = """
        import typing as t

        from pydantic import BaseModel, root_validator


        class Potato(BaseModel):
            name: str
            dialect: str

            @root_validator(pre=True, allow_reuse=True)
            def _normalize_fields(cls, values: t.Dict[str, t.Any]) -> t.Dict[str, t.Any]:
                if "gateways" not in values and "gateway" in values:
                    values["gateways"] = values.pop("gateway")
        """
        after = """
        import typing as t

        from pydantic import model_validator, BaseModel


        class Potato(BaseModel):
            name: str
            dialect: str

            @model_validator(mode="before")
            @classmethod
            def _normalize_fields(cls, values: t.Dict[str, t.Any]) -> t.Dict[str, t.Any]:
                if "gateways" not in values and "gateway" in values:
                    values["gateways"] = values.pop("gateway")
        """
        self.assertCodemod(before, after)

    def test_remove_skip_on_failure_from_model_validator(self) -> None:
        before = """
        import typing as t

        from pydantic import BaseModel, root_validator


        class Potato(BaseModel):
            name: str
            dialect: str

            @root_validator(skip_on_failure=True)
            def _normalize_fields(cls, values: t.Dict[str, t.Any]) -> t.Dict[str, t.Any]:
                if values["name"] == "foo":
                    values["name"] = "bar"
                if values.get("dialect") == "foo":
                    values["dialect"] = "bar"
                return values
        """
        after = """
        import typing as t

        from pydantic import model_validator, BaseModel
        from typing import Self


        class Potato(BaseModel):
            name: str
            dialect: str

            @model_validator(mode="after")
            def _normalize_fields(self) -> Self:
                if self.name == "foo":
                    self.name = "bar"
                if self.dialect == "foo":
                    self.dialect = "bar"
                return self
        """
        self.assertCodemod(before, after)

    def test_replace_validator_with_values(self) -> None:
        before = """
        import typing as t

        from pydantic import BaseModel, validator


        class Potato(BaseModel):
            name_map: t.Dict[str, str]
            name: str

            @validator("name")
            def _string_validator(cls, v: t.Any, values: t.Dict[str, t.Any]) -> t.Optional[str]:
                if v in values["name_map"]:
                    return values["name_map"][v]
                return v
        """
        after = """
        import typing as t

        from pydantic import ValidationInfo, field_validator, BaseModel


        class Potato(BaseModel):
            name_map: t.Dict[str, str]
            name: str

            @field_validator("name")
            @classmethod
            def _string_validator(cls, v: t.Any, info: ValidationInfo) -> t.Optional[str]:
                if v in info.data["name_map"]:
                    return info.data["name_map"][v]
                return v
        """

        self.assertCodemod(before, after)

    def test_replace_validator_with_existing_classmethod(self) -> None:
        before = """
        from pydantic import validator


        class Potato(BaseModel):
            name: str
            dialect: str

            @validator("name", "dialect")
            @classmethod
            def _string_validator(cls, v: t.Any) -> t.Optional[str]:
                if isinstance(v, exp.Expression):
                    return v.name.lower()
                return str(v).lower() if v is not None else None
        """
        after = """
        from pydantic import field_validator


        class Potato(BaseModel):
            name: str
            dialect: str

            @field_validator("name", "dialect")
            @classmethod
            def _string_validator(cls, v: t.Any) -> t.Optional[str]:
                if isinstance(v, exp.Expression):
                    return v.name.lower()
                return str(v).lower() if v is not None else None
        """
        self.assertCodemod(before, after)

    def test_comment_on_validator_that_reassigns_values(self) -> None:
        before = """
        import typing as t

        from pydantic import BaseModel, validator


        class Potato(BaseModel):
            name_map: t.Dict[str, str]
            name: str

            @validator("name")
            def _string_validator(cls, v: t.Any, values: t.Dict[str, t.Any]) -> t.Optional[str]:
                if "name_map" in values:
                    values = values["name_map"]
                if v in values:
                    return values[v]
                return v
        """
        after = """
        import typing as t

        from pydantic import BaseModel, validator


        class Potato(BaseModel):
            name_map: t.Dict[str, str]
            name: str

            # TODO[pydantic]: We couldn't refactor the `validator`, please replace it by `field_validator` manually.
            # Check https://docs.pydantic.dev/dev-v2/migration/#changes-to-validators for more information.
            @validator("name")
            def _string_validator(cls, v: t.Any, values: t.Dict[str, t.Any]) -> t.Optional[str]:
                if "name_map" in values:
                    values = values["name_map"]
                if v in values:
                    return values[v]
                return v
        """

        self.assertCodemod(before, after)

    def test_comment_on_validator_with_multiple_params(self) -> None:
        before = """
        import typing as t

        from pydantic import BaseModel, validator


        class Potato(BaseModel):
            name: str
            dialect: str

            @validator("name", "dialect")
            def _string_validator(cls, v: t.Any, values: t.Dict[str, t.Any], **kwargs) -> t.Optional[str]:
                if isinstance(v, exp.Expression):
                    return v.name.lower()
                return str(v).lower() if v is not None else None
        """
        after = """
        import typing as t

        from pydantic import BaseModel, validator


        class Potato(BaseModel):
            name: str
            dialect: str

            # TODO[pydantic]: We couldn't refactor the `validator`, please replace it by `field_validator` manually.
            # Check https://docs.pydantic.dev/dev-v2/migration/#changes-to-validators for more information.
            @validator("name", "dialect")
            def _string_validator(cls, v: t.Any, values: t.Dict[str, t.Any], **kwargs) -> t.Optional[str]:
                if isinstance(v, exp.Expression):
                    return v.name.lower()
                return str(v).lower() if v is not None else None
        """

        self.assertCodemod(before, after)

    @pytest.mark.xfail(reason="Not implemented yet")
    def test_reuse_model_validator(self) -> None:
        before = """
        from pydantic import root_validator

        expression_validator = root_validator(pre=True)(parse_expression)
        """
        after = """
        from pydantic import model_validator

        expression_validator = model_validator(mode="before")(parse_expression)
        """
        self.assertCodemod(before, after)

    def test_noop_reuse_validator(self) -> None:
        """Since we don't know if the function has one or more parameters, we can't
        safely replace it with `field_validator`.
        """
        code = """
        from pydantic import validator

        expression_validator = validator(
            "query",
            "expressions_",
            "pre_statements_",
            "post_statements_",
            pre=True,
            allow_reuse=True,
            check_fields=False,
        )(parse_expression)
        """
        self.assertCodemod(code, code)

    def test_root_validator_after(self) -> None:
        before = """
        from pydantic import root_validator, BaseModel


        class Potato(BaseModel):
            name: str
            dialect: str

            @root_validator(pre=False)
            def _normalize_fields(cls, values: t.Dict[str, t.Any]) -> t.Dict[str, t.Any]:
                if values["name"] == "foo":
                    values["name"] = "bar"
                if values.get("dialect") == "foo":
                    values["dialect"] = "bar"
                return values
        """
        after = """
        from pydantic import model_validator, BaseModel
        from typing import Self


        class Potato(BaseModel):
            name: str
            dialect: str

            @model_validator(mode="after")
            def _normalize_fields(self) -> Self:
                if self.name == "foo":
                    self.name = "bar"
                if self.dialect == "foo":
                    self.dialect = "bar"
                return self
        """
        self.assertCodemod(before, after)

    def test_replace_validator_without_pre(self) -> None:
        before = """
        from pydantic import validator


        class Potato(BaseModel):
            name: str
            dialect: str

            @validator("name", "dialect")
            def _string_validator(cls, v: t.Any) -> t.Optional[str]:
                if isinstance(v, exp.Expression):
                    return v.name.lower()
                return str(v).lower() if v is not None else None
        """
        after = """
        from pydantic import field_validator


        class Potato(BaseModel):
            name: str
            dialect: str

            @field_validator("name", "dialect")
            @classmethod
            def _string_validator(cls, v: t.Any) -> t.Optional[str]:
                if isinstance(v, exp.Expression):
                    return v.name.lower()
                return str(v).lower() if v is not None else None
        """
        self.assertCodemod(before, after)

    def test_replace_validator_with_pre_false(self) -> None:
        before = """
        from pydantic import validator


        class Potato(BaseModel):
            name: str
            dialect: str

            @validator("name", "dialect", pre=False)
            def _string_validator(cls, v: t.Any) -> t.Optional[str]:
                if isinstance(v, exp.Expression):
                    return v.name.lower()
                return str(v).lower() if v is not None else None
        """
        after = """
        from pydantic import field_validator


        class Potato(BaseModel):
            name: str
            dialect: str

            @field_validator("name", "dialect")
            @classmethod
            def _string_validator(cls, v: t.Any) -> t.Optional[str]:
                if isinstance(v, exp.Expression):
                    return v.name.lower()
                return str(v).lower() if v is not None else None
        """
        self.assertCodemod(before, after)

    def test_replace_validator_with_always(self) -> None:
        before = """
        import pydantic
        from pydantic import BaseModel, Field

        class Potato(BaseModel):
            response_format: str
            text: str = "hi"
            foo: Annotated[str, Field(max_length=256)]
            bar: str = pydantic.Field(default=None)
            baz: int = Field(gt=0, lt=10)
            not_always: str

            @validator("response_format", pre=True, always=True)
            def default_response_format(cls, v):
                x: int
                if v is None:
                    v = "foo"
                return v

            @validator("text", pre=True, always=True)
            def validate_text(cls, v):
                pass

            @validator("foo", pre=True, always=True)
            def validate_foo(cls, v):
                pass

            @validator("bar", pre=True, always=True)
            def validate_bar(cls, v):
                pass

            @validator("baz", pre=True, always=True)
            def validate_baz(cls, v):
                pass

            @validator("not_always", pre=True)
            def validate_not_always(cls, v):
                pass
        """
        after = """
        import pydantic
        from pydantic import field_validator, BaseModel, Field
        from typing import Annotated

        class Potato(BaseModel):
            response_format: Annotated[str, Field(validate_default=True)]
            text: Annotated[str, Field(validate_default=True)] = "hi"
            foo: Annotated[str, Field(max_length=256, validate_default=True)]
            bar: str = pydantic.Field(default=None, validate_default=True)
            baz: int = Field(gt=0, lt=10, validate_default=True)
            not_always: str

            @field_validator("response_format", mode="before")
            @classmethod
            def default_response_format(cls, v):
                x: int
                if v is None:
                    v = "foo"
                return v

            @field_validator("text", mode="before")
            @classmethod
            def validate_text(cls, v):
                pass

            @field_validator("foo", mode="before")
            @classmethod
            def validate_foo(cls, v):
                pass

            @field_validator("bar", mode="before")
            @classmethod
            def validate_bar(cls, v):
                pass

            @field_validator("baz", mode="before")
            @classmethod
            def validate_baz(cls, v):
                pass

            @field_validator("not_always", mode="before")
            @classmethod
            def validate_not_always(cls, v):
                pass
        """
        self.assertCodemod(before, after)

    def test_import_pydantic(self) -> None:
        before = """
        import typing as t

        import pydantic

        class Potato(pydantic.BaseModel):
            name: str
            dialect: str

            @pydantic.root_validator(pre=True)
            def _normalize_fields(cls, values: t.Dict[str, t.Any]) -> t.Dict[str, t.Any]:
                return values

            @pydantic.validator("name", "dialect")
            def _string_validator(cls, v: t.Any) -> t.Optional[str]:
                return v
        """
        after = """
        import typing as t

        import pydantic

        class Potato(pydantic.BaseModel):
            name: str
            dialect: str

            @pydantic.model_validator(mode="before")
            @classmethod
            def _normalize_fields(cls, values: t.Dict[str, t.Any]) -> t.Dict[str, t.Any]:
                return values

            @pydantic.field_validator("name", "dialect")
            @classmethod
            def _string_validator(cls, v: t.Any) -> t.Optional[str]:
                return v
        """
        self.assertCodemod(before, after)

    def test_root_validator_as_cst_name(self) -> None:
        before = """
        import typing as t

        from pydantic import BaseModel, root_validator


        class Potato(BaseModel):
            name: str
            dialect: str

            @root_validator
            def _normalize_fields(cls, values: t.Dict[str, t.Any]) -> t.Dict[str, t.Any]:
                return values
        """
        after = """
        import typing as t

        from pydantic import model_validator, BaseModel
        from typing import Self


        class Potato(BaseModel):
            name: str
            dialect: str

            @model_validator(mode="after")
            def _normalize_fields(self) -> Self:
                return self
        """
        self.assertCodemod(before, after)

    def test_root_validator_call_with_no_args(self) -> None:
        before = """
        import typing as t

        from pydantic import BaseModel, root_validator


        class Potato(BaseModel):
            name: str
            dialect: str

            @root_validator()
            def _normalize_fields(cls, values: t.Dict[str, t.Any]) -> t.Dict[str, t.Any]:
                return values
        """
        after = """
        import typing as t

        from pydantic import model_validator, BaseModel
        from typing import Self


        class Potato(BaseModel):
            name: str
            dialect: str

            @model_validator(mode="after")
            def _normalize_fields(self) -> Self:
                return self
        """
        self.assertCodemod(before, after)

    def test_root_validator_values_variable(self) -> None:
        before = """
        import typing as t

        from pydantic import BaseModel, root_validator


        class Potato(BaseModel):
            name: str
            dialect: str

            @root_validator()
            def _normalize_fields(cls, values: t.Dict[str, t.Any]) -> t.Dict[str, t.Any]:
                for key in ["name", "dialect"]:
                    if values.get(key) is not None and values[key] == "foo":
                        values[key] = "bar"
                return values
        """
        after = """
        import typing as t

        from pydantic import model_validator, BaseModel
        from typing import Self


        class Potato(BaseModel):
            name: str
            dialect: str

            @model_validator(mode="after")
            def _normalize_fields(self) -> Self:
                for key in ["name", "dialect"]:
                    if getattr(self, key) is not None and getattr(self, key) == "foo":
                        setattr(self, key, "bar")
                return self
        """
        self.assertCodemod(before, after)

    def test_noop_comment(self) -> None:
        code = """
        import typing as t

        from pydantic import BaseModel, validator


        class Potato(BaseModel):
            name: str
            dialect: str

            # TODO[pydantic]: We couldn't refactor the `validator`, please replace it by `field_validator` manually.
            # Check https://docs.pydantic.dev/dev-v2/migration/#changes-to-validators for more information.
            @validator("name", "dialect")
            def _string_validator(cls, v: t.Any, values: t.Dict[str, t.Any], **kwargs) -> t.Optional[str]:
                if isinstance(v, exp.Expression):
                    return v.name.lower()
                return str(v).lower() if v is not None else None
        """
        self.assertCodemod(code, code)
