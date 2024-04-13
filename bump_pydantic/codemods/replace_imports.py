"""
This codemod deals with the following cases:

1. `from pydantic import BaseSettings`
2. `from pydantic.settings import BaseSettings`
3. `from pydantic import BaseSettings as <name>`
4. `from pydantic.settings import BaseSettings as <name>`  # TODO: This is not working.
5. `import pydantic` -> `pydantic.BaseSettings`
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import libcst as cst
import libcst.matchers as m
from libcst.codemod import CodemodContext, VisitorBasedCodemodCommand
from libcst.codemod.visitors import AddImportsVisitor
from libcst.metadata import FullyQualifiedNameProvider

from bump_pydantic.codemods.class_def_visitor import ClassDefVisitor

IMPORTS = {
    "pydantic:BaseSettings": ("pydantic_settings", "BaseSettings"),
    "pydantic.settings:BaseSettings": ("pydantic_settings", "BaseSettings"),
    "pydantic:Color": ("pydantic_extra_types.color", "Color"),
    "pydantic.color:Color": ("pydantic_extra_types.color", "Color"),
    "pydantic:PaymentCardNumber": ("pydantic_extra_types.payment", "PaymentCardNumber"),
    "pydantic.payment:PaymentCardBrand": (
        "pydantic_extra_types.payment",
        "PaymentCardBrand",
    ),
    "pydantic.payment:PaymentCardNumber": (
        "pydantic_extra_types.payment",
        "PaymentCardNumber",
    ),
    "typing:TypedDict": ("typing_extensions", "TypedDict"),
}


def resolve_module_parts(module_parts: list[str]) -> m.Attribute | m.Name:
    if len(module_parts) == 1:
        return m.Name(module_parts[0])
    if len(module_parts) == 2:
        first, last = module_parts
        return m.Attribute(value=m.Name(first), attr=m.Name(last))
    last_name = module_parts.pop()
    attr = resolve_module_parts(module_parts)
    return m.Attribute(value=attr, attr=m.Name(last_name))


def get_import_from_from_str(import_str: str) -> m.ImportFrom:
    """Converts a string like `pydantic:BaseSettings` to an `ImportFrom` node.

    Examples:
        >>> get_import_from_from_str("pydantic:BaseSettings")
        ImportFrom(
            module=Name("pydantic"),
            names=[ImportAlias(name=Name("BaseSettings"))],
        )
        >>> get_import_from_from_str("pydantic.settings:BaseSettings")
        ImportFrom(
            module=Attribute(value=Name("pydantic"), attr=Name("settings")),
            names=[ImportAlias(name=Name("BaseSettings"))],
        )
        >>> get_import_from_from_str("a.b.c:d")
        ImportFrom(
            module=Attribute(
                value=Attribute(value=Name("a"), attr=Name("b")), attr=Name("c")
            ),
            names=[ImportAlias(name=Name("d"))],
        )
    """
    module, name = import_str.split(":")
    module_parts = module.split(".")
    module_node = resolve_module_parts(module_parts)
    return m.ImportFrom(
        module=module_node,
        names=[m.ZeroOrMore(), m.ImportAlias(name=m.Name(value=name)), m.ZeroOrMore()],
    )


@dataclass
class ImportInfo:
    import_from: m.ImportFrom
    import_str: str
    to_import_str: tuple[str, str]


IMPORT_INFOS = [
    ImportInfo(
        import_from=get_import_from_from_str(import_str),
        import_str=import_str,
        to_import_str=to_import_str,
    )
    for import_str, to_import_str in IMPORTS.items()
]
IMPORT_MATCH = m.OneOf(*[info.import_from for info in IMPORT_INFOS])


class ReplaceImportsCodemod(VisitorBasedCodemodCommand):

    METADATA_DEPENDENCIES = (FullyQualifiedNameProvider,)

    def __init__(self, context: CodemodContext) -> None:
        super().__init__(context)
        self.pydantic_model_bases = self.context.scratch[ClassDefVisitor.BASE_MODEL_CONTEXT_KEY].known_members

    def _is_pydantic_model(self, node: cst.CSTNode) -> bool:
        fqn_set = self.get_metadata(FullyQualifiedNameProvider, node, set())
        return any(fqn.name in self.pydantic_model_bases for fqn in fqn_set)

    def visit_Module(self, node: cst.Module) -> None:
        match_pydantic_model = m.ClassDef() & m.MatchIfTrue(self._is_pydantic_model)
        self.has_pydantic_model = bool(m.findall(node, match_pydantic_model))

    @m.leave(IMPORT_MATCH)
    def leave_replace_import(self, _: cst.ImportFrom, updated_node: cst.ImportFrom) -> cst.ImportFrom:
        for import_info in IMPORT_INFOS:
            if m.matches(updated_node, import_info.import_from):
                # We only need to replace TypedDict if we have a pydantic model in the file.
                if import_info.to_import_str[1] == "TypedDict" and not self.has_pydantic_model:
                    break
                aliases: Sequence[cst.ImportAlias] = updated_node.names  # type: ignore
                # If multiple objects are imported in a single import statement,
                # we need to remove only the one we're replacing.
                AddImportsVisitor.add_needed_import(self.context, *import_info.to_import_str)
                if len(updated_node.names) > 1:  # type: ignore
                    names = [alias for alias in aliases if alias.name.value != import_info.to_import_str[-1]]
                    names[-1] = names[-1].with_changes(comma=cst.MaybeSentinel.DEFAULT)
                    updated_node = updated_node.with_changes(names=names)
                else:
                    return cst.RemoveFromParent()  # type: ignore[return-value]
        return updated_node


if __name__ == "__main__":
    import textwrap

    from rich.console import Console

    console = Console()

    source = textwrap.dedent(
        """
        from pydantic.settings import BaseSettings
        from pydantic.color import Color
        from pydantic.payment import PaymentCardNumber, PaymentCardBrand
        from pydantic import Color
        from pydantic import Color as Potato


        class Potato(BaseSettings):
            color: Color
            payment: PaymentCardNumber
            brand: PaymentCardBrand
            potato: Potato
        """
    )
    console.print(source)
    console.print("=" * 80)

    mod = cst.parse_module(source)
    context = CodemodContext(filename="main.py")
    wrapper = cst.MetadataWrapper(mod)
    command = ReplaceImportsCodemod(context=context)

    mod = wrapper.visit(command)
    wrapper = cst.MetadataWrapper(mod)
    command = AddImportsVisitor(context=context)  # type: ignore[assignment]
    mod = wrapper.visit(command)
    console.print(mod.code)
