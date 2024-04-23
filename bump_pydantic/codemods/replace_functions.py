from typing import Union

import libcst as cst
from libcst import matchers as m
from libcst.codemod import CodemodContext, VisitorBasedCodemodCommand
from libcst.codemod.visitors import AddImportsVisitor, RemoveImportsVisitor


def m_import_from_pydantic(name: str) -> m.ImportFrom:
    return m.ImportFrom(
        module=m.Name("pydantic"),
        names=[
            m.ZeroOrMore(),
            m.ImportAlias(name=m.Name(name)),
            m.ZeroOrMore(),
        ]
    )

def m_name_or_pydantic_attr(name: str) -> m.OneOf[m.BaseExpressionMatchType]:
    return m.Name(name) | m.Attribute(attr=m.Name(name), value=m.Name("pydantic"))

TYPE_ADAPTER_REPLACEMENTS = {
    "parse_raw_as": "validate_json",
    "parse_obj_as": "validate_python",
}

JSON_LOADS_DUMP_JSON = m.Call(
    func=m.Attribute(value=m.Name("json"), attr=m.Name("loads")),
    args=[
        m.Arg(
            value=m.SaveMatchedNode(m.Call(
                func=m.Attribute(
                    value=m.DoNotCare(),
                    attr=m.Name(
                        value="model_dump_json",
                    ),
                ),
            ), "model_call"),
        ),
    ],
)

ERROR_WRAPPERS_VALIDATION_ERROR = m.Attribute(attr=m.Name("ValidationError"), value=m.Attribute(attr=m.Name("error_wrappers"), value=m.Name("pydantic")))

MOVED = {
    "pydantic.tools.schema_of": "pydantic.deprecated.tools.schema_of",
    "pydantic.tools.parse_obj_as": "pydantic.deprecated.tools.parse_obj_as",
    "pydantic.tools.schema_json_of": "pydantic.deprecated.tools.schema_json_of",
    "pydantic.json.pydantic_encoder": "pydantic.deprecated.json.pydantic_encoder",
    "pydantic.validate_arguments": "pydantic.deprecated.decorator.validate_arguments",
    "pydantic.json.custom_pydantic_encoder": "pydantic.deprecated.json.custom_pydantic_encoder",
    "pydantic.json.ENCODERS_BY_TYPE": "pydantic.deprecated.json.ENCODERS_BY_TYPE",
    "pydantic.json.timedelta_isoformat": "pydantic.deprecated.json.timedelta_isoformat",
    "pydantic.decorator.validate_arguments": "pydantic.deprecated.decorator.validate_arguments",
    "pydantic.class_validators.validator": "pydantic.deprecated.class_validators.validator",
    "pydantic.class_validators.root_validator": "pydantic.deprecated.class_validators.root_validator",
    "pydantic.utils.deep_update": "pydantic.v1.utils.deep_update",
    "pydantic.utils.GetterDict": "pydantic.v1.utils.GetterDict",
    "pydantic.utils.lenient_issubclass": "pydantic.v1.utils.lenient_issubclass",
    "pydantic.utils.lenient_isinstance": "pydantic.v1.utils.lenient_isinstance",
    "pydantic.utils.is_valid_field": "pydantic.v1.utils.is_valid_field",
    "pydantic.utils.update_not_none": "pydantic.v1.utils.update_not_none",
    "pydantic.utils.import_string": "pydantic.v1.utils.import_string",
    "pydantic.utils.Representation": "pydantic.v1.utils.Representation",
    "pydantic.utils.ROOT_KEY": "pydantic.v1.utils.ROOT_KEY",
    "pydantic.utils.smart_deepcopy": "pydantic.v1.utils.smart_deepcopy",
    "pydantic.utils.sequence_like": "pydantic.v1.utils.sequence_like",
}

def dotted_to_attr(dotted: str) -> Union[cst.Name, cst.Attribute]:
    parts = dotted.split(".")
    value = cst.Name(parts.pop(0))
    for part in parts:
        value = cst.Attribute(value=value, attr=cst.Name(part))
    return value

def dotted_to_attr_matcher(dotted: str) -> Union[m.Name, m.Attribute]:
    parts: list[str] = dotted.split(".")
    value = m.Name(parts.pop(0))
    for part in parts:
        value = m.Attribute(value=value, attr=m.Name(part))
    return value

def attr_to_dotted(attr: Union[cst.Name, cst.Attribute]) -> str:
    if isinstance(attr, cst.Name):
        return attr.value
    return f"{attr_to_dotted(attr.value)}.{attr.attr.value}"

MOVED_BY_MODULE: dict[str, list[tuple[str, str]]] = {}
for old, new in MOVED.items():
    old_mod, old_name = old.rsplit(".", 1)
    MOVED_BY_MODULE.setdefault(old_mod, []).append((old_name, new))

