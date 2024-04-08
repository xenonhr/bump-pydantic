from __future__ import annotations

import functools
import operator
from typing import Collection, cast

import libcst as cst
from libcst import matchers as m
from libcst.codemod import CodemodContext, VisitorBasedCodemodCommand
from libcst.codemod.visitors import AddImportsVisitor
from libcst.metadata import FullyQualifiedNameProvider, QualifiedName

from bump_pydantic.codemods.class_def_visitor import OrmarClassDefVisitor

META_LINE_MATCHER = m.SimpleStatementLine(body=[m.SaveMatchedNode(m.ZeroOrMore(m.Assign(targets=[m.AssignTarget(m.Name())])), "assigns")])
META_BODY_MATCHER = m.IndentedBlock(body=[m.ZeroOrMore(META_LINE_MATCHER)])


class OrmarCodemod(VisitorBasedCodemodCommand):
    METADATA_DEPENDENCIES = (FullyQualifiedNameProvider,)

    def __init__(self, context: CodemodContext) -> None:
        super().__init__(context)

        self._class_stack: list[tuple[cst.ClassDef, bool]] = []
        self._meta_replacement_failed = False

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        ormar_model_bases = self.context.scratch[OrmarClassDefVisitor.BASE_MODEL_CONTEXT_KEY]
        fqn_set = cast(Collection[QualifiedName], self.get_metadata(FullyQualifiedNameProvider, node))
        is_ormar_model = any(fqn.name in ormar_model_bases for fqn in fqn_set)
        self._class_stack.append((node, is_ormar_model))

    def leave_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.ClassDef | cst.SimpleStatementLine:
        top, _ = self._class_stack.pop()
        assert top == original_node
        if (original_node.name.value == "Meta" and self._class_stack and self._class_stack[-1][1]):
            # This is a Meta class inside an Ormar model
            if m.matches(updated_node.body, META_BODY_MATCHER):
                return self._meta_into_config(original_node, updated_node)
            else:
                self._meta_replacement_failed = True

        return updated_node

    def _meta_into_config(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.SimpleStatementLine:
        line_dicts = m.extractall(updated_node.body, META_LINE_MATCHER)
        assigns: list[cst.Assign] = functools.reduce(operator.iadd, [list(d["assigns"]) for d in line_dicts], [])
        args = [cst.Arg(
            keyword=cst.ensure_type(assign.targets[0].target, cst.Name),
            value=assign.value,
            equal=cst.AssignEqual(cst.SimpleWhitespace(""), cst.SimpleWhitespace("")),
            comma=cst.Comma(
                whitespace_after=cst.ParenthesizedWhitespace(
                    first_line=cst.TrailingWhitespace(newline=cst.Newline()),
                    indent=True,
                    last_line=cst.SimpleWhitespace(
                        value="    " if i < len(assigns) - 1 else "",
                    ),
                ),
            ),
        ) for i, assign in enumerate(assigns)]

        AddImportsVisitor.add_needed_import(self.context, "ormar")
        return cst.SimpleStatementLine(body=[cst.Assign(
            targets=[cst.AssignTarget(cst.Name("ormar_config"))],
            value=cst.Call(
                func=cst.Attribute(
                    value=cst.Name("ormar"),
                    attr=cst.Name("OrmarConfig"),
                ),
                whitespace_before_args=cst.ParenthesizedWhitespace(
                    first_line=cst.TrailingWhitespace(newline=cst.Newline()),
                    indent=True,
                    last_line=cst.SimpleWhitespace(value="    "),
                ),
                args=args,
            ),
        )])
