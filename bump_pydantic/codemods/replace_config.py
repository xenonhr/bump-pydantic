from dataclasses import dataclass
from typing import List

import libcst as cst
from libcst import matchers as m
from libcst.codemod import CodemodContext, VisitorBasedCodemodCommand
from libcst.codemod.visitors import AddImportsVisitor, RemoveImportsVisitor
from libcst.metadata import ClassScope, FullyQualifiedNameProvider, ScopeProvider

from bump_pydantic.codemods.class_def_visitor import ClassDefVisitor

PREFIX_COMMENT = "# TODO[pydantic]: "
REFACTOR_COMMENT = f"{PREFIX_COMMENT}We couldn't refactor this class, please create the `model_config` manually."
REMOVED_KEYS_COMMENT = f"{PREFIX_COMMENT}The following keys were removed: {{keys}}."
INHERIT_CONFIG_COMMENT = (
    f"{PREFIX_COMMENT}The `Config` class inherits from another class, please create the `model_config` manually."
)
CHECK_LINK_COMMENT = "# Check https://docs.pydantic.dev/dev-v2/migration/#changes-to-config for more information."
MODEL_CONFIG_FIELD_COMMENT = f"{PREFIX_COMMENT}Pydantic 2 reserves the name `model_config`; please rename this field."

NEW_DEFAULTS: dict[str, m.BaseMatcherNode] = {
    "smart_union": m.Name(value="True"),
    "underscore_attrs_are_private": m.Name(value="True"),
}
REMOVED_KEYS = [
    "error_msg_templates",
    "fields",
    "getter_dict",
    "smart_union",
    "underscore_attrs_are_private",
    "json_loads",
    "json_dumps",
    "copy_on_model_validation",
    "post_init_call",
]
RENAMED_KEYS = {
    "allow_population_by_field_name": "populate_by_name",
    "anystr_lower": "str_to_lower",
    "anystr_strip_whitespace": "str_strip_whitespace",
    "anystr_upper": "str_to_upper",
    "keep_untouched": "ignored_types",
    "max_anystr_length": "str_max_length",
    "min_anystr_length": "str_min_length",
    "orm_mode": "from_attributes",
    "schema_extra": "json_schema_extra",
    "validate_all": "validate_default",
    "allow_mutation": "frozen",
}

EXTRA_ATTRIBUTE = m.Attribute(
    value=m.Name("Extra"),
    attr=m.Name(value=m.MatchIfTrue(lambda v: v in ("allow", "forbid", "ignore"))),
)
BASE_MODEL_WITH_CONFIG = m.ClassDef(
    bases=[
        m.ZeroOrMore(),
        m.Arg(),
        m.ZeroOrMore(),
    ],
    body=m.IndentedBlock(
        body=[
            m.ZeroOrMore(),
            m.ClassDef(name=m.Name(value="Config"), bases=[]),
            m.ZeroOrMore(),
        ]
    ),
)
BASE_MODEL_WITH_INHERITED_CONFIG = m.ClassDef(
    bases=[
        m.ZeroOrMore(),
        m.Arg(),
        m.ZeroOrMore(),
    ],
    body=m.IndentedBlock(
        body=[
            m.ZeroOrMore(),
            m.ClassDef(name=m.Name(value="Config"), bases=[m.AtLeastN(n=1)]),
            m.ZeroOrMore(),
        ]
    ),
)
BASE_MODEL_WITH_INVALID_CONFIG = m.ClassDef(
    bases=[
        m.ZeroOrMore(),
        m.Arg(),
        m.ZeroOrMore(),
    ],
    body=m.IndentedBlock(
        body=[
            m.ZeroOrMore(),
            m.ClassDef(
                name=m.Name(value="Config"),
                bases=[],
                body=m.IndentedBlock(
                    body=[
                        m.ZeroOrMore(),
                        m.AtLeastN(n=1, matcher=~m.SimpleStatementLine()),
                        m.ZeroOrMore(),
                    ]
                ),
            ),
            m.ZeroOrMore(),
        ]
    ),
)
"""
This matches a `Config` class with at least one NON `m.SimpleStatementLine`:

Example:
```
class Config:
    allow_mutation = True

    def potato():
        ...
```
"""

