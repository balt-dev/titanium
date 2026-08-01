#!.venv/bin/python

from __future__ import annotations

import asyncio
import html.parser
import json
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Self

import aiohttp
import discord
import numpy as np
import tomllib
from discord.ext import commands
from PIL import Image

import auth
import config

ELEMENT_SCHEMA: dict[str, type | dict[Self]] = {
    "symbol": str,
    "embed_color": int,
    "pronouns": str,
    "author": str,
}

ELEMENT_SCHEMA_OPTIONAL: dict[str, type | dict[Self]] = {
    "atomic_number": int,
    "coordinates": {"x": int, "y": int},
    "path": str,
    "table": str,
    "oc": bool,
}


def check_schema(obj: dict, schema: dict, optional: dict | None = None) -> list[str]:
    optional = {} if optional is None else optional
    keys = set(obj.keys())
    schema_keys = set(schema.keys())
    wrong = []
    schema_optional_keys = set(optional.keys()) | schema_keys
    if len(extra_keys := keys.difference(schema_optional_keys)):
        wrong.append(f"Extraneous keys: `{extra_keys}`")
    if len(missing_keys := schema_keys.difference(keys)):
        wrong.append(f"Missing keys: `{missing_keys}`")
    schema_or_opt = schema | optional
    for key in keys.intersection(schema_optional_keys):
        val = obj[key]
        ty = schema_or_opt[key]
        if isinstance(ty, type):
            if not isinstance(val, ty):
                wrong.append(f"Key of wrong type: `{key}` (expected `{ty.__name__}`)")
        else:
            wrong.extend(check_schema(val, ty))
    return wrong


@dataclass
class Element:
    name: str
    """The element's name."""

    symbol: str
    """The element's symbol."""

    atomic_number: int | None
    """The element's atomic number."""

    pronouns: str  # chemistry if it was WOKE
    """The element's pronouns."""

    embed_color: int
    """The embed color for the element."""

    author: str
    """The author of the element's design."""

    image: Image.Image | tuple[str, tuple[int, int]]
    """The image, or table coordinates, of the element."""

    oc: bool
    """Whether the element is actually someone's OC - ocs shouldn't be genderswapped."""

    async def reply(self, *args, mention_author: bool = False, **kwargs):
        kwargs["mention_author"] = mention_author
        kwargs["reference"] = self.message
        kwargs["ephemeral"] = self.ephemeral
        return await self.send(*args, **kwargs)


class ImageScraper(html.parser.HTMLParser):
    seen_image: bool = False
    callback: Callable

    def __init__(self, callback: Callable):
        super().__init__()
        self.seen_image = False
        self.callback = callback

    def reset(self):
        super().reset()
        self.seen_image = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "img" and not self.seen_image:
            src = attrs["srcset"].split(", ")[-1].split(" ")[0]
            with urllib.request.urlopen(src) as f:
                with Image.open(f) as im:
                    (self.callback)(im.copy().convert("RGBA"))
            self.seen_image = True


GENDERSWAPPED = {"normal": "genderswap", "nonperiodics": "genderswap_nonperiodics"}


