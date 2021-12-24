import asyncio

from .tplbuild import TplBuild


async def main():
    """
    Main tplbuild entrypoint.
    """
    bld = TplBuild.from_path(".")
    stages = bld.render()
    # print(stages)
    build_ops = bld.plan(stages.values())
    for build_op in build_ops:
        print(type(build_op.image), [stage.name for stage in build_op.stages])

    await bld.build(build_ops)


asyncio.run(main())
