#!.venv/bin/python

from __future__ import annotations

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
    "atomic_number": int,
    "symbol": str,
    "embed_color": int,
    "path": str,
    "pronouns": str,
    "author": str
}

ELEMENT_SCHEMA_OPTIONAL: dict[str, type | dict[Self]] = {
    "coordinates": {"x": int, "y": int},
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

    atomic_number: int
    """The element's atomic number."""

    icon: Image.Image
    """The element's icon."""

    pronouns: str # chemistry if it was WOKE
    """The element's pronouns."""

    embed_color: int
    """The embed color for the element."""

    author: str
    """The author of the element's design."""

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
    table: Image.Image
    elements_by_atomic_number: dict[int, Element]
    elements_by_symbol: dict[str, Element]
    elements_by_name: dict[str, Element]

    def __init__(self, *args, **kwargs):
        self.client = None
        self.parser = None
        self.table = None
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
            self.table = image
        self.parser = ImageScraper(cb)
        self.sync_image()
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
            if "coordinates" in raw_element:
                coords = raw_element["coordinates"]
                # Slice the element from the table and save it
                icon = self.table.crop((
                    coords["x"] - 1, coords["y"] - 1,
                    coords["x"] + config.element_size[0] + 1, coords["y"] + config.element_size[1] + 1
                ))
                icon.save(Path("elements") / raw_element['path'], format = "PNG")
            with Image.open(Path("elements") / raw_element['path']) as im:
                icon = im.copy()
            element = Element(
                name,
                raw_element["symbol"],
                raw_element["atomic_number"],
                icon,
                raw_element["pronouns"],
                raw_element["embed_color"],
                raw_element["author"],
            )
            self.elements_by_name[name.lower()] = element
            if element.atomic_number is not None:
                self.elements_by_atomic_number[element.atomic_number] = element
            if element.symbol is not None:
                self.elements_by_symbol[element.symbol.lower()] = element
        print("Loaded elements!")
        
    
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