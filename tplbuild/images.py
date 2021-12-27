import abc
from dataclasses import dataclass
import functools
from typing import Iterable, List

from .hashing import json_hash
from .context import BuildContext


class ImageDefinition(metaclass=abc.ABCMeta):
    """
    Base class for all image deinitions. These abstractly represent a build
    graph.
    """

    @abc.abstractmethod
    def calculate_hash(self, symbolic: bool) -> str:
        """Calculate the hash of the image node."""

    @functools.cached_property
    def full_hash(self):
        """
        Returns the "full hash" of this image node. This is a hash over every
        input to the build. Specifically, this does a full hash on all
        build context data from disk.
        """
        return self.calculate_hash(symbolic=False)

    @functools.cached_property
    def symbolic_hash(self):
        """
        Returns the "symbolic" hash of this image node. The symbolic hash
        is like the full hash except build contexts will hash only the
        parameters of the build context (i.e. root directory and ignore
        patterns) rather than actually reading files from disk. This is
        useful for quickly determining if two  images are identical for a
        given build but is not useful across builds and can have false
        negatives.
        """
        return self.calculate_hash(symbolic=True)

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

    def calculate_hash(self, symbolic: bool) -> str:
        """Calculate the hash of the image node."""
        return json_hash(
            [
                type(self).__name__,
                self.parent.symbolic_hash if symbolic else self.parent.full_hash,
                self.command,
                self.args,
            ]
        )

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

    def calculate_hash(self, symbolic: bool) -> str:
        """Calculate the hash of the image node."""
        return json_hash(
            [
                type(self).__name__,
                self.parent.symbolic_hash if symbolic else self.parent.full_hash,
                self.context.symbolic_hash if symbolic else self.context.full_hash,
                self.command,
            ]
        )

    def get_dependencies(self) -> List[ImageDefinition]:
        return [self.parent, self.context]

    def set_dependencies(self, deps: Iterable[ImageDefinition]) -> None:
        self.parent, self.context = deps


@dataclass(eq=False)
class SourceImage(ImageDefinition):
    """Image node representing a source image"""

    repo: str
    tag: str

    def calculate_hash(self, symbolic: bool) -> str:
        """Calculate the hash of the image node."""
        return json_hash(
            [
                type(self).__name__,
                self.tag,
            ]
        )


@dataclass(eq=False)
class BaseImage(ImageDefinition):
    """Image node representing a base image"""

    config: str
    stage_name: str
    content_hash: str

    def calculate_hash(self, symbolic: bool) -> str:
        """Calculate the hash of the image node."""
        return json_hash(
            [
                type(self).__name__,
                self.content_hash,
            ]
        )


@dataclass(eq=False)
class ExternalImage(ImageDefinition):
    """
    Image node representing an external image.

    A SourceImage or BaseImage will be resolved into an ExternalImage after
    build planning before build execution.

    An ExternalImage cannot be hashed.
    """

    image: str

    def calculate_hash(self, symbolic: bool) -> str:
        """Calculate the hash of the image node."""
        raise NotImplementedError("ExternalImage cannot be hashed")


@dataclass(eq=False)
class ContextImage(ImageDefinition):
    """Image node representing a build context"""

    context: BuildContext

    def calculate_hash(self, symbolic: bool) -> str:
        """Calculate the hash of the image node."""
        return json_hash(
            [
                type(self).__name__,
                self.context.symbolic_hash if symbolic else self.context.full_hash,
            ]
        )
