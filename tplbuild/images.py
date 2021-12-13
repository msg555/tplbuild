import abc
from dataclasses import dataclass
import functools

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
        `       Returns the "full hash" of this image node. This is a hash over every
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


@dataclass
class RunCommandImage(ImageDefinition):
    """Image node ending in a RUN command."""

    parent: ImageDefinition
    command: str

    def calculate_hash(self, symbolic: bool) -> str:
        """Calculate the hash of the image node."""
        return json_hash(
            [
                type(self).__name__,
                self.parent.symbolic_hash if symbolic else self.parent.full_hash,
                self.command,
            ]
        )


@dataclass
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


@dataclass
class SourceImage(ImageDefinition):
    """Image node representing a source image"""

    repo: str
    manifest_hash: str

    def calculate_hash(self, symbolic: bool) -> str:
        """Calculate the hash of the image node."""
        return json_hash(
            [
                type(self).__name__,
                self.manifest_hash,
            ]
        )


@dataclass
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


@dataclass
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
