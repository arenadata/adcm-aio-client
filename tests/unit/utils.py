from typing import AsyncGenerator


async def n_entries_as_list[T](gen: AsyncGenerator[T, None], n: int) -> list[T]:
    result = []
    i = 1

    async for entry in gen:
        result.append(entry)
        if i == n:
            break
        i += 1

    return result
