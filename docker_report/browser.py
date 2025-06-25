from abc import ABC, abstractmethod
from typing import Generator, Callable, Tuple, List  # flake8: noqa

# Functions that can act as a filter should accept the image name without tag as an input,
# and return True if the image is admissible.
ImageFilter = Callable[[str], bool]
# For tags, they should accept the image name and tag as arguments, in a tuple.
TagFilter = Callable[[Tuple[str, str]], bool]


class Browser(ABC):

    # Filters on the image names.
    name_filters: List[ImageFilter] = []
    # Filters on image full names.
    tag_filters: List[TagFilter] = []

    @abstractmethod
    def get_images(self) -> Generator[str, None, None]:
        pass