MOVED_IMPORT_MATCHERS = [
    m.ImportFrom(dotted_to_attr_matcher(mod)) for mod in MOVED_BY_MODULE.keys()
]

class ReplaceFunctionsCodemod(VisitorBasedCodemodCommand):
    def __init__(self, context: CodemodContext) -> None:
        super().__init__(context)

        self.has_import_from_pydantic: dict[str, bool] = {}

    @m.visit(m.OneOf(*(m_import_from_pydantic(old) for old in TYPE_ADAPTER_REPLACEMENTS.keys())))
    def visit_import_from_pydantic(self, node: cst.ImportFrom) -> None:
        if isinstance(node.names, cst.ImportStar):
            for key in TYPE_ADAPTER_REPLACEMENTS:
                self.has_import_from_pydantic[key] = True
            return
        for name in node.names:
            if name.name.value in TYPE_ADAPTER_REPLACEMENTS:
                self.has_import_from_pydantic[name.name.value] = True

    @m.leave(m.OneOf(*(m.Call(func=m_name_or_pydantic_attr(old)) for old in TYPE_ADAPTER_REPLACEMENTS.keys())))
    def leave_old_call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        if isinstance(updated_node.func, cst.Attribute):
            old_name = updated_node.func.attr.value
            type_adapter = cst.Attribute(value=cst.Name("pydantic"), attr=cst.Name("TypeAdapter"))
        else:
            old_name = cst.ensure_type(updated_node.func, cst.Name).value
            if not self.has_import_from_pydantic.get(old_name, False):
                return updated_node
            type_adapter = cst.Name("TypeAdapter")
            AddImportsVisitor.add_needed_import(context=self.context, module="pydantic", obj="TypeAdapter")
            RemoveImportsVisitor.remove_unused_import(context=self.context, module="pydantic", obj=old_name)
        new_func = cst.Attribute(
            value=cst.Call(func=type_adapter, args=[cst.Arg(value=updated_node.args[0].value)]),
            attr=cst.Name(TYPE_ADAPTER_REPLACEMENTS[old_name]),
        )
        return updated_node.with_changes(func=new_func, args=updated_node.args[1:])

    @m.visit(m.OneOf(*MOVED_IMPORT_MATCHERS))
    def visit_moved_import(self, node: cst.ImportFrom) -> None:
        old_module = attr_to_dotted(node.module)
        old_names = {old_name for old_name, _ in MOVED_BY_MODULE[old_module]}
        def update_import(name: str) -> None:
            old = f"{old_module}.{name}"
            new = MOVED[old]
            new_module = new.rsplit(".", 1)[0]
            AddImportsVisitor.add_needed_import(context=self.context, module=new_module, obj=name)
            RemoveImportsVisitor.remove_unused_import(context=self.context, module=old_module, obj=name)
        if isinstance(node.names, cst.ImportStar):
            for old_name in old_names:
                update_import(old_name)
            return
        for name in node.names:
            if name.name.value in old_names:
                update_import(name.name.value)

    @m.leave(m.OneOf(*(dotted_to_attr_matcher(old) for old in MOVED.keys())))
    def leave_moved_attr(self, original_node: cst.Attribute|cst.Name, updated_node: cst.Attribute|cst.Name) -> cst.Name|cst.Attribute:
        old = attr_to_dotted(updated_node)
        new = MOVED.get(old)
        if new is None:
            return updated_node
        new_module = new.rsplit(".", 1)[0]
        AddImportsVisitor.add_needed_import(context=self.context, module=new_module)
        return dotted_to_attr(new)

    @m.leave(JSON_LOADS_DUMP_JSON)
    def leave_json_loads_dump_json(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        extracted = m.extract(updated_node, JSON_LOADS_DUMP_JSON)
        if extracted is None:
            return updated_node
        model_call = cst.ensure_type(extracted.get("model_call"), cst.Call)
        return model_call.with_changes(func=model_call.func.with_changes(attr=cst.Name("model_dump")), args=[
            cst.Arg(
                keyword=cst.Name("mode"),
                value=cst.SimpleString('"json"'),
                equal=cst.AssignEqual(cst.SimpleWhitespace(""), cst.SimpleWhitespace(""))
            ), *model_call.args
        ])

    @m.leave(ERROR_WRAPPERS_VALIDATION_ERROR)
    def leave_error_wrappers_validation_error(self, original_node: cst.Attribute, updated_node: cst.Attribute) -> cst.Attribute:
        AddImportsVisitor.add_needed_import(context=self.context, module="pydantic")
        return updated_node.with_changes(value=cst.Name("pydantic"))
