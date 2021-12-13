from dataclasses import dataclass
import os
from typing import Any, Dict, List, Literal, Iterable, Optional, Tuple

import pydantic
import yaml

from .images import ImageDefinition, SourceImage


@dataclass
class StageData:
    """
    Dataclass holding metadata about a rendered image stage.
    """

    #: The name of the build stage
    name: str
    #: The image definition
    image: ImageDefinition
    #: Tags to apply tothe built image
    tags: Tuple[str, ...] = ()
    #: Tags to push for the built image
    push_tags: Tuple[str, ...] = ()
    #: True if this is a base image
    base: bool = False


@dataclass
class BuildOperation:
    """
    Dataclass describing one build work unit. Each BuildOperation roughly
    corresponds to an invocation of the underlying image builder. Each
    operation in the chain of `image`, `image.parent`,
    `image.parent.parent`, ... up to but not including `root` will
    be part of this build unit.
    """

    #: The resulting image of this build operation
    image: ImageDefinition
    #: The parent image of this build operation
    root: ImageDefinition
    #: All stages associated with the resulting image
    stages: Tuple[StageData, ...] = ()
    #: All dependent build operations
    dependencies: Tuple["BuildOperation", ...] = ()


class TplContextConfig(pydantic.BaseModel):
    """
    Config model representing a build context.
    """

    #: The base directory (relative to the config base directory) of
    #:     the build context. This must be a relative path and cannot point
    #:     above the config base directory.
    base_dir: str = "."
    #: The umask as a three digit octal string. This may also be set to
    #:     None if the context permissions should be passed through directly.
    umask: Optional[str] = "022"
    #: The ignore_file to load patterns from. If this and :attr:`ignore`
    #:     are both None then this will attempt to load ".dockerignore", using
    #:     an empty list of patterns if that cannot be loaded.
    ignore_file: Optional[str] = None
    #: Ignore file string. If present this will be used over :attr:`ignore_file`.
    ignore: Optional[str] = None

    @pydantic.validator("umask")
    def umask_valid_octal(cls, v):
        """Ensure that umask is three-digit octal sequence"""
        if v is None:
            return v
        if 0 <= int(v, 8) <= 0o777:
            raise ValueError("umask out of range")
        return v

    @pydantic.validator("base_dir")
    def normalize_base_dir(cls, v):
        """Normalize the base directory"""
        return f".{os.path.sep}{os.path.normpath(os.path.join(os.path.sep, v))[1:]}"


class TplConfig(pydantic.BaseModel):
    """
    Top level config model for tplbuild.

    Attributes:
    """

    #: Must be "1.0"
    version: Literal["1.0"] = "1.0"
    #: Image repo where base images will be stored. This will
    #:     be interpretted as a Python format string receiving the single
    #:     named argument "stage_name".
    base_iamge_repo: Optional[str] = None
    #: List of platforms to build images for. If not present only the
    #:     default platform will be used. Images will be built for each of the
    #:     platforms as an image manifest by default.
    platforms: Optional[List[str]] = None
    #: The name of the default config to use. If this is not set
    #:     or refers to a non-existant config name the first config name from
    #:     :attr:`configs` will be used instead.
    default_config: Optional[str] = None
    #: A mapping of config names to string-key template arguments to pass
    #:     to any documents rendered through Jinja for this config.
    configs: Dict[str, Dict[str, Any]] = {}
    #: A set of named build context configurations. These contexts may
    #:     be referred to by name in the build file and should be unique
    #:     among all other stages.
    contexts: Dict[str, TplContextConfig] = {"default": TplContextConfig()}


class TplBuild:
    """
    Container class for all top level build operations.

    Arguments:
        base_dir: The base directory of the build
        config: The build configuration
    """

    @classmethod
    def from_path(cls, base_dir: str) -> "TplBuild":
        """
        Create a TplBuild object from just the base directory. This will
        attempt to load a file named "tplbuild.yml" from within `base_dir`
        to load the configuration. If not found an empty configuration will
        be used.

        Arguments:
            base_dir: The base directory of the build
        """
        try:
            with open(
                os.path.join(base_dir, "tplbuild.yml"), encoding="utf-8"
            ) as fconfig:
                config = yaml.safe_load(fconfig)
        except FileNotFoundError:
            config = {}
        return TplBuild(base_dir, config)

    def __init__(self, base_dir: str, config: Dict[str, Any]) -> None:
        self.base_dir = base_dir
        self.config = TplConfig(**config)

    def render(self) -> Dict[str, StageData]:
        """
        Render all stages into StageData.
        """
        # pylint: disable=no-self-use
        return {}

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
