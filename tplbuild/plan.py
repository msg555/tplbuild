import collections
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from .images import (
    BaseImage,
    ContextImage,
    CopyCommandImage,
    ImageDefinition,
    SourceImage,
)
from .render import StageData
from .utils import (
    hash_graph,
    visit_graph,
)


@dataclass(eq=False)
class BuildOperation:
    """
    Dataclass describing one build work unit. Each BuildOperation roughly
    corresponds to an invocation of the underlying image builder. In some
    cases it may instead just simplify to retagging existing images.

    Each operation in the chain of `image`, `image.parent`,
    `image.parent.parent`, ... up to but not including `root` will
    be part of this build unit. If `inline_context` is not None then
    it should be used as the build context.
    """

    #: The resulting image of this build operation
    image: ImageDefinition
    #: The parent image of this build operation
    root: ImageDefinition
    #: The inline context to pass to the build, if any. A context can
    #: only be inlined if its needed nowhere else.
    inline_context: Optional[ContextImage] = None
    #: All stages associated with the resulting image
    stages: Tuple[StageData, ...] = ()
    #: All dependent build operations
    dependencies: Tuple["BuildOperation", ...] = ()


class BuildPlanner:
    """
    Class responsible for group consecutive images together that can be
    grouped and generating a dependency graph on those grouped build
    operatons.
    """

    def plan(self, stages: Iterable[StageData]) -> List[BuildOperation]:
        """
        Plan converts the rendered stage data information into a concrete
        build plan. The plan is returned as a list of build operations
        topologically sorted such that a build operation appears in the
        list after all of its dependencies.

        Arguments:
            stages: An iterable of what stages should be included in
                    the bulid plan. This can be a subset of the rendered
                    images; any required dependant stages will automatically
                    be built but their tags will not be set if not listed here.
        """
        stage_data = list(stage for stage in stages if stage.tags or stage.push_tags)
        stage_images = [stage.image for stage in stage_data]
        hash_mapping = hash_graph(stage_images)

        reverse_deps = collections.defaultdict(set)
        canonical_image: Dict[str, ImageDefinition] = {}

        def canonicalize(image: ImageDefinition) -> ImageDefinition:
            return canonical_image.setdefault(hash_mapping[image], image)

        def mark_deps(image: ImageDefinition) -> None:
            for idx, dep in enumerate(image.get_dependencies()):
                reverse_deps[dep].add((idx, image))

        # Normalize all images with the same hash into the same object.
        # At the same time create a reverse dependency graph on those
        # objects.
        stage_images = visit_graph(
            stage_images,
            canonicalize,
            visit_func_post=mark_deps,
        )

        stages_by_image = collections.defaultdict(list)
        for stage, stage_image in zip(stage_data, stage_images):
            stages_by_image[stage_image].append(stage)

        build_ops: Dict[ImageDefinition, BuildOperation] = {}
        build_op_ctx_dependants = collections.defaultdict(set)
        build_op_other_dependants = collections.defaultdict(set)

        def create_op(image: ImageDefinition):
            """
            Creates all the build operations
            """
            dependants = reverse_deps.get(image, set())
            stages = tuple(stages_by_image.get(image, []))
            if (
                not stages
                and len(dependants) == 1
                and all(idx == 0 for idx, _ in dependants)
            ):
                # Mid-build operation image, do nothing.
                return

            # Generate build op, walking back the root as far as we can.
            root = image
            build_op_ctx_deps = set()
            build_op_other_deps = set()
            while root not in build_ops:
                if isinstance(root, CopyCommandImage):
                    # Specially mark context dependencies to support inlining.
                    build_op_ctx_deps.add(build_ops[root.context])
                    root = root.parent
                    continue

                # Other images we handle generically.
                deps = root.get_dependencies()
                if not deps:
                    break
                for dep in deps[1:]:
                    build_op_other_deps.add(build_ops[dep])
                root = deps[0]
            else:
                build_op_other_deps.add(build_ops[root])

            build_op = BuildOperation(
                image=image,
                root=root,
                stages=tuple(stages_by_image.get(image, [])),
                dependencies=tuple(build_op_ctx_deps | build_op_other_deps),
            )
            for build_op_dep in build_op_ctx_deps:
                build_op_ctx_dependants[build_op_dep].add(build_op)
            for build_op_dep in build_op_other_deps:
                build_op_other_dependants[build_op_dep].add(build_op)
            build_ops[image] = build_op

        visit_graph(stage_images, lambda img: img, visit_func_post=create_op)

        removed_build_ops = set()
        for image, build_op in build_ops.items():
            if not build_op.stages and isinstance(image, (BaseImage, SourceImage)):
                # base/source images that do not correspond to a stage do not
                # represent any work so we skip them.
                removed_build_ops.add(build_op)
            elif isinstance(image, ContextImage):
                # Remove and inline contexts that are only used in one place if
                # their one use does not already have an inline.
                if (
                    build_op not in build_op_other_dependants
                    and len(build_op_ctx_dependants[build_op]) == 1
                ):
                    (dependant_build_op,) = build_op_ctx_dependants[build_op]
                    if dependant_build_op.inline_context is None:
                        dependant_build_op.inline_context = image
                        removed_build_ops.add(build_op)

        # Prune out any removed build operations from the dependency list.
        for build_op in build_ops.values():
            build_op.dependencies = tuple(
                dep_build_op
                for dep_build_op in build_op.dependencies
                if dep_build_op not in removed_build_ops
            )

        # Return the result as a list, don't need the final image as a key anymore.
        return [
            build_op
            for build_op in build_ops.values()
            if build_op not in removed_build_ops
        ]
