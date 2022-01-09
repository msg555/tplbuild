import asyncio

from .tplbuild import TplBuild


async def main():
    """
    Main tplbuild entrypoint.
    """
    base = True

    bld = TplBuild.from_path(".")
    stages = bld.render()

    if base:
        stages = [stage for stage in stages.values() if stage.base_image is not None]
    else:
        stages = [stage for stage in stages.values() if stage.tags or stage.push_tags]

    await bld.resolve_source_images(stages)
    await bld.resolve_base_images(stages, dereference=base)
    # print(stages)
    build_ops = bld.plan(stages)
    for build_op in build_ops:
        print(type(build_op.image), [stage.name for stage in build_op.stages])

    await bld.build(build_ops)


asyncio.run(main())
