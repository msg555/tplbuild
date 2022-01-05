import asyncio

from .tplbuild import TplBuild


async def main():
    """
    Main tplbuild entrypoint.
    """
    base = True

    bld = TplBuild.from_path(".")
    stages = bld.render()
    for stage_name, stage in stages.items():
        print(stage_name, stage.tags)

    stages = [stage for stage in stages.values() if bool(stage.base_image) == base]

    await bld.resolve_source_images(stages)
    await bld.resolve_base_images(stages, dereference=base)
    # print(stages)
    build_ops = bld.plan(stages)
    for build_op in build_ops:
        print(type(build_op.image), [stage.name for stage in build_op.stages])

    await bld.build(build_ops)


asyncio.run(main())
