from enum import Enum
from typing import List, Type

from libcst.codemod import ContextAwareTransformer
from libcst.codemod.visitors import AddImportsVisitor, RemoveImportsVisitor

from bump_pydantic.codemods.add_default_none import AddDefaultNoneCommand
from bump_pydantic.codemods.add_missing_annotation import AddMissingAnnotationCommand
from bump_pydantic.codemods.con_func import ConFuncCallCommand
from bump_pydantic.codemods.custom_types import CustomTypeCodemod
from bump_pydantic.codemods.field import FieldCodemod
from bump_pydantic.codemods.ormar import OrmarCodemod
from bump_pydantic.codemods.replace_config import ReplaceConfigCodemod
from bump_pydantic.codemods.replace_functions import ReplaceFunctionsCodemod
from bump_pydantic.codemods.replace_generic_model import ReplaceGenericModelCommand
from bump_pydantic.codemods.replace_imports import ReplaceImportsCodemod
from bump_pydantic.codemods.replace_model_attribute_access import ReplaceModelAttributeAccessCommand
from bump_pydantic.codemods.root_model import RootModelCommand
from bump_pydantic.codemods.validator import ValidatorCodemod
from bump_pydantic.codemods.warn_replaced_overrides import WarnReplacedOverridesCommand


class Rule(str, Enum):
    BP001 = "BP001"
    """Add default `None` to `Optional[T]`, `Union[T, None]` and `Any` fields"""
    BP002 = "BP002"
    """Replace `Config` class with `model_config` attribute."""
    BP003 = "BP003"
    """Replace `Field` old parameters with new ones."""
    BP004 = "BP004"
    """Replace imports that have been moved."""
    BP005 = "BP005"
    """Replace `GenericModel` with `BaseModel`."""
    BP006 = "BP006"
    """Replace `BaseModel.__root__ = T` with `RootModel[T]`."""
    BP007 = "BP007"
    """Replace `@validator` with `@field_validator`."""
    BP008 = "BP008"
    """Replace `con*` functions by `Annotated` versions."""
    BP009 = "BP009"
    """Mark Pydantic "protocol" functions in custom types with proper TODOs."""
    BP010 = "BP010"
    """Add type annotations to fields that are missing them."""
    BP011 = "BP011"
    """Replace `model.<old_attribute>` with `model.<new_attribute>`."""
    BP012 = "BP012"
    """Replace `parse_obj_as`, `parse_raw_as` with TypeAdapter."""
    BP013 = "BP013"
    """Add a TODO on overrides of deprecated methods like `dict` or `json`."""
    BO001 = "BO001"
    """Update Ormar models."""


def gather_codemods(disabled: List[Rule]) -> List[Type[ContextAwareTransformer]]:
    codemods: List[Type[ContextAwareTransformer]] = []

    if Rule.BP001 not in disabled:
        codemods.append(AddDefaultNoneCommand)

    # These need to run early because TypeInfrenceProvider depends on seeing the right line numbers for the original nodes.
    if Rule.BP010 not in disabled:
        codemods.append(AddMissingAnnotationCommand)

    if Rule.BP011 not in disabled:
        codemods.append(ReplaceModelAttributeAccessCommand)

    if Rule.BP002 not in disabled:
        codemods.append(ReplaceConfigCodemod)

    # The `ConFuncCallCommand` needs to run before the `FieldCodemod`.
    if Rule.BP008 not in disabled:
        codemods.append(ConFuncCallCommand)

    if Rule.BP003 not in disabled:
        codemods.append(FieldCodemod)

    if Rule.BP004 not in disabled:
        codemods.append(ReplaceImportsCodemod)

    if Rule.BP005 not in disabled:
        codemods.append(ReplaceGenericModelCommand)

    if Rule.BP006 not in disabled:
        codemods.append(RootModelCommand)

    if Rule.BP007 not in disabled:
        codemods.append(ValidatorCodemod)

    if Rule.BP009 not in disabled:
        codemods.append(CustomTypeCodemod)

    if Rule.BP012 not in disabled:
        codemods.append(ReplaceFunctionsCodemod)

    if Rule.BP013 not in disabled:
        codemods.append(WarnReplacedOverridesCommand)

    if Rule.BO001 not in disabled:
        codemods.append(OrmarCodemod)

    # Those codemods need to be the last ones.
    codemods.extend([RemoveImportsVisitor, AddImportsVisitor])
    return codemods
