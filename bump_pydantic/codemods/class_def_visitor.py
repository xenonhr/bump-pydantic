"""
There are two objects in the visitor:
1. `base_model_cls` (Set[str]): Set of classes that are BaseModel based.
2. `cls` (Dict[str, Set[str]]): A dictionary mapping each class definition to a set of base classes.

`base_model_cls` accumulates on each iteration.
`cls` also accumulates on each iteration, but it's also partially solved:
1. Check if the module visited is a prefix of any `cls.keys()`.
1.1. If it is, and if any `base_model_cls` is found, remove from `cls`, and add to `base_model_cls`.
1.2. If it's not, it continues on the `cls`
"""

from __future__ import annotations

import dataclasses
from collections import defaultdict

import libcst as cst
from libcst.codemod import CodemodContext, VisitorBasedCodemodCommand
from libcst.metadata import FullyQualifiedNameProvider, QualifiedName, QualifiedNameProvider


@dataclasses.dataclass
class PendingClass:
    pending_bases: set[str] = dataclasses.field(default_factory=set)
    subclasses: set[str] = dataclasses.field(default_factory=set)

@dataclasses.dataclass
class ClassCategory:
    known_members: set[str] = dataclasses.field(default_factory=set)
    known_non_members: set[str] = dataclasses.field(default_factory=set)
    pending: dict[str, PendingClass] = dataclasses.field(default_factory=lambda: defaultdict(PendingClass))

    def mark_as_member(self, fqn: str) -> None:
        self.known_members.add(fqn)
        if fqn in self.pending:
            pending_info = self.pending.pop(fqn)
            for subclass_fqn in pending_info.subclasses:
                self.mark_as_member(subclass_fqn)

    def mark_as_non_member(self, fqn: str) -> None:
        self.known_non_members.add(fqn)
        if fqn in self.pending:
            pending_info = self.pending.pop(fqn)
            for subclass_fqn in pending_info.subclasses:
                if subclass_fqn not in self.pending:
                    continue
                sub_info = self.pending[subclass_fqn]
                sub_info.pending_bases.discard(fqn)
                if not sub_info.pending_bases:
                    self.mark_as_non_member(subclass_fqn)

class ClassDefVisitor(VisitorBasedCodemodCommand):
    METADATA_DEPENDENCIES = {FullyQualifiedNameProvider, QualifiedNameProvider}

    BASE_MODEL_CONTEXT_KEY = "base_model_cls"

    def __init__(self, context: CodemodContext) -> None:
        super().__init__(context)

        self.models: ClassCategory = self.context.scratch.setdefault(self.BASE_MODEL_CONTEXT_KEY,
            ClassCategory(known_members={"pydantic.BaseModel", "pydantic.main.BaseModel"}))

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        self.update_membership(node, self.models)

    def update_membership(self, node: cst.ClassDef, category: ClassCategory) -> None:
        fqn_set = self.get_metadata(FullyQualifiedNameProvider, node)

        if not fqn_set:
            return None

        fqn: QualifiedName = next(iter(fqn_set))  # type: ignore

        if not node.bases:
            category.mark_as_non_member(fqn.name)
            return

        has_model_base = False
        unknown_bases: list[QualifiedName] = []
        for arg in node.bases:
            base_fqn_set = self.get_metadata(FullyQualifiedNameProvider, arg.value, set())
            for base_fqn in base_fqn_set:
                if base_fqn.name in category.known_members:
                    has_model_base = True
                    break
                elif base_fqn.name not in category.known_non_members:
                    unknown_bases.append(base_fqn)

        if has_model_base:
            category.mark_as_member(fqn.name)
        elif not unknown_bases:
            category.mark_as_non_member(fqn.name)
        else:
            category.pending[fqn.name].pending_bases = {base_fqn.name for base_fqn in unknown_bases}
            for base_fqn in unknown_bases:
                category.pending[base_fqn.name].subclasses.add(fqn.name)

    # TODO: Implement this if needed...
    def next_file(self, visited: set[str]) -> str | None:
        return None


class OrmarClassDefVisitor(ClassDefVisitor):
    BASE_MODEL_CONTEXT_KEY = "ormar_model_cls"

    def __init__(self, context: CodemodContext) -> None:
        context.scratch.setdefault(
            self.BASE_MODEL_CONTEXT_KEY,
            ClassCategory(known_members={"ormar.Model"}),
        )
        super().__init__(context)


class OrmarMetaClassDefVisitor(ClassDefVisitor):
    BASE_MODEL_CONTEXT_KEY = "ormar_model_meta_cls"

    def __init__(self, context: CodemodContext) -> None:
        context.scratch.setdefault(
            self.BASE_MODEL_CONTEXT_KEY,
            ClassCategory(known_members={"ormar.ModelMeta"}),
        )
        super().__init__(context)


if __name__ == "__main__":
    import os
    import textwrap
    from pathlib import Path
    from tempfile import TemporaryDirectory

    from libcst.metadata import FullRepoManager
    from rich.pretty import pprint

    with TemporaryDirectory(dir=os.getcwd()) as tmpdir:
        package_dir = f"{tmpdir}/package"
        os.mkdir(package_dir)
        module_path = f"{package_dir}/a.py"
        with open(module_path, "w") as f:
            content = textwrap.dedent(
                """
                from pydantic import BaseModel

                class Foo(BaseModel):
                    a: str

                class Bar(Foo):
                    b: str

                class Potato:
                    ...

                class Spam(Potato):
                    ...

                foo = Foo(a="text")
                foo.dict()
            """
            )
            f.write(content)
        module = str(Path(module_path).relative_to(tmpdir))
        mrg = FullRepoManager(tmpdir, {module}, providers={FullyQualifiedNameProvider})
        wrapper = mrg.get_metadata_wrapper_for_path(module)
        context = CodemodContext(wrapper=wrapper)
        command = ClassDefVisitor(context=context)
        mod = wrapper.visit(command)
        pprint(context.scratch[ClassDefVisitor.BASE_MODEL_CONTEXT_KEY])
