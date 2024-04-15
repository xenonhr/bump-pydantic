from collections import defaultdict
from typing import List, Sequence

import libcst as cst
from libcst import matchers as m
from libcst._nodes.module import Module
from libcst.codemod import CodemodContext, VisitorBasedCodemodCommand
from libcst.codemod.visitors import AddImportsVisitor, RemoveImportsVisitor
from libcst.metadata import QualifiedNameProvider

PREFIX_COMMENT = "# TODO[pydantic]: "
REFACTOR_COMMENT = (
    f"{PREFIX_COMMENT}We couldn't refactor the `{{old_name}}`, please replace it by `{{new_name}}` manually."
)
VALIDATOR_COMMENT = REFACTOR_COMMENT.format(old_name="validator", new_name="field_validator")
ROOT_VALIDATOR_COMMENT = REFACTOR_COMMENT.format(old_name="root_validator", new_name="model_validator")
CHECK_LINK_COMMENT = "# Check https://docs.pydantic.dev/dev-v2/migration/#changes-to-validators for more information."

def m_name_or_pydantic_attr(name: str) -> m.OneOf[m.BaseExpressionMatchType]:
    return m.Name(name) | m.Attribute(attr=m.Name(name), value=m.Name("pydantic"))

IMPORT_VALIDATOR = m.Module(
    body=[
        m.ZeroOrMore(),
        m.SimpleStatementLine(
            body=[
                m.ZeroOrMore(),
                m.ImportFrom(
                    module=m.Name("pydantic"),
                    names=[
                        m.ZeroOrMore(),
                        m.ImportAlias(name=m.Name("validator")),
                        m.ZeroOrMore(),
                    ],
                ),
                m.ZeroOrMore(),
            ],
        ),
        m.ZeroOrMore(),
    ]
)
VALIDATOR_DECORATOR = m.Decorator(decorator=m.Call(func=m_name_or_pydantic_attr("validator")))
VALIDATOR_FUNCTION = m.FunctionDef(decorators=[m.ZeroOrMore(), VALIDATOR_DECORATOR, m.ZeroOrMore()])

IMPORT_ROOT_VALIDATOR = m.Module(
    body=[
        m.ZeroOrMore(),
        m.SimpleStatementLine(
            body=[
                m.ZeroOrMore(),
                m.ImportFrom(
                    module=m.Name("pydantic"),
                    names=[
                        m.ZeroOrMore(),
                        m.ImportAlias(name=m.Name("root_validator")),
                        m.ZeroOrMore(),
                    ],
                ),
                m.ZeroOrMore(),
            ],
        ),
        m.ZeroOrMore(),
    ]
)
BARE_ROOT_VALIDATOR_DECORATOR = m.Decorator(decorator=m_name_or_pydantic_attr("root_validator"))
BARE_ROOT_VALIDATOR_FUNCTION = m.FunctionDef(decorators=[m.ZeroOrMore(), BARE_ROOT_VALIDATOR_DECORATOR, m.ZeroOrMore()])

ROOT_VALIDATOR_DECORATOR = m.Decorator(decorator=m.Call(func=m_name_or_pydantic_attr("root_validator")))
ROOT_VALIDATOR_FUNCTION = m.FunctionDef(decorators=[m.ZeroOrMore(), ROOT_VALIDATOR_DECORATOR, m.ZeroOrMore()])

ASSIGN_TO_VALUES = (
    m.Assign(targets=[m.AssignTarget(target=m.Name("values"))]) |
    m.AugAssign(target=m.Name("values"))
)


