import dataclasses
import json
import os
from typing import Any, Dict, Iterable, Optional, Tuple, Union

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

RESERVED_STAGE_NAMES = {"scratch"}

ImageDescriptor = Union[str, Tuple[str, str]]


def _json_encode(data: Any) -> str:
    """Helper function to encode JSON data"""
    return json.dumps(data)


def _json_decode(data: str) -> Any:
    """Helper function to decode JSON data"""
    return json.loads(data)


def _line_reader(document: str) -> Iterable[str]:
    """
    Yield lines from `document`. Lines will have leading and trailing whitespace
    stripped. Lines that being with a '#' character will be omitted. Lines that
    end with a single backslash character will be treated as continuations with
    the following line concatenated onto itself, not including the backslash or
    line feed character.
    """
    line_parts = []
    lines = document.splitlines()
    for idx, line_part in enumerate(lines):
        line_part = line_part.rstrip()
        if line_part.endswith("\\") and not line_part.endswith("\\\\"):
            line_parts.append(line_part[:-1])
            if idx + 1 < len(lines):
                continue
            line_part = ""

        line = ("".join(line_parts) + line_part).strip()
        line_parts.clear()
        if line and line[0] != "#":
            yield line


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
        if context_name in RESERVED_STAGE_NAMES:
            raise TplBuildException(
                f"Cannot name context {repr(context_name)}, name is reserved"
            )

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
            ignore_data = self.jinja_env.from_string(ignore_data).render(
                config=config_data,
            )
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

        def _begin_stage(
            stage_name: str,
            parent: ImageDescriptor,
            *,
            context: Optional[str] = None,
            base: bool = False,
            tags: Iterable[str] = (),
            push_tags: Iterable[str] = (),
        ):
            metadata = {
                "context": context,
                "base": base,
                "tag": tags,
                "push_tags": push_tags,
            }
            metadata = {key: val for key, val in metadata.items() if val}
            return (
                f"TPLFROM {_json_encode({'parent': parent, 'name': stage_name})}\n"
                f"METADATA { _json_encode(metadata) }\n"
            )

        dockerfile_data = self.jinja_env.get_template("Dockerfile.tplbuild").render(
            begin_stage=_begin_stage,
            **config_data,
        )

        for line in _line_reader(dockerfile_data):
            line_parts = line.split(maxsplit=1)
            cmd = line_parts[0].upper()
            line = line_parts[1] if len(line_parts) > 1 else ""

            if cmd == "FROM":
                print("normalfrom", line)
            elif cmd == "TPLFROM":
                from_image_desc = _json_decode(line)
                print("tplfrom", from_image_desc)
            elif cmd == "RUN":
                print("run stuff", line)
            elif cmd == "COPY":
                print("copy stuff", line)
            elif cmd == "METADATA":
                metadata = _json_decode(line)
                print("stage metadata", metadata)
            elif cmd == "PUSHCONTEXT":
                push_context = line
                if line and line[0] in '"[':
                    push_context = _json_decode(line)
                print("push context", push_context)
            elif cmd == "POPCONTEXT":
                print("pop context")
            elif cmd in ("ENTRYPOINT", "COMMAND", "WORKDIR", "ENV"):
                print("image config", line)
            else:
                raise TplBuildException(f"Unsupported build command {repr(cmd)}")

        return result
