import difflib
import functools
import itertools
import json
import multiprocessing
import os
import platform
import subprocess
import time
import traceback
from collections import deque
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, Type, TypeVar, Union

import libcst as cst
from libcst.codemod import CodemodContext, ContextAwareTransformer
from libcst.helpers import calculate_module_and_package
from libcst.metadata import (
    FilePathProvider,
    FullRepoManager,
    FullyQualifiedNameProvider,
    NonCachedTypeInferenceProvider,
    ScopeProvider,
)
from rich.console import Console
from rich.progress import Progress
from typer import Argument, Exit, Option, Typer, echo
from typing_extensions import ParamSpec

from bump_pydantic import __version__
from bump_pydantic.codemods import Rule, gather_codemods
from bump_pydantic.codemods.class_def_visitor import ClassCategory, ClassDefVisitor
from bump_pydantic.glob_helpers import match_glob

app = Typer(invoke_without_command=True, add_completion=False)

entrypoint = functools.partial(app, windows_expand_args=False)

P = ParamSpec("P")
T = TypeVar("T")

DEFAULT_IGNORES = [".venv/**", ".tox/**", ".git/**"]


def version_callback(value: bool):
    if value:
        echo(f"bump-pydantic version: {__version__}")
        raise Exit()

_T = TypeVar("_T")

def batch_iterator(iterable:Iterable[_T], n:int) -> Iterable[List[_T]]:
    it = iter(iterable)
    while (batch := list(itertools.islice(it, n))):
        yield batch

