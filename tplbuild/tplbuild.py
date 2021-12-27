import json
import logging
import os
from typing import Any, Dict, List, Iterable, Optional

import yaml

from .config import (
    BuildData,
    TplConfig,
)
from .exceptions import TplBuildException
from .executor import BuildExecutor
from .images import SourceImage
from .plan import (
    BuildPlanner,
    BuildOperation,
)
from .render import (
    BuildRenderer,
    StageData,
)

LOGGER = logging.getLogger(__name__)


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
        self.planner = BuildPlanner()
        self.renderer = BuildRenderer(self.base_dir, self.config)
        self.executor = BuildExecutor(self.config.client)
        try:
            with open(
                os.path.join(base_dir, ".tplbuilddata.json"), encoding="utf-8"
            ) as fbuilddata:
                self.build_data = BuildData(**json.load(fbuilddata))
        except FileNotFoundError:
            LOGGER.warning(".tplbuilddata.json not found, using empty bulid data")
            self.build_data = BuildData()

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

    def plan(self, stages: Iterable[StageData]) -> List[BuildOperation]:
        """
        Plan how to build the given list of stage names.
        """
        # pylint: disable=unused-argument,no-self-use
        return self.planner.plan(stages)

    async def build(self, build_ops: Iterable[BuildOperation]) -> None:
        """
        Execute the build operatoins.
        """
        await self.executor.build(build_ops)

    def get_source_image(self, repo: str, tag: str) -> Optional[SourceImage]:
        """
        Return a ImageDefinition representation of the requested source image
        or None if there is no such source image set.
        """
        # pylint: disable=unused-argument,no-self-use
        return None
