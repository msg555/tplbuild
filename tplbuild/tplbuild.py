import copy
from dataclasses import dataclass
from typing import List, Iterable, Optional, Tuple

from .images import ImageDefinition, SourceImage


@dataclass
class StageData:
    """
    Dataclass holding metadata about a rendered image stage.

    Attributes:
        name: The name of the build stage
        image: The image definition
        tags: Tags to apply to the built image
        push_tags: Tags to push for the built image
        base: True if this is a base image
    """

    name: str
    image: ImageDefinition
    tags: Tuple[str, ...] = ()
    push_tags: Tuple[str, ...] = ()
    base: bool = False


@dataclass
class BuildOperation:
    """
    Dataclass describing one build work unit. Each BuildOperation roughly
    corresponds to an invocation of the underlying image builder. Each
    operation in the chain of `image`, `image.parent`,
    `image.parent.parent`, ... up to but not including `root` will
    be part of this build unit.

    Attributes:
        image: The resulting image of this build operation
        root: The parent image of this build operation
        stages: All stages associated with the resulting image
        dependencies: All dependent build operations
    """

    image: ImageDefinition
    root: ImageDefinition
    stages: Tuple[StageData, ...] = ()
    dependencies: Tuple["BuildOperation", ...] = ()


class TplBuild:
    """
    Container class for all top level build operations.
    """

    def __init__(self, config) -> None:
        # Use pydantic?
        self.config = copy.deepcopy(config)

    def plan(self, stage_names: Iterable[StageData]) -> List[BuildOperation]:
        """
        Plan how to build the given list of stage names.
        """
        # pylint: disable=unused-argument,no-self-use
        return []

    def get_source_image(self, repo: str, tag: str) -> Optional[SourceImage]:
        """
        Return a ImageDefinition representation of the requested source image
        or None if there is no such source image set.
        """
        # pylint: disable=unused-argument,no-self-use
        return None
