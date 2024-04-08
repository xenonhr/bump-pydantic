from __future__ import annotations

import functools
import operator
from typing import Collection, cast

import libcst as cst
from attr import dataclass
from libcst import matchers as m
from libcst.codemod import CodemodContext, VisitorBasedCodemodCommand
from libcst.codemod.visitors import AddImportsVisitor
from libcst.metadata import FullyQualifiedNameProvider, QualifiedName

from bump_pydantic.codemods.class_def_visitor import ClassDefVisitor

META_LINE_MATCHER = m.SimpleStatementLine(body=[m.SaveMatchedNode(m.ZeroOrMore(m.Assign(targets=[m.AssignTarget(m.Name())])), "assigns")])
META_BODY_MATCHER = m.IndentedBlock(body=[m.ZeroOrMore(META_LINE_MATCHER)])


@dataclass(frozen=True)
class ClassInfo:
    node: cst.ClassDef
    is_ormar_model: bool
    is_ormar_meta: bool


class OrmarCodemod(VisitorBasedCodemodCommand):
    METADATA_DEPENDENCIES = (FullyQualifiedNameProvider,)

    def __init__(self, context: CodemodContext) -> None:
        super().__init__(context)

        self._class_stack: list[ClassInfo] = []

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        ormar_model_bases = self.context.scratch[ClassDefVisitor.ORMAR_MODEL_CONTEXT_KEY].known_members
        ormar_meta_bases = self.context.scratch[ClassDefVisitor.ORMAR_META_CONTEXT_KEY].known_members
        fqn_set = cast(Collection[QualifiedName], self.get_metadata(FullyQualifiedNameProvider, node))
        self._class_stack.append(ClassInfo(
            node,
            is_ormar_model=any(fqn.name in ormar_model_bases for fqn in fqn_set),
            is_ormar_meta=any(fqn.name in ormar_meta_bases for fqn in fqn_set)
        ))

    def leave_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.ClassDef | cst.SimpleStatementLine:
        top = self._class_stack.pop()
        assert top.node == original_node
        meta_replacement_failed = False
        parent_is_ormar_model = self._class_stack and self._class_stack[-1].is_ormar_model
        if original_node.name.value == "Meta" and parent_is_ormar_model:
            # This is a Meta class inside an Ormar model
            if m.matches(updated_node.body, META_BODY_MATCHER) and len(original_node.bases) <= 1:
                return self._meta_into_config(original_node, updated_node)
            else:
                meta_replacement_failed = True
        elif top.is_ormar_meta and not parent_is_ormar_model:
            # This is an Ormar Meta base class outside an Ormar model
            if m.matches(updated_node.body, META_BODY_MATCHER) and len(original_node.bases) <= 1:
                return self._meta_into_config(original_node, updated_node, ormar_config_name=self._config_name_from_class_name(original_node.name.value)).with_changes(leading_lines=[cst.EmptyLine()])
            else:
                meta_replacement_failed = True

        if meta_replacement_failed:
            return self._with_leading_comment(updated_node, "# TODO[ormar]: Failed to replace Meta with OrmarConfig, please fix manually.")

        return updated_node

    def _config_name_from_class_name(self, class_name: str) -> str:
        return f"{class_name.removesuffix('Meta').lower()}_ormar_config"

    def _meta_into_config(self, original_node: cst.ClassDef, updated_node: cst.ClassDef, ormar_config_name: str = "ormar_config") -> cst.SimpleStatementLine:
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

        config_func = cst.Attribute(
            value=cst.Name("ormar"),
            attr=cst.Name("OrmarConfig"),
        )
        if original_node.bases:
            assert len(original_node.bases) == 1
            base = original_node.bases[0].value
            base_fqn_set = self.get_metadata(FullyQualifiedNameProvider, base, set())
            base_is_default = any(fqn.name == "ormar.ModelMeta" for fqn in base_fqn_set)
            if not base_is_default:
                if isinstance(base, cst.Name):
                    base = base.with_changes(value=self._config_name_from_class_name(base.value))
                elif isinstance(base, cst.Attribute):
                    base = base.with_changes(attr=cst.Name(self._config_name_from_class_name(base.attr.value)))
                config_func = cst.Attribute(
                    value=base,
                    attr=cst.Name("copy"),
                )

        AddImportsVisitor.add_needed_import(self.context, "ormar")
        return cst.SimpleStatementLine(body=[cst.Assign(
            targets=[cst.AssignTarget(cst.Name(ormar_config_name))],
            value=cst.Call(
                func=config_func,
                whitespace_before_args=cst.ParenthesizedWhitespace(
                    first_line=cst.TrailingWhitespace(newline=cst.Newline()),
                    indent=True,
                    last_line=cst.SimpleWhitespace(value="    "),
                ),
                args=args,
            ),
        )])

    def _with_leading_comment(self, node: cst.ClassDef, comment: str) -> cst.ClassDef:
        return node.with_changes(
            leading_lines=[
                *node.leading_lines,
                cst.EmptyLine(comment=cst.Comment(value=(comment))),
            ]
        )
