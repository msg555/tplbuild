import abc
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set

from .config import StageConfig
from .context import BuildContext


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

    def merge_into(self, image: "ImageDefinition") -> None:
        """
        Called during planning during the canonicalization phase. Two images will
        be merged if they represent the same build step. This step allows for
        bookkeepping when tracking what image definitions came from where.
        """


@dataclass(frozen=True)
class StageDescriptor:
    """Describes a rendered stage"""

    name: str
    profile: str
    platform: str


@dataclass(eq=False)  # type: ignore
class StageDefinedImage(ImageDefinition):  # pylint: disable=abstract-method
    """
    Parent class for image nodes that are defined by build stages. This is
    meant to help facilitate bookkeeping for display/debug purposes of where
    an image node was defined.
    """

    stage_descs: Set[StageDescriptor]

    def merge_into(self, image: ImageDefinition) -> None:
        """Merge the stage descriptors together."""
        assert isinstance(image, StageDefinedImage)
        self.stage_descs.update(image.stage_descs)


@dataclass(eq=False)
class CommandImage(StageDefinedImage):
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
class CopyCommandImage(StageDefinedImage):
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
    platform: str
    digest: Optional[str] = None

    def local_hash_data(self, symbolic: bool) -> Any:
        if symbolic:
            return [self.repo, self.tag, self.platform]

        if self.digest is None:
            raise ValueError("Cannot full hash SourceImage with unresolved digest")

        return self.digest


@dataclass(eq=False)
class MultiPlatformImage(StageDefinedImage):
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
        platform: The platform to select for this base image.
        image: The build graph behind this base image. This can be None if
            the base image will not be dereferenced.
        content_hash: The conent hash of the base image. Typically this is
            supplied from tplbuild's cached build data and is used to find
            the base image from an external repository.
        digest: The digest of the image as stored in the registry.
    """

    profile: str
    stage: str
    platform: str
    image: Optional[ImageDefinition] = None
    content_hash: Optional[str] = None
    digest: Optional[str] = None

    def get_dependencies(self) -> List[ImageDefinition]:
        return [self.image] if self.image else []

    def set_dependencies(self, deps: Iterable[ImageDefinition]) -> None:
        if deps:
            (self.image,) = deps

    def local_hash_data(self, symbolic: bool) -> Any:
        if symbolic:
            return [self.profile, self.stage, self.platform]

        if self.content_hash is None:
            raise ValueError("Cannot hash BaseImage with unresolved content hash")

        return self.content_hash


@dataclass(eq=False)
class ContextImage(StageDefinedImage):
    """Image node representing a build context"""

    context: BuildContext
    platform: str

    def local_hash_data(self, symbolic: bool) -> Any:
        return [
            self.platform,
            self.context.symbolic_hash if symbolic else self.context.full_hash,
        ]


@dataclass(eq=False)
class StageData:
    """
    Dataclass holding metadata about a rendered image stage.
    """

    #: The name of the build stage
    name: str
    #: The image definition
    image: ImageDefinition
    #: The stage config
    config: StageConfig
    #: If this is a base image this will be set as the appropriate base
    #: image reference.
    base_image: Optional[BaseImage] = None
