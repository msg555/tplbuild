import abc
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from .context import BuildContext
from .utils import format_simple


class ImageDefinition(metaclass=abc.ABCMeta):
    """
    Base class for all image deinitions. These abstractly represent a build
    graph.
    """

    @abc.abstractmethod
    def local_hash_data(self, symbolic: bool) -> Any:
        """
        Return a JSON-able payload suitable for hashing the image node. This
        should not recursively include hashes of any dependencies.
        """
        return None

    def get_dependencies(self) -> List["ImageDefinition"]:
        """
        Returns a list of image dependencies for this image node. The first
        dependant is considered the "primary" dependant.
        """
        return []

    def set_dependencies(self, deps: Iterable["ImageDefinition"]) -> None:
        """
        Sets the dependencies for this image. This must be the correct size
        for the image type.
        """
        assert not tuple(deps)


@dataclass(eq=False)
class CommandImage(ImageDefinition):
    """Image node ending in a command other than COPY."""

    parent: ImageDefinition
    command: str
    args: str

    def local_hash_data(self, symbolic: bool) -> Any:
        """Return the local hash data for this node."""
        return [
            self.command,
            self.args,
        ]

    def get_dependencies(self) -> List[ImageDefinition]:
        return [self.parent]

    def set_dependencies(self, deps: Iterable[ImageDefinition]) -> None:
        (self.parent,) = deps


@dataclass(eq=False)
class CopyCommandImage(ImageDefinition):
    """Image node ending in a COPY command"""

    parent: ImageDefinition
    context: ImageDefinition
    command: str

    def local_hash_data(self, symbolic: bool) -> str:
        return self.command

    def get_dependencies(self) -> List[ImageDefinition]:
        return [self.parent, self.context]

    def set_dependencies(self, deps: Iterable[ImageDefinition]) -> None:
        self.parent, self.context = deps


@dataclass(eq=False)
class SourceImage(ImageDefinition):
    """Image node representing a source image"""

    repo: str
    tag: str
    platform: str = ""
    digest: Optional[str] = None

    def local_hash_data(self, symbolic: bool) -> Any:
        if symbolic:
            return [self.repo, self.tag, self.platform]

        if self.digest is None:
            raise ValueError("Cannot full hash SourceImage with unresolved digest")

        return [self.platform, self.digest]


@dataclass(eq=False)
class MultiPlatformImage(ImageDefinition):
    """
    Container image node that merges multiple other images into a single
    manifest list.

    Attributes:
        images: Mapping of platform names to images.
    """

    images: Dict[str, ImageDefinition]

    def get_dependencies(self) -> List[ImageDefinition]:
        return list(self.images.values())

    def set_dependencies(self, deps: Iterable[ImageDefinition]) -> None:
        for platform, dep in zip(self.images, deps):
            self.images[platform] = dep

    def local_hash_data(self, symbolic: bool) -> Any:
        return list(self.images)


@dataclass(eq=False)
class BaseImage(ImageDefinition):
    """
    Image node representing a base image.

    Attributes:
        profile: Name of the profile this base image belongs to
        stage: Name of the build stage
        platform: The platform to select for this base image. For platform
            aware builds if platform is empty than this node represents the
            multi platform manifest list itself. Platform unaware builds
            should have this be empty.
        image: The build graph behind this base image. This can be None if
            the base image will not be dereferenced.
        content_hash: The conent hash of the base image. Typically this is
            supplied from tplbuild's cached build data and is used to find
            the base image from an external repository.
    """

    profile: str
    stage: str
    platform: str = ""
    image: Optional[ImageDefinition] = None
    content_hash: Optional[str] = None

    def get_dependencies(self) -> List[ImageDefinition]:
        return [self.image] if self.image else []

    def set_dependencies(self, deps: Iterable[ImageDefinition]) -> None:
        if deps:
            (self.image,) = deps

    def get_image_name(self, base_image_repo: str) -> str:
        """
        Return the appropriate image name given the passed base_image_repo format.
        `base_image_repo` will be formatted with the keyword arguments `profile`,
        set to the name of the profile this base image was rendered from, and
        `stage`, set to the name of the stage of this base image.
        """
        if self.content_hash is None:
            raise ValueError("Cannot get image name of base image with no content hash")

        return (
            format_simple(
                base_image_repo,
                profile=self.profile,
                stage=self.stage,
            )
            + f":{self.content_hash}"
        )

    def local_hash_data(self, symbolic: bool) -> Any:
        if symbolic:
            return [self.profile, self.stage, self.platform]

        if self.content_hash is None:
            raise ValueError("Cannot hash BaseImage with unresolved content hash")

        return [self.content_hash, self.platform]


@dataclass(eq=False)
class ContextImage(ImageDefinition):
    """Image node representing a build context"""

    context: BuildContext

    def local_hash_data(self, symbolic: bool) -> str:
        return self.context.symbolic_hash if symbolic else self.context.full_hash
