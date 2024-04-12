from __future__ import annotations

import re

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

MODEL_ATTRIBUTE=m.Attribute(attr=m.OneOf(*(m.Name(attr) for attr in ATTRIBUTE_MAP.keys())))
COPY_CALL=m.Call(func=m.Attribute(attr=m.Name("copy")))
ARGS_NOT_IN_MODEL_COPY=m.Arg(keyword=m.Name("exclude") | m.Name("include"))

PREFIX_COMMENT = "# TODO[pydantic]: "
INCLUDE_EXCLUDE_COMMENT = "see https://docs.pydantic.dev/latest/api/base_model/#pydantic.BaseModel.copy"

class ReplaceModelAttributeAccessCommand(VisitorBasedCodemodCommand):

    METADATA_DEPENDENCIES = (FullyQualifiedNameProvider, NonCachedTypeInferenceProvider)

    def __init__(self, context: CodemodContext) -> None:
        super().__init__(context)

        self.pydantic_model_bases = self.context.scratch[ClassDefVisitor.BASE_MODEL_CONTEXT_KEY].known_members
        self.comment_to_add = None

    @m.leave(MODEL_ATTRIBUTE)
    def leave_model_attr(self, original_node: cst.Attribute, updated_node: cst.Attribute) -> cst.Attribute:
        obj = original_node.value
        old_attr = original_node.attr.value
        fqn = self.get_metadata(NonCachedTypeInferenceProvider, obj, None)
        if not fqn:
            # We don't know what this is! Warn?
            return updated_node
        if (match := re.match(r"typing\.Type\[(.*)\]", fqn)):
            fqn = match.group(1)
        if fqn in self.pydantic_model_bases:
            return updated_node.with_changes(attr=cst.Name(ATTRIBUTE_MAP[old_attr]))
        return updated_node

    @m.leave(COPY_CALL)
    def leave_copy_call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        if any(m.matches(arg, ARGS_NOT_IN_MODEL_COPY) for arg in original_node.args):
            # Use `copy` instead of `model_copy`.
            self.comment_to_add = INCLUDE_EXCLUDE_COMMENT
            return updated_node.with_changes(
                func=updated_node.func.with_changes(
                    attr=cst.Name("copy"),
                )
            )
        return updated_node

    def leave_SimpleStatementLine(self, original_node: cst.SimpleStatementLine, updated_node: cst.SimpleStatementLine) -> cst.SimpleStatementLine:
        if self.comment_to_add:
            comment=cst.Comment(value=f"{PREFIX_COMMENT}{self.comment_to_add}")
            self.comment_to_add = None
            return updated_node.with_changes(
                leading_lines=[
                    *updated_node.leading_lines,
                    cst.EmptyLine(comment=comment),
                ]
            )
        return updated_node
