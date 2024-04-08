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


class ClassDefVisitor(VisitorBasedCodemodCommand):
    METADATA_DEPENDENCIES = {FullyQualifiedNameProvider, QualifiedNameProvider}

    BASE_MODEL_CONTEXT_KEY = "base_model_cls"
    NO_BASE_MODEL_CONTEXT_KEY = "no_base_model_cls"
    PENDING_CLS_CONTEXT_KEY = "unknown_cls"

    def __init__(self, context: CodemodContext) -> None:
        super().__init__(context)
        self.module_fqn: None | QualifiedName = None

        self.models: set[str] = self.context.scratch.setdefault(
            self.BASE_MODEL_CONTEXT_KEY,
            {"pydantic.BaseModel", "pydantic.main.BaseModel"},
        )
        self.non_models: set[str] = self.context.scratch.setdefault(self.NO_BASE_MODEL_CONTEXT_KEY, set())
        self.pending: dict[str, PendingClass] = self.context.scratch.setdefault(self.PENDING_CLS_CONTEXT_KEY, defaultdict(PendingClass))

    def _setIsModel(self, fqn: str) -> None:
        self.models.add(fqn)
        if fqn in self.pending:
            pending_info = self.pending.pop(fqn)
            for subclass_fqn in pending_info.subclasses:
                self._setIsModel(subclass_fqn)

    def _setIsNotModel(self, fqn: str) -> None:
        self.non_models.add(fqn)
        if fqn in self.pending:
            pending_info = self.pending.pop(fqn)
            for subclass_fqn in pending_info.subclasses:
                if subclass_fqn not in self.pending:
                    continue
                sub_info = self.pending[subclass_fqn]
                sub_info.pending_bases.discard(fqn)
                if not sub_info.pending_bases:
                    self._setIsNotModel(subclass_fqn)

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        fqn_set = self.get_metadata(FullyQualifiedNameProvider, node)

        if not fqn_set:
            return None

        fqn: QualifiedName = next(iter(fqn_set))  # type: ignore

        if not node.bases:
            self._setIsNotModel(fqn.name)
            return

        has_model_base = False
        unknown_bases: list[QualifiedName] = []
        for arg in node.bases:
            base_fqn_set = self.get_metadata(FullyQualifiedNameProvider, arg.value, set())
            for base_fqn in base_fqn_set:
                if base_fqn.name in self.models:
                    has_model_base = True
                    break
                elif base_fqn.name not in self.non_models:
                    unknown_bases.append(base_fqn)

        if has_model_base:
            self._setIsModel(fqn.name)
        elif not unknown_bases:
            self._setIsNotModel(fqn.name)
        else:
            self.pending[fqn.name].pending_bases = {base_fqn.name for base_fqn in unknown_bases}
            for base_fqn in unknown_bases:
                self.pending[base_fqn.name].subclasses.add(fqn.name)

    # TODO: Implement this if needed...
    def next_file(self, visited: set[str]) -> str | None:
        return None


class OrmarClassDefVisitor(ClassDefVisitor):
    BASE_MODEL_CONTEXT_KEY = "ormar_model_cls"
    NO_BASE_MODEL_CONTEXT_KEY = "no_ormar_model_cls"
    PENDING_CLS_CONTEXT_KEY = "ormar_unknown_cls"

    def __init__(self, context: CodemodContext) -> None:
        context.scratch.setdefault(
            self.BASE_MODEL_CONTEXT_KEY,
            {"ormar.Model"},
        )
        super().__init__(context)


class OrmarMetaClassDefVisitor(ClassDefVisitor):
    BASE_MODEL_CONTEXT_KEY = "ormar_model_meta_cls"
    NO_BASE_MODEL_CONTEXT_KEY = "no_ormar_model_meta_cls"
    PENDING_CLS_CONTEXT_KEY = "ormar_unknown_meta_cls"

    def __init__(self, context: CodemodContext) -> None:
        context.scratch.setdefault(
            self.BASE_MODEL_CONTEXT_KEY,
            {"ormar.ModelMeta"},
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
        pprint(context.scratch[ClassDefVisitor.NO_BASE_MODEL_CONTEXT_KEY])
        pprint(context.scratch[ClassDefVisitor.PENDING_CLS_CONTEXT_KEY])
