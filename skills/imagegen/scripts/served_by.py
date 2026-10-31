#!/usr/bin/env python3
"""The subscription backend's runner: the vendored image_gen.py, saying what drew each image.

A claude-switch proxy picks, for each image, the provider that draws it: the ChatGPT plan's image
tool, or another provider when that plan is spent or down. It names its pick in two response
headers, one comma-separated entry per image in the order of the response's `data`:

    X-Switch-Member   provider/model that drew it, e.g. runway/gpt_image_2
    X-Switch-Funding  how it was paid: `included` (the plan's own allowance), `paid:<pot>` (that
                      pot's credits or balance) or `paid?:<pot>` (the same, the pot's balance unknown)

The Images API has no field for either and the vendored script prints neither. This runner loads
image_gen.py unmodified, hands it clients that make the same calls through the SDK's public
`with_raw_response` so the headers can be read, and after the script writes each image prints

    imagegen: <path> drawn by <provider/model> (<funding>)

A response without the headers prints no such line.

    served_by.py <image_gen.py arguments>
"""

from __future__ import annotations

import contextvars
import importlib.util
import itertools
import os
import sys
import types

IMAGE_GEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "image_gen.py")

# What the last Images API answer drew each image with, as (provider/model, funding) pairs. A
# context variable, because generate-batch runs its jobs as concurrent tasks and each job reads
# back its own call's answer.
served = contextvars.ContextVar("served", default=())


def noted(raw):
    members = raw.headers.get("x-switch-member")
    if members is not None:
        fundings = raw.headers.get("x-switch-funding", "").split(",")
        served.set(tuple(itertools.zip_longest(members.split(","), fundings, fillvalue="")))
    return raw.parse()


class Images:
    """`client.images` as the vendored script calls it, answered through `with_raw_response`."""

    def __init__(self, images):
        self.raw = images.with_raw_response

    def generate(self, **kwargs):
        return noted(self.raw.generate(**kwargs))

    def edit(self, **kwargs):
        return noted(self.raw.edit(**kwargs))


class AsyncImages(Images):
    async def generate(self, **kwargs):
        return noted(await self.raw.generate(**kwargs))


def main() -> int:
    spec = importlib.util.spec_from_file_location("image_gen", IMAGE_GEN)
    image_gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(image_gen)
    # The script makes its clients through these two, and generate, edit and generate-batch all
    # write their images through the third.
    create, create_async, write = image_gen._create_client, image_gen._create_async_client, image_gen._decode_write_and_downscale

    def write_and_say(images, outputs, **kwargs):
        # One image at a time, so an image written before a later one fails (an output that
        # already exists, without --force) is still named.
        drawn = served.get()
        for i, (image, path) in enumerate(zip(images, outputs)):
            write([image], [path], **kwargs)
            if i < len(drawn):
                member, funding = drawn[i]
                print(f"imagegen: {path} drawn by {member}" + (f" ({funding})" if funding else ""), file=sys.stderr)

    image_gen._create_client = lambda: types.SimpleNamespace(images=Images(create().images))
    image_gen._create_async_client = lambda: types.SimpleNamespace(images=AsyncImages(create_async().images))
    image_gen._decode_write_and_downscale = write_and_say
    sys.argv = [IMAGE_GEN, *sys.argv[1:]]
    return image_gen.main()


if __name__ == "__main__":
    raise SystemExit(main())
