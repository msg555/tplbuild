from dataclasses import dataclass
import os
from typing import Any, Dict, List, Iterable, Optional, Tuple

import yaml

from .config import TplConfig
from .exceptions import TplBuildException
from .images import (
    ImageDefinition,
    SourceImage,
)
from .render import (
    BuildRenderer,
    StageData,
)


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
        self.renderer = BuildRenderer(self.base_dir, self.config)

    def _get_config_data(
        self,
        config_name: Optional[str] = None,
        *,
        platform: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Returns the config data associated with the passed config name.
        """
        if config_name is None:
            config_name = self.config.default_config
            if config_name is None and self.config.configs:
                config_name = next(iter(self.config.configs))

        if config_name is None:
            # If no config was requested nor are any configured use an emtpy
            # configuration dictionary.
            config_data = {}
        else:
            try:
                config_data = self.config.configs[config_name]
            except KeyError as exc:
                raise TplBuildException(
                    f"Config {repr(config_name)} does not exist"
                ) from exc

        return {
            "config": config_data,
            "config_name": config_name,
            "platform": platform,
        }

    def render(
        self,
        config_name: Optional[str] = None,
        *,
        platform: Optional[str] = None,
    ) -> Dict[str, StageData]:
        """
        Render all contexts and stages into StageData.
        """
        return self.renderer.render(
            self._get_config_data(config_name, platform=platform)
        )

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
