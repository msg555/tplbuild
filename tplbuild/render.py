import dataclasses
import json
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

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
    CopyCommandImage,
    ImageDefinition,
    CommandImage,
)

RESERVED_STAGE_NAMES = {"scratch"}

ImageDescriptor = Union[str, Tuple[str, str]]


def _json_encode(data: Any) -> str:
    """Helper function to encode JSON data"""
    return json.dumps(data)


def _json_decode(data: str) -> Any:
    """Helper function to decode JSON data"""
    return json.loads(data)


def _line_reader(document: str) -> Iterable[Tuple[int, str]]:
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
            yield idx, line


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
        # pylint: disable=no-self-use
        result = {
            context_name: StageData(
                name=context_name,
                image=self._render_context(context_name, context_config, config_data),
            )
            for context_name, context_config in self.config.contexts.items()
        }

        # Determine the default context as either the context named "default"
        # or the first context listed. If there are no contexts default_context
        # will just be None.
        default_context = None
        if "default" in result:
            default_context = result["default"].image
        elif result:
            default_context = next(iter(result.values())).image

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

        @dataclasses.dataclass
        class LateImageReference(ImageDefinition):
            """
            Represents a symbolic reference to another image. These should be
            resolved to other ImageDefinition objects before render returns
            any image graph data.
            """

            image_desc: ImageDescriptor

            def calculate_hash(self, symbolic: bool) -> str:
                raise NotImplementedError(
                    "LateImageReference should be removed before attempting to hash"
                )

        @dataclasses.dataclass
        class ActiveImage:
            """
            Tracks metadata on an active image in the image stack.
            """

            name: str
            image: ImageDefinition
            contexts: List[Optional[ImageDefinition]] = dataclasses.field(
                default_factory=lambda: [default_context]
            )

        image_stack = []
        image_metadata: Dict[str, Dict[str, Any]] = {}
        for line_num, line in _line_reader(dockerfile_data):
            line_parts = line.split(maxsplit=1)
            cmd = line_parts[0].upper()
            line = line_parts[1] if len(line_parts) > 1 else ""

            if cmd == "FROM":
                line_parts = line.split()
                if len(line_parts) == 1:
                    raise TplBuildException(
                        f"{line_num}: FROM without a stage name not supported"
                    )
                if len(line_parts) != 3 or line_parts[1].upper() != "AS":
                    raise TplBuildException(
                        f"{line_num}: Expected FROM parent AS stage_name"
                    )
                image_stack.append(
                    ActiveImage(
                        image=LateImageReference(line_parts[0]),
                        name=line_parts[2],
                    )
                )
            elif cmd == "TPLFROM":
                try:
                    from_image_desc = _json_decode(line)
                except json.JSONDecodeError as exc:
                    raise TplBuildException(
                        f"{line_num}: Failed to parse TPLFROM data"
                    ) from exc

                image_stack.append(
                    ActiveImage(
                        image=LateImageReference(from_image_desc["parent"]),
                        name=from_image_desc["name"],
                    )
                )
            elif cmd == "END":
                if line:
                    raise TplBuildException(
                        f"{line_num}: Unexpected extra data after END command"
                    )
                if image_stack[-1].name in result:
                    raise TplBuildException(
                        f"Duplicate stage names {repr(image_stack[-1].name)}"
                    )
                img = image_stack[-1]
                metadata = image_metadata.get(img.name, {})
                result[img.name] = StageData(
                    name=img.name,
                    image=img.image,
                    tags=tuple(metadata.get("tags", [])),
                    push_tags=tuple(metadata.get("push_tags", [])),
                    base=metadata.get("base", False),
                )
                image_stack.pop()
            elif cmd in ("RUN", "ENTRYPOINT", "COMMAND", "WORKDIR", "ENV"):
                if not image_stack:
                    raise TplBuildException(
                        f"{line_num}: Expected image start, not {cmd}"
                    )
                image_stack[-1].image = CommandImage(
                    parent=image_stack[-1].image,
                    command=cmd,
                    args=line,
                )
            elif cmd == "COPY":
                if not image_stack:
                    raise TplBuildException(
                        f"{line_num}: Expected image start, not {cmd}"
                    )

                ctx = image_stack[-1].contexts[-1]

                if line.startswith("--from="):
                    line = line[7:]
                    if line[0] in '"[':
                        try:
                            ctx_name, pos = json.JSONDecoder().raw_decode(line)
                            line = line[pos:].lstrip()
                        except json.JSONDecodeError as exc:
                            raise TplBuildException(
                                f"{line_num}: Failed to parse COPY --from argument"
                            ) from exc
                    else:
                        line_parts = line.split(maxsplit=1)
                        ctx_name = line_parts[0]
                        line = line_parts[1] if len(line_parts) > 1 else ""

                    ctx = LateImageReference(ctx_name)

                if ctx is None:
                    raise TplBuildException(
                        f"{line_num}: Cannot COPY from null context"
                    )

                image_stack[-1].image = CopyCommandImage(
                    parent=image_stack[-1].image,
                    context=ctx,
                    command=line,
                )
            elif cmd == "METADATA":
                if not image_stack:
                    raise TplBuildException(
                        f"{line_num}: Expected image start, not {cmd}"
                    )
                try:
                    metadata = _json_decode(line)
                except json.JSONDecodeError as exc:
                    raise TplBuildException(
                        f"{line_num}: Failed to parse METADATA data"
                    ) from exc
                image_metadata[image_stack[-1].name] = metadata
                if "context" in metadata:
                    image_stack[-1].contexts = [metadata["context"]]
            elif cmd == "PUSHCONTEXT":
                if not image_stack:
                    raise TplBuildException(
                        f"{line_num}: Expected image start, not {cmd}"
                    )
                push_context = line
                if line and line[0] in '"[':
                    try:
                        push_context = _json_decode(line)
                    except json.JSONDecodeError as exc:
                        raise TplBuildException(
                            f"{line_num}: Failed to parse PUSHCONTEXT data"
                        ) from exc
                image_stack[-1].contexts.append(LateImageReference(push_context))
            elif cmd == "POPCONTEXT":
                if not image_stack:
                    raise TplBuildException(
                        f"{line_num}: Expected image start, not {cmd}"
                    )
                if len(image_stack[-1].contexts) <= 1:
                    raise TplBuildException(f"{line_num}: No context on stack to pop")
                image_stack[-1].contexts.pop()
            else:
                raise TplBuildException(f"Unsupported build command {repr(cmd)}")

        while image_stack:
            if image_stack[-1].name in result:
                raise TplBuildException(
                    f"Duplicate stage names {repr(image_stack[-1].name)}"
                )
            img = image_stack[-1]
            metadata = image_metadata.get(img.name, {})
            result[img.name] = StageData(
                name=img.name,
                image=img.image,
                tags=tuple(metadata.get("tags", [])),
                push_tags=tuple(metadata.get("push_tags", [])),
                base=metadata.get("base", False),
            )
            image_stack.pop()

        # TODO(msg): Make this a bit cleaner
        # TODO(msg): Resolve LateImageReferences

        return result
