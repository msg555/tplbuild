import contextlib
import json
import os
import tempfile
from typing import Any, Callable, Iterable, List, Optional, Tuple

from .exceptions import TplBuildException
from .images import ImageDefinition

VisitFunc = Callable[[ImageDefinition], ImageDefinition]
VisitFuncPost = Callable[[ImageDefinition], None]


def json_encode(data: Any) -> str:
    """Helper function to encode JSON data"""
    return json.dumps(data)


def json_decode(data: str) -> Any:
    """Helper function to decode JSON data"""
    return json.loads(data)


def json_raw_decode(data: str) -> Tuple[Any, int]:
    """Helper function to decode raw JSON data"""
    return json.JSONDecoder().raw_decode(data)


def visit_graph(
    roots: Iterable[ImageDefinition],
    visit_func: VisitFunc,
    *,
    visit_func_post: Optional[VisitFuncPost] = None,
) -> List[ImageDefinition]:
    """
    Traverses the image graph from the passed `roots` calling `visit_func` with
    each image. The graph is traveresed in pre-order allowing `visit_func` to
    change a node before it is traversed. `visit_func_post` can optionally
    also be provided. If given this will be called with each image in post-order,
    i.e. after each dependant image has been processed.

    visit_graph will raise TplBuildException if a cycle is detected in the graph.
    It will also automatically skip images taht have been visited already.
    visit_graph will return a list of the update image roots in the same order
    they were passed to visit_graph.

    `visit_func` can return a new image object (or modify and return the passed
    image object) to modify the graph. Alternatively, `visit_func` may raise a
    StopIteration exception to not traverse further into the part of the graph
    rooted at the current image.
    """

    roots_list = list(roots)
    stack: List[
        Tuple[Optional[ImageDefinition], Optional[List[ImageDefinition]], int]
    ] = [(None, roots_list, 0)]
    on_stack = set()
    remapped = {}
    while True:
        image, image_deps, dep_idx = stack[-1]
        if image_deps is None:
            assert image is not None
            try:
                new_image = visit_func(image)
            except StopIteration:
                stack.pop()
                continue

            # Store the remapping
            remapped[image] = new_image
            image = new_image
            image_deps = image.get_dependencies()
            on_stack.add(image)

            # Update dependant for parent image if not root.
            if len(stack) > 1:
                assert stack[-2][1] is not None
                stack[-2][1][stack[-2][2] - 1] = image

        dep_image = None
        while dep_image is None and dep_idx < len(image_deps):
            dep_image = image_deps[dep_idx]
            if dep_image in on_stack:
                raise TplBuildException("Cycle detected in graph")

            # Check if we've visited this image before and apply its remapping.
            remapped_image = remapped.get(dep_image)
            if remapped_image is not None:
                image_deps[dep_idx] = remapped_image
                dep_image = None

            dep_idx += 1

        stack[-1] = (image, image_deps, dep_idx)
        if dep_image is None:
            if len(stack) == 1:
                return roots_list

            assert image is not None
            image.set_dependencies(image_deps)
            on_stack.remove(image)
            stack.pop()
            if visit_func_post is not None:
                visit_func_post(image)
        else:
            stack.append((dep_image, None, 0))


def line_reader(document: str) -> Iterable[Tuple[int, str]]:
    """
    Yield lines from `document`. Lines will have leading and trailing whitespace
    stripped. Lines that being with a '#' character will be omitted. Lines that
    end with a single backslash character will be treated as continuations with
    the following line concatenated onto itself, not including the backslash or
    line feed character.
    """
    line_parts: List[str] = []
    lines = document.splitlines()
    for idx, line_part in enumerate(lines):
        line_part = line_part.rstrip()
        if not line_parts and line_part.lstrip().startswith("#"):
            continue
        if line_part.endswith("\\") and not line_part.endswith("\\\\"):
            line_parts.append(line_part[:-1])
            if idx + 1 < len(lines):
                continue
            line_part = ""

        line = ("".join(line_parts) + line_part).strip()
        line_parts.clear()
        if line:
            yield idx, line


@contextlib.contextmanager
def open_and_swap(filename, mode="w+b", buffering=-1, encoding=None, newline=None):
    """
    Open a file for writing and relink it to the desired path in an atomic
    operation when the file is closed without an exception. This prevents
    the existing file data from being lost if an unexpected failure occurs
    while writing the file.
    """
    fd, tmppath = tempfile.mkstemp(
        dir=os.path.dirname(filename) or ".",
        text="b" not in mode,
    )
    fh = None
    try:
        fh = open(
            fd,
            mode=mode,
            buffering=buffering,
            encoding=encoding,
            newline=newline,
            closefd=False,
        )
        yield fh
        os.rename(tmppath, filename)
        tmppath = None
    finally:
        if fh is not None:
            fh.close()
        os.close(fd)
        if tmppath is not None:
            os.unlink(tmppath)
