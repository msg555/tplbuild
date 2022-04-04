import dataclasses
import os
from typing import Any, Dict, List, Optional

from aioregistry import parse_image_name

from .config import StageConfig, TplContextConfig
from .context import BuildContext
from .exceptions import TplBuildException, TplBuildTemplateException
from .graph import visit_graph
from .images import (
    BaseImage,
    CommandImage,
    ContextImage,
    CopyCommandImage,
    ImageDefinition,
    SourceImage,
    StageData,
    StageDescriptor,
)
from .tplbuild import TplBuild
from .utils import line_reader

RESERVED_STAGE_NAMES = {"scratch"}


@dataclasses.dataclass(eq=False)
class _LateImageReference(ImageDefinition):
    """
    Represents a symbolic reference to another image. These should be
    resolved to other ImageDefinition objects before render returns
    any image graph data.
    """

    image_name: str

    def local_hash_data(self, symbolic: bool) -> str:
        raise NotImplementedError(
            "LateImageReference should be removed before attempting to hash"
        )


def _render_context(
    tplbld: TplBuild,
    context_config: TplContextConfig,
    profile_data: Dict[str, Any],
    stage_desc: StageDescriptor,
) -> ContextImage:
    """
    Renders a context config into a ContextImage graph representation.
    """
    if stage_desc.name in RESERVED_STAGE_NAMES:
        raise TplBuildException(
            f"Cannot name context {repr(stage_desc.name)}, name is reserved"
        )

    ignore_data = context_config.ignore
    if ignore_data is None:
        ignore_file = context_config.ignore_file or ".dockerignore"
        try:
            with open(
                os.path.join(tplbld.base_dir, ignore_file), encoding="utf-8"
            ) as fign:
                ignore_data = fign.read()
        except FileNotFoundError as exc:
            if context_config.ignore_file is not None:
                raise TplBuildException(
                    f"Missing ignore file {repr(context_config.ignore_file)}"
                ) from exc
            ignore_data = ""

    try:
        ignore_data = tplbld.jinja_render(
            ignore_data,
            dict(
                platform=stage_desc.platform,
                **profile_data,
            ),
            file_env=True,
        )
    except TplBuildTemplateException as exc:
        exc.update_message(
            f"Failed to render ignore context for {repr(stage_desc.name)}: {exc}"
        )
        raise

    return ContextImage(
        stage_descs={stage_desc},
        context=BuildContext(
            context_config.base_dir,
            None if context_config.umask is None else int(context_config.umask, 8),
            ignore_data.split("\n"),
        ),
        platform=stage_desc.platform,
    )


def _resolve_late_references(stages: Dict[str, StageData], platform: str) -> None:
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

        stage = stages.get(image.image_name)
        if stage is not None:
            return stage.base_image or stage.image

        try:
            image_ref = parse_image_name(image.image_name)
        except ValueError as exc:
            raise TplBuildException(
                f"Malformed image name {repr(image.image_name)}"
            ) from exc

        repo_name = "/".join(image_ref.repo)
        if image_ref.registry:
            repo_name = f"{image_ref.registry}/{repo_name}"
        return SourceImage(
            repo=repo_name,
            tag=image_ref.ref,
            platform=platform,
        )

    stage_images = visit_graph(
        (stage_data.image for stage_data in stages.values()),
        _visit,
    )
    for stage_data, stage_image in zip(stages.values(), stage_images):
        stage_data.image = stage_image


def render(
    tplbld: TplBuild, profile: str, profile_data: Dict[str, Any], platform: str
) -> Dict[str, StageData]:
    """
    Renders all build contexts and stages into its graph representation.
    """
    make_stage_desc = lambda name: StageDescriptor(
        name=name,
        profile=profile,
        platform=platform,
    )

    result = {
        context_name: StageData(
            name=context_name,
            image=_render_context(
                tplbld,
                context_config,
                profile_data,
                make_stage_desc(context_name),
            ),
            config=StageConfig(),
        )
        for context_name, context_config in tplbld.config.contexts.items()
    }

    # Determine the default context as either the context named "default"
    # or the first context listed. If there are no contexts default_context
    # will just be None.
    default_context = None
    if "default" in result:
        default_context = result["default"].image
    elif result:
        default_context = next(iter(result.values())).image

    try:
        dockerfile_data = tplbld.jinja_render(
            "Dockerfile",
            dict(
                platform=platform,
                **profile_data,
            ),
            file_template=True,
            file_env=True,
        )
    except TplBuildTemplateException as exc:
        exc.update_message(f"Failed to render build file: {type(exc)}")
        raise

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

    def _pop_image_stack():
        """
        Pop the image on the top of the stack and add the stage data to the
        result.
        """
        img = image_stack.pop()
        if img.name in result:
            raise TplBuildException(f"Duplicate stage names {repr(img.name)}")

        stage_data = StageData(
            name=img.name,
            image=img.image,
            config=tplbld.get_stage_config(img.name, profile, platform),
        )
        if stage_data.config.base:
            stage_data.base_image = BaseImage(
                profile=profile,
                stage=img.name,
                platform=platform,
                image=img.image,
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
                    f"{line_num}: Expected 'FROM parent AS stage_name'"
                )
            image_stack.append(
                ActiveImage(
                    image=_LateImageReference(line_parts[0]),
                    name=line_parts[2],
                )
            )
        elif cmd == "END":
            if line:
                raise TplBuildException(
                    f"{line_num}: Unexpected extra data after END command"
                )
            _pop_image_stack()
        elif cmd in ("RUN", "ENTRYPOINT", "COMMAND", "WORKDIR", "ENV", "USER"):
            if not image_stack:
                raise TplBuildException(f"{line_num}: Expected image start, not {cmd}")
            image_stack[-1].image = CommandImage(
                stage_descs={make_stage_desc(image_stack[-1].name)},
                parent=image_stack[-1].image,
                command=cmd,
                args=line,
            )
        elif cmd == "COPY":
            if not image_stack:
                raise TplBuildException(f"{line_num}: Expected image start, not {cmd}")

            ctx = image_stack[-1].contexts[-1]

            if line.startswith("--from="):
                line_parts = line[7:].split(maxsplit=1)
                line = line_parts[1] if len(line_parts) > 1 else ""
                ctx = _LateImageReference(line_parts[0])

            if ctx is None:
                raise TplBuildException(f"{line_num}: Cannot COPY from null context")

            assert not isinstance(ctx, str)
            image_stack[-1].image = CopyCommandImage(
                stage_descs={make_stage_desc(image_stack[-1].name)},
                parent=image_stack[-1].image,
                context=ctx,
                command=line,
            )
        elif cmd == "PUSHCONTEXT":
            if not image_stack:
                raise TplBuildException(f"{line_num}: Expected image start, not {cmd}")
            image_stack[-1].contexts.append(_LateImageReference(line))
        elif cmd == "POPCONTEXT":
            if not image_stack:
                raise TplBuildException(f"{line_num}: Expected image start, not {cmd}")
            if len(image_stack[-1].contexts) <= 1:
                raise TplBuildException(f"{line_num}: No context on stack to pop")
            image_stack[-1].contexts.pop()
        else:
            raise TplBuildException(f"Unsupported build command {repr(cmd)}")

    while image_stack:
        _pop_image_stack()

    _resolve_late_references(result, platform)

    return result
