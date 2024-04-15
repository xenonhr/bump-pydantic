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