class Bot(commands.Bot):
    tables: dict[str, Image.Image]
    elements_by_atomic_number: dict[int, Element]
    elements_by_symbol: dict[str, Element]
    elements_by_name: dict[str, Element]
    elements_by_table: dict[str, list[Element]]

    def __init__(self, *args, **kwargs):
        self.tables = {}
        self.elements_by_atomic_number = {}
        self.elements_by_symbol = {}
        self.elements_by_name = {}
        self.elements_by_table = {}
        super().__init__(*args, **kwargs)

    def shutdown(self):
        sys.exit(0)

    async def on_ready(self):
        await self.sync_image()
        self.load_elements()
        if "commands" in self.extensions:
            await self.unload_extension("commands")
        await self.load_extension("commands")
        await self.tree.sync()

        print("Ready!")

    def load_elements(self):
        print("Loading elements...")
        self.elements_by_name = {}
        self.elements_by_atomic_number = {}
        self.elements_by_symbol = {}
        self.elements_by_table = {}

        with open("elements.toml", "rb") as f:
            raw_elements = tomllib.load(f)
        for name, path in raw_elements["tables"].items():
            with Image.open(Path("elements") / path) as im:
                im.load()
                self.tables[name] = im
        del raw_elements["tables"]
        for name, raw_element in raw_elements.items():
            things_wrong = check_schema(
                raw_element, ELEMENT_SCHEMA, ELEMENT_SCHEMA_OPTIONAL
            )
            assert not len(things_wrong), (
                f"Element `{name}` has a malformed entry!\n" + "\n".join(things_wrong)
            )
            if "table" in raw_element:
                assert "coordinates" in raw_element, (
                    f"Element `{name}` has a table, but no coordinates!"
                )
                image = (
                    raw_element["table"],
                    (raw_element["coordinates"]["x"], raw_element["coordinates"]["y"]),
                )
            else:
                assert "path" in raw_element, f"Element `{name}` has no table or path!"
                with Image.open(Path("elements") / raw_element["path"]) as im:
                    im.load()
                    image = im
            element = Element(
                name,
                raw_element["symbol"],
                raw_element.get("atomic_number"),
                raw_element["pronouns"],
                raw_element["embed_color"],
                raw_element["author"],
                image,
                raw_element.get("oc", False),
            )
            if "table" in raw_element:
                if raw_element["table"] not in self.elements_by_table:
                    self.elements_by_table[raw_element["table"]] = []
                self.elements_by_table[raw_element["table"]].append(element)
            self.elements_by_name[name.lower()] = element
            if element.atomic_number is not None:
                self.elements_by_atomic_number[element.atomic_number] = element
            if element.symbol != "???":
                raw_symbol = element.symbol.lower()
                for a, b in zip(
                    [*"₀₁₂₃₄₅₆₇₈₉", "ⓢ", "**n**", "×", "±", "↔"],
                    [*"0123456789", "(s)", "n", "*", "+/-", "<->"],
                ):
                    raw_symbol = raw_symbol.replace(a, b)
                self.elements_by_symbol[raw_symbol] = element
        print("Generating Omnium...")
        omnium = np.array(
            [
                self.get_element_icon(el).convert("RGB")
                for el in self.elements_by_atomic_number.values()
            ],
            dtype=np.uint8,
        )
        omnium = np.average(omnium, axis=0).astype(np.uint8)
        omnium = Image.fromarray(omnium)
        omnium_embed = np.array(
            [
                (*el.embed_color.to_bytes(3, "big"),)
                for el in self.elements_by_atomic_number.values()
            ],
            dtype=np.uint8,
        )
        omnium_embed = np.average(omnium_embed, axis=0).astype(int)
        omnium_embed = (
            int(omnium_embed[0]) << 16
            | int(omnium_embed[1]) << 8
            | int(omnium_embed[2])
        )
        omnium = Element(
            "Omnium", "???", None, "any/all", omnium_embed, "@everyone", omnium, False
        )
        self.elements_by_name["omnium"] = omnium

    def get_element_icon(self, el: Element, genderswap=False):
        assert not (el.oc and genderswap), (
            "People's OCs can't be genderswapped out of respect for the authors. Sorry!"
        )
        if type(el.image) is tuple:
            el_table = el.image[0]
            if genderswap:
                el_table = GENDERSWAPPED.get(el_table, el_table)
            return self.tables[el_table].crop(
                (
                    el.image[1][0] - 1,
                    el.image[1][1] - 1,
                    el.image[1][0] + config.element_size[0] + 1,
                    el.image[1][1] + config.element_size[1] + 1,
                )
            )
        return el.image

    async def sync_image(self):
        print("Loading image...")
        async with (
            aiohttp.ClientSession(raise_for_status=True) as session,
            session.get(
                "https://static.wikitide.net/elementcattoswiki/5/54/PurriodicTable.png"
            ) as response,
        ):
            with open("elements/normal.png", "wb") as f:
                while True:
                    chunk = await response.content.readany()
                    if not chunk:
                        break
                    f.write(chunk)


def main():
    discord.utils.setup_logging()

    bot = Bot(
        command_prefix=None,
        case_insensitive=True,
        description=config.description,
        allowed_mentions=discord.AllowedMentions(
            everyone=False, roles=False, users=False
        ),
        intents=discord.Intents(),
        member_cache_flags=discord.MemberCacheFlags.none(),
        max_messages=None,
        chunk_guilds_at_startup=False,
        owner_ids=config.owner_ids,
    )

    try:
        bot.run(auth.DISCORD_TOKEN, log_handler=None)
    finally:
        asyncio.run(bot.close())


if __name__ == "__main__":
    main()
