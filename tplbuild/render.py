import dataclasses
import os
from typing import Any, Dict, Tuple

import jinja2

from .config import (
    TplConfig,
    TplContextConfig,
)
from .context import BuildContext
from .exceptions import (
    TplBuildException,
    TplBuildTemplateException,
)
from .images import (
    ContextImage,
    ImageDefinition,
)


@dataclasses.dataclass
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


class BuildRenderer:
    """
    Class responsible for rendering the build into its graph representation.
    This is responsible both for rendering templates and parsing the rendered
    build files into the build graph.
    """

    def __init__(self, base_dir: str, config: TplConfig) -> None:
        self.base_dir = base_dir
        self.config = config
        self.jinja_env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(self.base_dir),
        )

    def _render_context(
        self,
        context_name: str,
        context_config: TplContextConfig,
        config_data: Dict[str, Any],
    ) -> ContextImage:
        """
        Renders a context config into a ContextImage graph representation.
        """
        ignore_data = context_config.ignore
        if ignore_data is None:
            ignore_file = context_config.ignore_file or ".dockerignore"
            try:
                with open(
                    os.path.join(self.base_dir, ignore_file), encoding="utf-8"
                ) as fign:
                    ignore_data = fign.read()
            except FileNotFoundError as exc:
                if context_config.ignore_file is not None:
                    raise TplBuildException(
                        f"Missing ignore file {repr(context_config.ignore_file)}"
                    ) from exc
                ignore_data = ""

        try:
            ignore_data = self.jinja_env.from_string(ignore_data).render(**config_data)
        except jinja2.TemplateError as exc:
            raise TplBuildTemplateException(
                f"Failed to render ignore context for {repr(context_name)}"
            ) from exc

        return ContextImage(
            context=BuildContext(
                context_config.base_dir,
                None if context_config.umask is None else int(context_config.umask, 8),
                ignore_data.split("\n"),
            )
        )

    def render(self, config_data: Dict[str, Any]) -> Dict[str, StageData]:
        """
        Renders all build contexts and stages into its graph representation.
        """
        result = {
            context_name: StageData(
                name=context_name,
                image=self._render_context(context_name, context_config, config_data),
            )
            for context_name, context_config in self.config.contexts.items()
        }
        return result
