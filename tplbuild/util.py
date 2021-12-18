import json
from typing import Any, Callable, Iterable, List, Optional, Tuple

from .exceptions import TplBuildException
from .images import ImageDefinition

VisitFunc = Callable[[ImageDefinition], ImageDefinition]


def json_encode(data: Any) -> str:
    """Helper function to encode JSON data"""
    return json.dumps(data)


def json_decode(data: str) -> Any:
    """Helper function to decode JSON data"""
    return json.loads(data)


def json_raw_decode(data: str) -> Tuple[Any, int]:
    """Helper function to decode raw JSON data"""
    return json.JSONDecoder().raw_decode(data)


def visit_graph(root: ImageDefinition, visit_func: VisitFunc) -> ImageDefinition:
    """
    Traverses the image graph rooted at `root` calling `visit_func` with
    each image. The graph is traveresed in pre-order allowing `visit_func` to
    change a node before it is traversed.

    visit_graph will raise TplBuildException if a cycle is detected in the graph.
    It will also automatically skip images taht have been visited already.

    `visit_func` can return a new image object (or modify and return the passed
    image object) to modify the graph. Alternatively, `visit_func` may raise a
    StopIteration exception to not traverse further into the part of the graph
    rooted at the current image.
    """

    stack: List[Tuple[ImageDefinition, Optional[List[ImageDefinition]], int]] = [
        (root, None, 0)
    ]
    on_stack = set()
    remapped = {}
    while True:
        image, image_deps, dep_idx = stack[-1]
        if image_deps is None:
            try:
                new_image = visit_func(image)
            except StopIteration:
                stack.pop()
                if not stack:
                    return image
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
                raise TplBuildException("Cycle detected in build graph")

            # Check if we've visited this image before and apply its remapping.
            remapped_image = remapped.get(dep_image)
            if remapped_image is not None:
                image_deps[dep_idx] = remapped_image
                dep_image = None

            dep_idx += 1

        stack[-1] = (image, image_deps, dep_idx)
        if dep_image is None:
            image.set_dependencies(image_deps)
            on_stack.remove(image)
            stack.pop()
        else:
            stack.append((dep_image, None, 0))

        if not stack:
            return image


def line_reader(document: str) -> Iterable[Tuple[int, str]]:
    """
    Yield lines from `document`. Lines will have leading and trailing whitespace
    stripped. Lines that being with a '#' character will be omitted. Lines that
    end with a single backslash character will be treated as continuations with
    the following line concatenated onto itself, not including the backslash or
    line feed character.
    """
    line_parts = []
    lines = document.splitlines()
    for idx, line_part in enumerate(lines):
        line_part = line_part.rstrip()
        if line_part.endswith("\\") and not line_part.endswith("\\\\"):
            line_parts.append(line_part[:-1])
            if idx + 1 < len(lines):
                continue
            line_part = ""

        line = ("".join(line_parts) + line_part).strip()
        line_parts.clear()
        if line and line[0] != "#":
            yield idx, line
