from typing import Callable, Dict, Iterable, List, Optional, Tuple

from .exceptions import TplBuildException
from .hashing import json_hash
from .images import ImageDefinition

VisitFunc = Callable[[ImageDefinition], ImageDefinition]
VisitFuncPost = Callable[[ImageDefinition], None]


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


def hash_graph(
    roots: Iterable[ImageDefinition],
    *,
    salt: str = "",
    symbolic=True,
) -> Dict[ImageDefinition, str]:
    """
    Generate a mapping of image nodes to their hashes.

    Arguments:
        roots: The root of the build graph to hash.
        symbolic: If set the hash is computed symbolicly. Otherwise a full
            hash is done (in particular this means build contexts will be
            fully read and hashed).
    """
    hash_mapping: Dict[ImageDefinition, str] = {}

    def hash_node(image: ImageDefinition) -> None:
        hash_mapping[image] = json_hash(
            [
                salt,
                type(image).__name__,
                image.local_hash_data(symbolic),
                *(hash_mapping[dep] for dep in image.get_dependencies()),
            ]
        )

    visit_graph(roots, lambda image: image, visit_func_post=hash_node)
    return hash_mapping
