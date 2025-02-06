#!.venv/bin/python

from __future__ import annotations

import numpy as np
import json
import html.parser
import urllib.request
from typing import Callable, Self
import tomllib
from dataclasses import dataclass
from pathlib import Path

import discord
from discord.ext import commands
from PIL import Image
import pytumblr

import config
import auth

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

    pronouns: str # chemistry if it was WOKE
    """The element's pronouns."""

    embed_color: int
    """The embed color for the element."""

    author: str
    """The author of the element's design."""

    image: Image.Image | tuple[str, tuple[int, int]]
    """The image, or table coordinates, of the element."""

class Context(commands.Context):
    silent: bool = False
    ephemeral: bool = False

    async def error(self, msg: str, embed: discord.Embed | None = None, **kwargs):
        try:
            await self.message.add_reaction("\u26a0\ufe0f")
        except discord.errors.NotFound:
            pass
        if embed is not None:
            return await self.reply(msg, embed=embed, **kwargs)
        else:
            return await self.reply(msg, **kwargs)

    async def send(self, content: str = "", embed: discord.Embed | None = None, **kwargs):
        content = str(content)
        kwargs['ephemeral'] = self.ephemeral
        kwargs['silent'] = self.silent
        if len(content) > 2000:
            msg = " [...] \n\n (Character limit reached!)"
            content = content[:2000 - len(msg)] + msg
        if embed is not None:
            if content:
                return await super().send(content, embed=embed, **kwargs)
            return await super().send(embed=embed, **kwargs)
        elif content:
            return await super().send(content, embed=embed, **kwargs)
        return await super().send(**kwargs)

    async def reply(self, *args, mention_author: bool = False, **kwargs):
        kwargs['mention_author'] = mention_author
        kwargs['reference'] = self.message
        kwargs['ephemeral'] = self.ephemeral
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

class Bot(commands.Bot):
    client: pytumblr.TumblrRestClient
    parser: ImageScraper
    tables: dict[str, Image.Image]
    elements_by_atomic_number: dict[int, Element]
    elements_by_symbol: dict[str, Element]
    elements_by_name: dict[str, Element]

    def __init__(self, *args, **kwargs):
        self.client = None
        self.parser = None
        self.tables = {}
        self.elements_by_atomic_number = {}
        self.elements_by_symbol = {}
        self.elements_by_name = {}
        super().__init__(*args, **kwargs)

    async def on_ready(self):
        if "commands" in self.extensions:
            await self.unload_extension("commands")
        await self.load_extension("commands")
        self.client = pytumblr.TumblrRestClient(
            auth.CONSUMER_KEY,
            auth.CONSUMER_SECRET,
            auth.OAUTH_TOKEN,
            auth.OAUTH_SECRET
        )
        def cb(image: Image.Image):
            nonlocal self
            image.save("elements/normal.png")
            self.tables["normal"] = image
        self.parser = ImageScraper(cb)
        self.sync_image()
        with Image.open("elements/nonperiodics.png") as im:
            im.load()
            self.tables["nonperiodics"] = im
        with Image.open("elements/genderswap.png") as im:
            im.load()
            self.tables["genderswap"] = im
        self.load_elements()
        print("Ready!")

    def load_elements(self):
        print("Loading elements...")
        self.elements_by_name = {}
        self.elements_by_atomic_number = {}
        self.elements_by_symbol = {}        
    
        with open("elements.toml", "rb") as f:
            raw_elements = tomllib.load(f)
        for name, raw_element in raw_elements.items():
            things_wrong = check_schema(raw_element, ELEMENT_SCHEMA, ELEMENT_SCHEMA_OPTIONAL)
            assert not len(things_wrong), f"Element `{name}` has a malformed entry!\n" + "\n".join(things_wrong)
            if "table" in raw_element:
                assert "coordinates" in raw_element, F"Element `{name}` has a table, but no coordinates!"
                image = (raw_element["table"], (raw_element["coordinates"]["x"], raw_element["coordinates"]["y"]))
            else:
                assert "path" in raw_element, F"Element `{name}` has no table or path!"
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
                image
            )
            self.elements_by_name[name.lower()] = element
            if element.atomic_number is not None:
                self.elements_by_atomic_number[element.atomic_number] = element
            if element.symbol != "???":
                raw_symbol = element.symbol.lower()
                for a, b in zip([*"₀₁₂₃₄₅₆₇₈₉", "ⓢ", "**n**", "×"], [*"0123456789", "(s)", "n", "*"]):
                    raw_symbol = raw_symbol.replace(a, b)
                self.elements_by_symbol[raw_symbol] = element
        print("Generating Omnium...")        
        omnium = np.array([self.get_element_icon(el).convert("RGB") for el in self.elements_by_atomic_number.values()], dtype=np.uint8)
        omnium = np.average(omnium, axis = 0).astype(np.uint8)
        omnium = Image.fromarray(omnium)
        omnium_embed = np.array([(*el.embed_color.to_bytes(3, "big"), ) for el in self.elements_by_atomic_number.values()], dtype=np.uint8)
        omnium_embed = np.average(omnium_embed, axis = 0).astype(int)
        omnium_embed = int(omnium_embed[0]) << 16 | int(omnium_embed[1]) << 8 | int(omnium_embed[2])
        omnium = Element("Omnium", "???", None, "any/all", omnium_embed, "@everyone", omnium)
        self.elements_by_name["omnium"] = omnium
        print("Loaded elements!")
        
    def get_element_icon(self, el: Element, genderswap = False):
        if type(el.image) is tuple:
            el_table = el.image[0]
            if genderswap and el_table == "normal":
                el_table = "genderswap"
            return self.tables[el_table].crop((el.image[1][0] - 1, el.image[1][1] - 1, el.image[1][0] + config.element_size[0] + 1, el.image[1][1] + config.element_size[1] + 1))
        return el.image
    
    def sync_image(self):
        print("Loading image...")
        info = self.client.posts("elementcattos", id=config.post_id)
        table_post = info["posts"][0]
        table_data = table_post["trail"][0]
        table_content = table_data["content_raw"]
        self.parser.reset()
        self.parser.feed(table_content)
        print("Loaded image!")
    
    async def get_context(self, message: discord.Message, **kwargs) -> Context:
        return await super().get_context(message, cls=Context)

def main():
    discord.utils.setup_logging()

    bot = Bot(
        command_prefix=config.prefixes,
        strip_after_prefix=True,
        description = config.description,
        allowed_mentions=discord.AllowedMentions(everyone = False, roles = False, users = False),
        intents=discord.Intents(messages = True, message_content = True, guilds = True),
        member_cache_flags=discord.MemberCacheFlags.none(),
        max_messages=None,
        chunk_guilds_at_startup=None,
        owner_ids=config.owner_ids
    )

    bot.run(auth.DISCORD_TOKEN, log_handler=None)

if __name__ == "__main__":
    main()