class ValidatorCodemod(VisitorBasedCodemodCommand):

    METADATA_DEPENDENCIES = (QualifiedNameProvider,)

    def __init__(self, context: CodemodContext) -> None:
        super().__init__(context)

        self._import_pydantic_validator = self._import_pydantic_root_validator = False
        self._already_modified = False
        self._should_add_comment = False
        self._should_replace_values_param = False
        self._has_comment = False
        self._args: List[cst.Arg] = []
        self._fields_needing_validate_default = defaultdict[cst.ClassDef, set[str]](set)
        self._class_stack: list[cst.ClassDef] = []
        self._need_field_import = False
        self._should_be_instance_method = False

    @m.visit(IMPORT_VALIDATOR)
    def visit_import_validator(self, node: cst.CSTNode) -> None:
        self._import_pydantic_validator = True
        self._import_pydantic_root_validator = True

    def leave_Module(self, original_node: Module, updated_node: Module) -> Module:
        self._import_pydantic_validator = False
        self._import_pydantic_root_validator = False
        if self._need_field_import:
            AddImportsVisitor.add_needed_import(context=self.context, module="pydantic", obj="Field")
            self._need_field_import = False
        return updated_node

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        self._class_stack.append(node)

    @m.visit(VALIDATOR_DECORATOR | ROOT_VALIDATOR_DECORATOR)
    def visit_validator_decorator(self, node: cst.Decorator) -> None:
        if m.matches(node.decorator, m.Call()):
            field_names: list[str] = []
            always = False
            assert isinstance(node.decorator, cst.Call)
            for arg in node.decorator.args:
                pre_false = m.Arg(keyword=m.Name("pre"), value=m.Name("False"))
                pre_true = m.Arg(keyword=m.Name("pre"), value=m.Name("True"))
                if m.matches(arg, m.Arg(keyword=m.Name("allow_reuse")) | pre_false):
                    continue
                if m.matches(arg, pre_true):
                    self._args.append(arg.with_changes(keyword=cst.Name("mode"), value=cst.SimpleString('"before"')))
                elif m.matches(arg, m.Arg(keyword=m.Name("always"), value=m.Name("True"))):
                    always = True
                elif m.matches(arg, m.Arg(keyword=m.Name("skip_on_failure"), value=m.Name("True"))):
                    continue
                elif m.matches(arg.keyword, m.Name(value=m.MatchIfTrue(lambda v: v in ("each_item", "always")))):
                    self._should_add_comment = True
                else:
                    if isinstance(arg.value, cst.SimpleString) and isinstance(field_name := arg.value.evaluated_value, str):
                        field_names.append(field_name)
                    # The `check_fields` kw-argument and all positional arguments can be just copied.
                    self._args.append(arg)
            if always:
                if field_names and self._class_stack:
                    self._fields_needing_validate_default[self._class_stack[-1]].update(field_names)
                else:
                    self._should_add_comment = True
        else:
            """This only happens for `@validator`, not with `@validator()`. The parenthesis makes it not be a `Call`"""
            self._should_add_comment = True

        # Removes the trailing comma on the last argument e.g.
        # `@validator(allow_reuse=True, )` -> `@validator(allow_reuse=True)`
        if self._args:
            self._args[-1] = self._args[-1].with_changes(comma=cst.MaybeSentinel.DEFAULT)

    @m.visit(VALIDATOR_FUNCTION)
    def visit_validator_func(self, node: cst.FunctionDef) -> None:
        for line in node.leading_lines:
            if m.matches(line, m.EmptyLine(comment=m.Comment(value=CHECK_LINK_COMMENT))):
                self._has_comment = True
        allowed_param_count = 2
        if any(p.name.value == "values" for p in node.params.params[2:]) and not m.findall(node.body, ASSIGN_TO_VALUES):
            allowed_param_count += 1
            self._should_replace_values_param = True
        # We are only able to refactor the `@validator` when the function has only `cls` and `v` as arguments.
        if len(node.params.params) > allowed_param_count or node.params.star_kwarg is not None:
            self._should_add_comment = True

    @m.leave(ROOT_VALIDATOR_DECORATOR|BARE_ROOT_VALIDATOR_DECORATOR)
    def leave_root_validator_decorato(self, original_node: cst.Decorator, updated_node: cst.Decorator) -> cst.Decorator:
        if self._has_comment:
            return updated_node

        if self._should_add_comment:
            return self._decorator_with_leading_comment(updated_node, ROOT_VALIDATOR_COMMENT)

        return self._replace_validators(updated_node, "root_validator", "model_validator")

    @m.leave(VALIDATOR_DECORATOR)
    def leave_validator_decorator(self, original_node: cst.Decorator, updated_node: cst.Decorator) -> cst.Decorator:
        if self._has_comment:
            return updated_node

        if self._should_add_comment:
            return self._decorator_with_leading_comment(updated_node, VALIDATOR_COMMENT)

        return self._replace_validators(updated_node, "validator", "field_validator")

    @m.leave(VALIDATOR_FUNCTION | ROOT_VALIDATOR_FUNCTION | BARE_ROOT_VALIDATOR_FUNCTION)
    def leave_validator_func(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.FunctionDef:
        self._args = []
        self._has_comment = False

        if self._should_add_comment:
            self._should_add_comment = False
            return updated_node

        if self._should_replace_values_param:
            new_params: list[cst.Param] = []
            for param in updated_node.params.params:
                if param.name.value == "values":
                    param = cst.Param(name=cst.Name("info"), annotation=cst.Annotation(annotation=cst.Name("ValidationInfo")))
                new_params.append(param)
            AddImportsVisitor.add_needed_import(self.context, "pydantic", "ValidationInfo")
            new_body = m.replace(updated_node.body, m.Name("values"), cst.Attribute(value=cst.Name(value="info"), attr=cst.Name(value="data")))
            updated_node = updated_node.with_changes(params=updated_node.params.with_changes(params=new_params), body=new_body)
            self._should_replace_values_param = False

        if not self._should_be_instance_method and not any(m.matches(d, m.Decorator(decorator=m.Name("classmethod"))) for d in updated_node.decorators):
            classmethod_decorator = cst.Decorator(decorator=cst.Name("classmethod"))
            updated_node = updated_node.with_changes(decorators=[*updated_node.decorators, classmethod_decorator])
        self._should_be_instance_method = False
        return updated_node

    def leave_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.ClassDef:
        if self._class_stack and self._class_stack[-1] == original_node:
            self._class_stack.pop()
            field_names = self._fields_needing_validate_default[original_node]
            if field_names:
                updated_node = self._add_validate_default(original_node, updated_node, field_names)
                del self._fields_needing_validate_default[original_node]

        return updated_node

    def _add_validate_default(self, original_node: cst.ClassDef, updated_node: cst.ClassDef, field_names:set[str]) -> cst.ClassDef:
        field_matcher = m.AnnAssign(target=m.OneOf(*(m.Name(name) for name in field_names)))

        replacements: list[tuple[int, int, cst.BaseSmallStatement]] = []
        for i, statement in enumerate(original_node.body.body):
            if isinstance(statement, cst.SimpleStatementLine):
                for j, small_stat in enumerate(statement.body):
                    if m.matches(small_stat, field_matcher):
                        new_small_stat = self._add_validate_default_to_field(cst.ensure_type(small_stat, cst.AnnAssign))
                        replacements.append((i, j, new_small_stat))

        for i, j, new_small_stat in replacements:
            small_stat = cst.ensure_type(updated_node.body.body[i], cst.SimpleStatementLine).body[j]
            updated_node = cst.ensure_type(updated_node.deep_replace(small_stat, new_small_stat), cst.ClassDef)

        return updated_node

    def _add_validate_default_to_field(self, ann_assign: cst.AnnAssign) -> cst.AnnAssign:
        pyd_field_name_matcher = m.MatchMetadataIfTrue(
            QualifiedNameProvider,
            lambda qualnames: any(
                qualname.name == "pydantic.Field"
                for qualname in qualnames
            ),
        )
        pyd_field_matcher = m.Call(func=(pyd_field_name_matcher | m.Attribute(attr=pyd_field_name_matcher)))
        validate_default_true = cst.Arg(
            keyword=cst.Name(value="validate_default"),
            value=cst.Name(value="True"),
            equal=cst.AssignEqual(cst.SimpleWhitespace(""), cst.SimpleWhitespace("")))

        pyd_fields: Sequence[cst.CSTNode] = self.findall(ann_assign, pyd_field_matcher)
        if pyd_fields:
            # There is already a pydantic.Field, add validate_default=True to it.
            pyd_field = cst.ensure_type(pyd_fields[0], cst.Call)
            new_pyd_field = pyd_field.with_changes(args=[*pyd_field.args, validate_default_true])
            return cst.ensure_type(ann_assign.deep_replace(pyd_field, new_pyd_field), cst.AnnAssign)

        # No pydantic.Field found, let's add it
        self._need_field_import = True
        pyd_field = cst.Call(func=cst.Name("Field"), args=[validate_default_true])

        annotation = ann_assign.annotation.annotation
        if m.matches(annotation, m.Subscript(value=m.Name("Annotated"))):
            # There is already an annotation with Annotated, let's add the Field to it.
            new_annotation = annotation.with_changes(slice=[cst.SubscriptElement(slice=cst.Index(value=pyd_field))])
        else:
            # We need to wrap it into Annotated
            AddImportsVisitor.add_needed_import(self.context, "typing", "Annotated")
            new_annotation = cst.Subscript(
                value=cst.Name("Annotated"),
                slice=[
                    cst.SubscriptElement(slice=cst.Index(value=annotation)),
                    cst.SubscriptElement(slice=cst.Index(value=pyd_field)),
                ],
            )
        return cst.ensure_type(ann_assign.deep_replace(annotation, new_annotation), cst.AnnAssign)

    def _decorator_with_leading_comment(self, node: cst.Decorator, comment: str) -> cst.Decorator:
        return node.with_changes(
            leading_lines=[
                *node.leading_lines,
                cst.EmptyLine(comment=cst.Comment(value=(comment))),
                cst.EmptyLine(comment=cst.Comment(value=(CHECK_LINK_COMMENT))),
            ]
        )

    def _replace_validators(self, node: cst.Decorator, old_name: str, new_name: str) -> cst.Decorator:
        mode_after = cst.Arg(
                keyword=cst.Name("mode"),
                value=cst.SimpleString('"after"'),
                equal=cst.AssignEqual(cst.SimpleWhitespace(""), cst.SimpleWhitespace("")))
        old_func = cst.ensure_type(node.decorator, cst.Call).func if m.matches(node.decorator, m.Call()) else node.decorator
        if isinstance(old_func, cst.Name):
            new_func = cst.Name(new_name)
            RemoveImportsVisitor.remove_unused_import(self.context, "pydantic", old_name)
            AddImportsVisitor.add_needed_import(self.context, "pydantic", new_name)
        else:
            new_func = cst.Attribute(attr=cst.Name(new_name), value=cst.Name("pydantic"))

        if new_name == "model_validator":
            mode = next((arg for arg in self._args if arg.keyword and arg.keyword.value == "mode"), None)
            if mode is None:
                self._args.append(mode_after)
                mode = "after"
            if mode == "after":
                self._should_be_instance_method = True

        if m.matches(node, BARE_ROOT_VALIDATOR_DECORATOR):
            decorator = cst.Call(func=new_func, args=self._args)
        else:
            decorator = node.decorator.with_changes(func=new_func, args=self._args)
        return node.with_changes(decorator=decorator)


if __name__ == "__main__":
    import textwrap

    from rich.console import Console

    console = Console()

    source = textwrap.dedent(
        """
        from pydantic import BaseModel, validator

        class Foo(BaseModel):
            bar: str

            @validator("bar", pre=True, always=True)
            def bar_validator(cls, v):
                return v
        """
    )
    console.print(source)
    console.print("=" * 80)

    mod = cst.parse_module(source)
    context = CodemodContext(filename="main.py")
    wrapper = cst.MetadataWrapper(mod)
    command = ValidatorCodemod(context=context)
    # console.print(mod)

    mod = wrapper.visit(command)
    wrapper = cst.MetadataWrapper(mod)
    command = AddImportsVisitor(context=context)  # type: ignore[assignment]
    mod = wrapper.visit(command)
    console.print(mod.code)
