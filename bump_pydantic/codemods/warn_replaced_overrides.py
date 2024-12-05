from __future__ import annotations

import libcst as cst
import libcst.matchers as m
from libcst.codemod import CodemodContext, VisitorBasedCodemodCommand
from libcst.metadata import FullyQualifiedNameProvider

from bump_pydantic.codemods.class_def_visitor import ClassDefVisitor
from bump_pydantic.codemods.replace_model_attribute_access import ATTRIBUTE_MAP

PREFIX_COMMENT = "# TODO[pydantic]: "
REFACTOR_COMMENT = (
    f"{PREFIX_COMMENT}overriding a deprecated model method: `{{old_name}}` is replaced by `{{new_name}}`.\n"
    "# You may need to refactor this and add tests to ensure the intended behavior is preserved.\n"
    "# Check https://docs.pydantic.dev/dev-v2/migration/#changes-to-pydanticbasemodel for more information."
)

OLD_MODEL_METHOD = m.FunctionDef(name=m.OneOf(*(m.Name(attr) for attr in ATTRIBUTE_MAP.keys())))
MODEL_METHOD_ANCESTORS = [m.ClassDef(), m.IndentedBlock()]


class WarnReplacedOverridesCommand(VisitorBasedCodemodCommand):

    METADATA_DEPENDENCIES = (FullyQualifiedNameProvider, )

    def __init__(self, context: CodemodContext) -> None:
        super().__init__(context)

        self.pydantic_model_bases = self.context.scratch[ClassDefVisitor.BASE_MODEL_CONTEXT_KEY].known_members
        self.should_add_comment = False
        self.node_stack = list[cst.CSTNode]()

    def on_visit(self, node: cst.CSTNode) -> bool:
        self.node_stack.append(node)
        return super().on_visit(node)

    def on_leave(self, original_node: cst.CSTNode, updated_node: cst.CSTNode) -> cst.CSTNode | cst.RemovalSentinel:
        self.node_stack.pop()
        return super().on_leave(original_node, updated_node)

    def _is_pydantic_model(self, node: cst.CSTNode) -> bool:
        fqn_set = self.get_metadata(FullyQualifiedNameProvider, node, set())
        return any(fqn.name in self.pydantic_model_bases for fqn in fqn_set)

    @m.leave(OLD_MODEL_METHOD)
    def leave_old_model_method(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.FunctionDef:
        ancestors = self.node_stack[-len(MODEL_METHOD_ANCESTORS):]
        if len(ancestors) < len(MODEL_METHOD_ANCESTORS) or not self._is_pydantic_model(ancestors[0]) or not all(
            m.matches(parent, matcher) for parent, matcher in zip(ancestors, MODEL_METHOD_ANCESTORS, strict=True)):
            return updated_node

        return updated_node.with_changes(
            leading_lines=list(updated_node.leading_lines) + [
                cst.EmptyLine(comment=cst.Comment(value=line))
                for line in REFACTOR_COMMENT.format(old_name=original_node.name.value, new_name=ATTRIBUTE_MAP[original_node.name.value]).splitlines()
            ]
        )