@app.callback()
def main(
    path: Path = Argument(..., exists=True, dir_okay=True, allow_dash=False),
    disable: List[Rule] = Option(default=[], help="Disable a rule."),
    diff: bool = Option(False, help="Show diff instead of applying changes."),
    ignore: List[str] = Option(default=DEFAULT_IGNORES, help="Ignore a path glob pattern."),
    log_file: Path = Option("log.txt", help="Log errors to this file."),
    process_single_file: Optional[Path] = Option(default=None, help="Process a single file."),
    processes: Optional[int] = Option(default=os.cpu_count(), help="Maximum number of processes to use."),
    version: bool = Option(
        None,
        "--version",
        callback=version_callback,
        is_eager=True,
        help="Show the version and exit.",
    ),
):
    """Convert Pydantic from V1 to V2 ♻️

    Check the README for more information: https://github.com/pydantic/bump-pydantic.
    """
    console = Console(log_time=True)
    console.log("Start bump-pydantic.")
    # NOTE: LIBCST_PARSER_TYPE=native is required according to https://github.com/Instagram/LibCST/issues/487.
    os.environ["LIBCST_PARSER_TYPE"] = "native"

    # Windows has a limit of 61 processes. See https://github.com/python/cpython/issues/89240.
    if platform.system() == "Windows" and processes is not None:
        processes = min(processes, 61)

    if os.path.isfile(path):
        package = path.parent
        all_files = [path]
    else:
        package = path
        all_files = sorted(package.glob("**/*.py"))

    filtered_files = [file for file in all_files if not any(match_glob(file, pattern) for pattern in ignore)]
    files = [str(file.relative_to(".")) for file in filtered_files]

    if len(files) == 1:
        console.log("Found 1 file to process.")
    elif len(files) > 1:
        console.log(f"Found {len(files)} files to process.")
    else:
        console.log("No files to process.")
        raise Exit()

    # Note: we do _not_ cache TypeInferenceProvider because it takes forever and will eventually cause an OOM.
    # It's silly to cache all type inferences for the entire repo.
    providers = {FullyQualifiedNameProvider, ScopeProvider, FilePathProvider}
    metadata_manager = FullRepoManager(".", files, providers=providers, timeout=3600)  # type: ignore[arg-type]
    metadata_manager.resolve_cache()

    count_errors = 0
    log_fp = log_file.open("a+", encoding="utf8")

    scratch: dict[str, Any] = {}
    scan_needed = True
    if (package / ".pyre_configuration").exists():
        console.log("Found .pyre_configuration file. Using Pyre to find class families.")
        try:
            families = [
                (ClassDefVisitor.BASE_MODEL_CONTEXT_KEY, {"pydantic.BaseModel", "pydantic.main.BaseModel"}),
                (ClassDefVisitor.ORMAR_MODEL_CONTEXT_KEY, {"ormar.Model", "ormar.models.model.Model"}),
                (ClassDefVisitor.ORMAR_META_CONTEXT_KEY, {"ormar.ModelMeta", "ormar.models.metaclass.ModelMeta"}),
            ]
            class_sets = find_class_families_using_pyre([f[1] for f in families])
            for (key, _), class_set in zip(families, class_sets):
                scratch[key] = ClassCategory(known_members=class_set)
            scan_needed = False
        except Exception as e:
            console.log(f"Failed to use Pyre to find class families: {e}")
    if scan_needed:
        for error in scan_for_classes(files, metadata_manager, scratch, package):
            count_errors += 1
            log_fp.writelines(error)

    for name, key in [
        ("pydantic_models.txt", ClassDefVisitor.BASE_MODEL_CONTEXT_KEY),
        ("ormar_models.txt", ClassDefVisitor.ORMAR_MODEL_CONTEXT_KEY),
        ("ormar_meta.txt", ClassDefVisitor.ORMAR_META_CONTEXT_KEY),
    ]:
        console.log(f"Found {len(scratch[key].known_members)} members of {key}.")
        with open(name, "w") as f:
            for fqn in sorted(scratch[key].known_members):
                f.write(f"{fqn}\n")

    start_time = time.time()

    codemods = gather_codemods(disabled=disable)

    partial_run_codemods = functools.partial(run_codemods_batched, codemods, metadata_manager, scratch, package, diff)
    batch_size = 16
    if process_single_file:
        error, difflines = partial_run_codemods([str(process_single_file.relative_to("."))])
    else:
        with Progress(*Progress.get_default_columns(), transient=True) as progress:
            task = progress.add_task(description="Executing codemods...", total=(len(files)+batch_size-1)//batch_size)
            difflines: List[List[str]] = []
            with multiprocessing.Pool(processes=processes) as pool:
                for batch_errors, batch_diffs in pool.imap_unordered(partial_run_codemods, batch_iterator(files, batch_size)):
                    progress.advance(task)
                    difflines.extend(batch_diffs)
                    if batch_errors:
                        count_errors += len(batch_errors)
                        log_fp.writelines(batch_errors)

    modified = [Path(f) for f in files if os.stat(f).st_mtime > start_time]

    if not diff:
        if modified:
            console.log(f"Refactored {len(modified)} files.")
        else:
            console.log("No files were modified.")

    for _difflines in difflines:
        color_diff(console, _difflines)

    if count_errors > 0:
        console.log(f"Found {count_errors} errors. Please check the {log_file} file.")
    else:
        console.log("Run successfully!")

    if difflines:
        raise Exit(1)


def run_codemods_batched(
    codemods: List[Type[ContextAwareTransformer]],
    metadata_manager: FullRepoManager,
    scratch: Dict[str, Any],
    package: Path,
    diff: bool,
    filenames: list[str],
) -> Tuple[list[str], list[list[str]]]:
    errors: list[str] = []
    diffs: List[List[str]] = []
    NonCachedTypeInferenceProvider.cache_batch(filenames)
    for filename in filenames:
        one_error, one_difflines = run_codemods(codemods, metadata_manager, scratch, package, diff, filename)

        if one_difflines is not None:
            diffs.append(one_difflines)

        if one_error is not None:
            errors.append(one_error)
    return errors, diffs

def find_class_families_using_pyre(root_sets: list[set[str]]) -> list[set[str]]:
    families = [set(r) for r in root_sets]
    cmd_args = ["pyre", "--noninteractive", "query", "dump_class_hierarchy()"]
    stdout = subprocess.run(cmd_args, check=True, stdout=subprocess.PIPE).stdout
    resp = json.loads(stdout)["response"]
    for entry in resp:
        for class_fqn, class_ancestors in entry.items():
            for roots, family in zip(root_sets, families):
                if any(a in roots for a in class_ancestors):
                    family.add(class_fqn)
    return families


def scan_for_classes(files: list[str], metadata_manager: FullRepoManager, scratch: dict[str, Any], package: Path) -> list[str]:
    errors: list[str] = []
    with Progress(*Progress.get_default_columns(), transient=True) as progress:
        task = progress.add_task(description="Looking for Pydantic Models...", total=len(files))
        queue = deque(files)
        visited: Set[str] = set()

        while queue:
            # Queue logic
            filename = queue.popleft()
            visited.add(filename)
            progress.advance(task)

            # Visitor logic
            code = Path(filename).read_text(encoding="utf8")
            try:
                module = cst.parse_module(code)
                module_and_package = calculate_module_and_package(str(package), filename)

                context = CodemodContext(
                    metadata_manager=metadata_manager,
                    filename=filename,
                    full_module_name=module_and_package.name,
                    full_package_name=module_and_package.package,
                    scratch=scratch,
                )
                visitor = ClassDefVisitor(context=context)
                visitor.transform_module(module)

                # Queue logic
                next_file = visitor.next_file(visited)
                if next_file is not None:
                    queue.appendleft(next_file)
            except Exception:
                errors.append(f"An error happened on {filename}.\n{traceback.format_exc()}")
                # count_errors += 1
                # log_fp.writelines(f"An error happened on {filename}.\n{traceback.format_exc()}")
                continue
    return errors


def run_codemods(
    codemods: List[Type[ContextAwareTransformer]],
    metadata_manager: FullRepoManager,
    scratch: Dict[str, Any],
    package: Path,
    diff: bool,
    filename: str,
) -> Tuple[Union[str, None], Union[List[str], None]]:
    try:
        module_and_package = calculate_module_and_package(str(package), filename)
        context = CodemodContext(
            metadata_manager=metadata_manager,
            filename=filename,
            full_module_name=module_and_package.name,
            full_package_name=module_and_package.package,
        )
        context.scratch.update(scratch)

        file_path = Path(filename)
        with file_path.open("r+", encoding="utf-8") as fp:
            code = fp.read()
            fp.seek(0)

            input_tree = cst.parse_module(code)

            for codemod in codemods:
                transformer = codemod(context=context)
                output_tree = transformer.transform_module(input_tree)
                input_tree = output_tree

            output_code = input_tree.code
            if code != output_code:
                if diff:
                    lines = difflib.unified_diff(
                        code.splitlines(keepends=True),
                        output_code.splitlines(keepends=True),
                        fromfile=filename,
                        tofile=filename,
                    )
                    return None, list(lines)
                else:
                    fp.write(output_code)
                    fp.truncate()
        return None, None
    except cst.ParserSyntaxError as exc:
        return (
            f"A syntax error happened on {filename}. This file cannot be formatted.\n"
            "Check https://github.com/pydantic/bump-pydantic/issues/124 for more information.\n"
            f"{exc}"
        ), None
    except Exception:
        return f"An error happened on {filename}.\n{traceback.format_exc()}", None


def color_diff(console: Console, lines: Iterable[str]) -> None:
    for line in lines:
        line = line.rstrip("\n")
        if line.startswith("+"):
            console.print(line, style="green")
        elif line.startswith("-"):
            console.print(line, style="red")
        elif line.startswith("^"):
            console.print(line, style="blue")
        else:
            console.print(line, style="white")
