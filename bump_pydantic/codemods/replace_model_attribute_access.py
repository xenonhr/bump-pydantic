from __future__ import annotations

import libcst as cst
import libcst.matchers as m
from libcst.codemod import CodemodContext, VisitorBasedCodemodCommand
from libcst.metadata import FullyQualifiedNameProvider, NonCachedTypeInferenceProvider

from bump_pydantic.codemods.class_def_visitor import ClassDefVisitor

ATTRIBUTE_MAP = {
    "__fields__": "model_fields",
    "__private_attributes__": "__pydantic_private__",
    "__validators__": "__pydantic_validator__",
    "construct": "model_construct",
    "copy": "model_copy",
    "dict": "model_dump",
    "json_schema": "model_json_schema",
    "json": "model_dump_json",
    "parse_obj": "model_validate",
    "update_forward_refs": "model_rebuild",
    "parse_raw": "model_validate_json",
}

MODEL_ATTRIBUTE=func=m.Attribute(attr=m.OneOf(*(m.Name(attr) for attr in ATTRIBUTE_MAP.keys())))


class ReplaceModelAttributeAccessCommand(VisitorBasedCodemodCommand):

    METADATA_DEPENDENCIES = (FullyQualifiedNameProvider, NonCachedTypeInferenceProvider)

    def __init__(self, context: CodemodContext) -> None:
        super().__init__(context)

        self.pydantic_model_bases = self.context.scratch[ClassDefVisitor.BASE_MODEL_CONTEXT_KEY].known_members

    @m.leave(MODEL_ATTRIBUTE)
    def leave_model_attr(self, original_node: cst.Attribute, updated_node: cst.Attribute) -> cst.Attribute:
        obj = original_node.value
        old_attr = original_node.attr.value
        fqn = self.get_metadata(NonCachedTypeInferenceProvider, obj, None)
        if not fqn:
            # We don't know what this is! Warn?
            return updated_node
        if fqn in self.pydantic_model_bases:
            return updated_node.with_changes(attr=cst.Name(ATTRIBUTE_MAP[old_attr]))
        return updated_node