MODEL_CONFIG_FIELD_LINE = m.SimpleStatementLine(
    body=[
        m.ZeroOrMore(),
        m.AnnAssign(target=m.Name("model_config")),
        m.ZeroOrMore(),
    ]
)
BASE_MODEL_WITH_MODEL_CONFIG_FIELD = m.ClassDef(
    bases=[
        m.ZeroOrMore(),
        m.Arg(),
        m.ZeroOrMore(),
    ],
    body=m.IndentedBlock(
        body=[
            m.ZeroOrMore(),
            MODEL_CONFIG_FIELD_LINE,
            m.ZeroOrMore(),
        ]
    ),
)

MEMBER_ANN_ASSIGN_ANCESTORS = [m.ClassDef(), m.IndentedBlock(), m.SimpleStatementLine()]

@dataclass
class ClassInfo:
    is_model: bool = False
    field_starts_with_model: bool = False

class ReplaceConfigCodemod(VisitorBasedCodemodCommand):
    """Replace `Config` class by `ConfigDict` call."""

    METADATA_DEPENDENCIES = (ScopeProvider,FullyQualifiedNameProvider,)

    def __init__(self, context: CodemodContext) -> None:
        super().__init__(context)

        self.inside_config_class = False
        self.is_base_settings = False
        self.invalid_config_class = False
        self.inherited_config_class = False
        self.config_args: List[cst.Arg] = []
        self.class_stack: list[ClassInfo] = []
        self.pydantic_model_bases = self.context.scratch[ClassDefVisitor.BASE_MODEL_CONTEXT_KEY].known_members
        self.last_class: ClassInfo | None = None
        self.needs_model_config_comment = False

    def _is_pydantic_model(self, node: cst.CSTNode) -> bool:
        fqn_set = self.get_metadata(FullyQualifiedNameProvider, node, set())
        return any(fqn.name in self.pydantic_model_bases for fqn in fqn_set)

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        self.class_stack.append(ClassInfo(is_model=self._is_pydantic_model(node)))

    def leave_ClassDef(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.ClassDef:
        self.last_class = self.class_stack.pop()
        return updated_node

    def visit_AnnAssign(self, node: cst.AnnAssign) -> None:
        scope = self.get_metadata(ScopeProvider, node)
        if not isinstance(scope, ClassScope) or not self.class_stack or not self.class_stack[-1].is_model:
            return
        if not isinstance(node.target, cst.Name):
            return
        if node.target.value == "model_config":
            self.needs_model_config_comment = True
        if node.target.value.startswith("model_") and node.target.value != "model_config":
            self.class_stack[-1].field_starts_with_model = True

    def leave_SimpleStatementLine(self, original_node: cst.SimpleStatementLine, updated_node: cst.SimpleStatementLine) -> cst.SimpleStatementLine:
        if self.needs_model_config_comment:
            self.needs_model_config_comment = False
            return updated_node.with_changes(
                leading_lines=[
                    *updated_node.leading_lines,
                    cst.EmptyLine(comment=cst.Comment(value=MODEL_CONFIG_FIELD_COMMENT)),
                    cst.EmptyLine(comment=cst.Comment(value=CHECK_LINK_COMMENT)),
                ]
            )
        return updated_node

    @m.visit(m.ClassDef(bases=[m.ZeroOrMore(), m.Arg(value=m.Name("BaseSettings")), m.ZeroOrMore()]))
    def visit_settings_with_config(self, node: cst.ClassDef) -> None:
        self.is_base_settings = True

    @m.visit(m.ClassDef(name=m.Name(value="Config")))
    def visit_config_class(self, node: cst.ClassDef) -> None:
        if not self.class_stack or not self.class_stack[-1].is_model:
            return
        scope = self.get_metadata(ScopeProvider, node)
        if isinstance(scope, ClassScope):
            self.inside_config_class = True

    @m.leave(m.ClassDef(name=m.Name(value="Config")))
    def leave_config_class(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.ClassDef:
        self.inside_config_class = False
        if self.invalid_config_class or self.inherited_config_class:
            for line in updated_node.leading_lines:
                if m.matches(line, m.EmptyLine(comment=m.Comment(value=CHECK_LINK_COMMENT))):
                    return updated_node

        if self.invalid_config_class:
            return updated_node.with_changes(
                leading_lines=[
                    *updated_node.leading_lines,
                    cst.EmptyLine(comment=cst.Comment(value=(REFACTOR_COMMENT))),
                    cst.EmptyLine(comment=cst.Comment(value=(CHECK_LINK_COMMENT))),
                ]
            )
        elif self.inherited_config_class:
            return updated_node.with_changes(
                leading_lines=[
                    *updated_node.leading_lines,
                    cst.EmptyLine(comment=cst.Comment(value=(INHERIT_CONFIG_COMMENT))),
                    cst.EmptyLine(comment=cst.Comment(value=(CHECK_LINK_COMMENT))),
                ]
            )
        return updated_node

    def visit_Assign(self, node: cst.Assign) -> None:
        self.assign_value = node.value

    def visit_AssignTarget(self, node: cst.AssignTarget) -> None:
        if self.inside_config_class:
            if not isinstance(target := node.target, cst.Name):
                return
            keyword = RENAMED_KEYS.get(target.value, target.value)  # type: ignore[attr-defined]
            if m.matches(self.assign_value, EXTRA_ATTRIBUTE):
                value = cst.SimpleString(value=f'"{self.assign_value.attr.value}"')  # type: ignore[attr-defined]
                RemoveImportsVisitor.remove_unused_import(self.context, "pydantic", "Extra")
            else:
                value = self.assign_value  # type: ignore[assignment]
            if target.value == "allow_mutation":
                if m.matches(value, m.Name(value="False")):
                    value = cst.Name("True")
                elif m.matches(value, m.Name(value="True")):
                    value = cst.Name("False")
                else:
                    value = cst.UnaryOperation(operator=cst.Not(), expression=value)
            if (default := NEW_DEFAULTS.get(target.value)) and m.matches(value, default):
                return
            if keyword == "frozen":
                # If someone had both allow_mutation and frozen, with compatible values,
                # remove the duplication.
                duplicate_matcher = m.Arg(keyword=m.Name("frozen"), value=m.MatchIfTrue(lambda v: value.deep_equals(v)))
                if any(m.matches(arg, duplicate_matcher) for arg in self.config_args):
                    return
            self.config_args.append(
                cst.Arg(
                    keyword=target.with_changes(value=keyword),
                    value=value,
                    equal=cst.AssignEqual(
                        whitespace_before=cst.SimpleWhitespace(""),
                        whitespace_after=cst.SimpleWhitespace(""),
                    ),
                )
            )

    def leave_Module(self, original_node: cst.Module, updated_node: cst.Module) -> cst.Module:
        return updated_node

    @m.visit(BASE_MODEL_WITH_INHERITED_CONFIG)
    def visit_inherited_config_class(self, node: cst.ClassDef) -> None:
        self.inherited_config_class = True

    @m.leave(BASE_MODEL_WITH_INHERITED_CONFIG)
    def leave_inherited_config_class(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.ClassDef:
        if not self._is_pydantic_model(original_node):
            return original_node
        self.inherited_config_class = False
        return updated_node

    @m.visit(BASE_MODEL_WITH_INVALID_CONFIG)
    def visit_config_class_with_more_than_assignments(self, node: cst.ClassDef) -> None:
        self.invalid_config_class = True

    @m.visit(BASE_MODEL_WITH_MODEL_CONFIG_FIELD)
    def visit_model_with_model_config_field(self, node: cst.ClassDef) -> None:
        self.invalid_config_class = True

    @m.leave(BASE_MODEL_WITH_CONFIG)
    def leave_config_class_childless(self, original_node: cst.ClassDef, updated_node: cst.ClassDef) -> cst.ClassDef:
        """Replace the `Config` class with a `model_config` attribute.

        Any class that contains a `Config` class will have that class replaced
        with a `model_config` attribute. The `model_config` attribute will be
        assigned a `ConfigDict` object with the same arguments as the attributes
        from `Config` class.
        """
        if not self._is_pydantic_model(original_node):
            return original_node
        if self.invalid_config_class:
            self.invalid_config_class = False
            return updated_node
        if self.last_class and self.last_class.field_starts_with_model:
            self.config_args.append(
                cst.Arg(
                    keyword=cst.Name("protected_namespaces"),
                    value=cst.Tuple([]),
                    equal=cst.AssignEqual(
                        whitespace_before=cst.SimpleWhitespace(""),
                        whitespace_after=cst.SimpleWhitespace(""),
                    ),
                )
            )
        if self.is_base_settings:
            needed_import = {"module": "pydantic_settings", "obj": "SettingsConfigDict"}
        else:
            needed_import = {"module": "pydantic", "obj": "ConfigDict"}
        AddImportsVisitor.add_needed_import(context=self.context, **needed_import)  # type: ignore[arg-type]
        block = cst.ensure_type(updated_node.body, cst.IndentedBlock)
        body = [
            cst.SimpleStatementLine(
                body=[
                    cst.Assign(
                        targets=[cst.AssignTarget(target=cst.Name("model_config"))],
                        value=cst.Call(
                            func=cst.Name("SettingsConfigDict" if self.is_base_settings else "ConfigDict"),
                            args=self.config_args,
                        ),
                    )
                ],
                leading_lines=self._leading_lines_from_removed_keys(self.config_args),
            )
            if m.matches(statement, m.ClassDef(name=m.Name(value="Config")))
            else statement
            for statement in block.body
        ]
        self.is_base_settings = False
        self.config_args = []
        return updated_node.with_changes(body=updated_node.body.with_changes(body=body))

    @staticmethod
    def _leading_lines_from_removed_keys(args: List[cst.Arg]) -> List[cst.EmptyLine]:
        removed_keys = [arg.keyword.value for arg in args if arg.keyword.value in REMOVED_KEYS]  # type: ignore
        if not removed_keys:
            return []

        formatted_keys = ", ".join(f"`{key}`" for key in removed_keys)
        return [
            cst.EmptyLine(comment=cst.Comment(value=REMOVED_KEYS_COMMENT.format(keys=formatted_keys))),
            cst.EmptyLine(comment=cst.Comment(value=CHECK_LINK_COMMENT)),
        ]


if __name__ == "__main__":
    import textwrap

    from rich.console import Console

    console = Console()

    source = textwrap.dedent(
        """
        from pydantic import BaseModel

        class A(BaseSettings):
            a: str
            # My comment

            b: int

            # potato
            class Config:
                allow_arbitrary_types = True
                schema_extra = {
                    "example": {
                        "foo": "bar",
                    }
                }

                @staticmethod
                def indexes() -> Iterable[Index]:
                    yield Index(DiscoverTopic.org_id, DiscoverTopic.taxonomy_id)
        """
    )
    console.print(source)
    console.print("=" * 80)

    mod = cst.parse_module(source)
    context = CodemodContext(filename="main.py")
    wrapper = cst.MetadataWrapper(mod)
    command = ReplaceConfigCodemod(context=context)
    console.print(mod)

    mod = wrapper.visit(command)
    wrapper = cst.MetadataWrapper(mod)
    command = AddImportsVisitor(context=context)  # type: ignore[assignment]
    mod = wrapper.visit(command)
    console.print(mod.code)
