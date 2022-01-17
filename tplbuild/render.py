import dataclasses
import json
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

import jinja2

from .config import TplConfig, TplContextConfig
from .context import BuildContext
from .exceptions import TplBuildException, TplBuildTemplateException
from .images import (
    BaseImage,
    CommandImage,
    ContextImage,
    CopyCommandImage,
    ImageDefinition,
    SourceImage,
)
from .utils import json_decode, json_encode, json_raw_decode, line_reader, visit_graph

RESERVED_STAGE_NAMES = {"scratch"}

ImageDescriptor = Union[str, Tuple[str, str]]


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
    #: If this is a base image this will be set as the appropriate base
    #: image reference.
    base_image: Optional[BaseImage] = None


@dataclasses.dataclass(eq=False)
class _LateImageReference(ImageDefinition):
    """
    Represents a symbolic reference to another image. These should be
    resolved to other ImageDefinition objects before render returns
    any image graph data.
    """

    image_desc: ImageDescriptor

    def local_hash_data(self, symbolic: bool) -> str:
        raise NotImplementedError(
            "LateImageReference should be removed before attempting to hash"
        )


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

    def _resolve_late_references(self, stages: Dict[str, StageData]) -> None:
        """
        Update all the images in `stages` to remove any _LateImageReference
        objects and replace them with the proper image.
        """

        def _visit(image: ImageDefinition) -> ImageDefinition:
            """
            If visiting a late image reference replace it with the proper
            stage image or source image.
            """
            if not isinstance(image, _LateImageReference):
                return image

            desc = image.image_desc
            if isinstance(desc, str):
                stage = stages.get(desc)
                if stage is None:
                    raise TplBuildException(
                        f"Cannot resolve image reference to {repr(desc)}"
                    )

                return stage.base_image or stage.image

            if isinstance(desc, list) and len(desc) == 2:
                return SourceImage(
                    repo=desc[0],
                    tag=desc[1],
                )

            raise TplBuildException(f"Malformed image desc {repr(desc)}")

        stage_images = visit_graph(
            (stage_data.image for stage_data in stages.values()),
            _visit,
        )
        for stage_data, stage_image in zip(stages.values(), stage_images):
            stage_data.image = stage_image

    def render(
        self, config_name: str, config_data: Dict[str, Any]
    ) -> Dict[str, StageData]:
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
                "tags": tags,
                "push_tags": push_tags,
            }
            metadata = {key: val for key, val in metadata.items() if val}
            return (
                f"TPLFROM {json_encode({'parent': parent, 'name': stage_name})}\n"
                f"METADATA {json_encode(metadata)}\n"
            )

        dockerfile_data = self.jinja_env.get_template("Dockerfile.tplbuild").render(
            begin_stage=_begin_stage,
            **config_data,
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

        image_stack: List[ActiveImage] = []
        image_metadata: Dict[str, Dict[str, Any]] = {}

        def _pop_image_stack():
            """
            Pop the image on the top of the stack and add the stage data to the
            result.
            """
            img = image_stack.pop()
            if img.name in result:
                raise TplBuildException(f"Duplicate stage names {repr(img.name)}")

            metadata = image_metadata.get(img.name, {})
            stage_data = StageData(
                name=img.name,
                image=img.image,
                tags=tuple(metadata.get("tags", [])),
                push_tags=tuple(metadata.get("push_tags", [])),
            )
            if metadata.get("base"):
                stage_data.base_image = BaseImage(
                    image=img.image,
                    config=config_name,
                    stage=img.name,
                )
            result[img.name] = stage_data

        for line_num, line in line_reader(dockerfile_data):
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
                        image=_LateImageReference(line_parts[0]),
                        name=line_parts[2],
                    )
                )
            elif cmd == "TPLFROM":
                try:
                    from_image_desc = json_decode(line)
                except json.JSONDecodeError as exc:
                    raise TplBuildException(
                        f"{line_num}: Failed to parse TPLFROM data"
                    ) from exc

                image_stack.append(
                    ActiveImage(
                        image=_LateImageReference(from_image_desc["parent"]),
                        name=from_image_desc["name"],
                    )
                )
            elif cmd == "END":
                if line:
                    raise TplBuildException(
                        f"{line_num}: Unexpected extra data after END command"
                    )
                _pop_image_stack()
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
                            ctx_name, pos = json_raw_decode(line)
                        except json.JSONDecodeError as exc:
                            raise TplBuildException(
                                f"{line_num}: Failed to parse COPY --from argument"
                            ) from exc
                        line = line[pos:].lstrip()
                    else:
                        line_parts = line.split(maxsplit=1)
                        ctx_name = line_parts[0]
                        line = line_parts[1] if len(line_parts) > 1 else ""

                    ctx = _LateImageReference(ctx_name)

                if ctx is None:
                    raise TplBuildException(
                        f"{line_num}: Cannot COPY from null context"
                    )

                assert not isinstance(ctx, str)
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
                    metadata = json_decode(line)
                except json.JSONDecodeError as exc:
                    raise TplBuildException(
                        f"{line_num}: Failed to parse METADATA data"
                    ) from exc
                image_metadata[image_stack[-1].name] = metadata
                if "context" in metadata:
                    image_stack[-1].contexts = [
                        _LateImageReference(metadata["context"])
                    ]
            elif cmd == "PUSHCONTEXT":
                if not image_stack:
                    raise TplBuildException(
                        f"{line_num}: Expected image start, not {cmd}"
                    )
                push_context = line
                if line and line[0] in '"[':
                    try:
                        push_context = json_decode(line)
                    except json.JSONDecodeError as exc:
                        raise TplBuildException(
                            f"{line_num}: Failed to parse PUSHCONTEXT data"
                        ) from exc
                image_stack[-1].contexts.append(_LateImageReference(push_context))
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
            _pop_image_stack()

        # TODO(msg): Make this a bit cleaner

        self._resolve_late_references(result)

        return result
