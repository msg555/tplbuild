from typing import List, Iterable



class StageData:
    pass


class BuildOperation:
    pass


class TplBuild:
    def __init__(self, config) -> None:
        # Use pydantic?
        self.config = copy.deepcopy(config)


    def plan(self, stages: Iterable[StageData]) -> List[BuildOperation]:
        return []


    def get_source_image(self, repo: str, tag: str) -> Optional[SourceImage]:
