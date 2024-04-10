from __future__ import annotations

import libcst as cst
import libcst.matchers as m
from libcst.codemod import CodemodContext, VisitorBasedCodemodCommand
from libcst.metadata import FullyQualifiedNameProvider, TypeInferenceProvider

from bump_pydantic.codemods.class_def_visitor import ClassDefVisitor

METHOD_MAP = {
    "construct": "model_construct",
    "copy": "model_copy",
    "dict": "model_dump",
    "json_schema": "model_json_schema",
    "json": "model_dump_json",
    "parse_obj": "model_validate",
    "update_forward_refs": "model_rebuild",
}

MODEL_METHOD_CALL=m.Call(func=m.Attribute(attr=m.OneOf(*(m.Name(method) for method in METHOD_MAP.keys()))))


class ReplaceModelMethodCallsCommand(VisitorBasedCodemodCommand):

    METADATA_DEPENDENCIES = (FullyQualifiedNameProvider, TypeInferenceProvider)

    def __init__(self, context: CodemodContext) -> None:
        super().__init__(context)

        self.pydantic_model_bases = self.context.scratch[ClassDefVisitor.BASE_MODEL_CONTEXT_KEY].known_members
        self.should_add_comment = False
        self.node_stack = list[cst.CSTNode]()

    @m.leave(MODEL_METHOD_CALL)
    def leave_json_call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        func_attr: cst.Attribute = cst.ensure_type(original_node.func, cst.Attribute)
        obj = func_attr.value
        old_method = func_attr.attr.value
        fqn = self.get_metadata(TypeInferenceProvider, obj, None)
        if not fqn:
            # We don't know what this is! Warn?
            return updated_node
        if fqn in self.pydantic_model_bases:
            return updated_node.with_changes(
                func=cst.Attribute(
                    attr=cst.Name(METHOD_MAP[old_method]),
                    value=updated_node.func.value
                )
            )
        return updated_node
